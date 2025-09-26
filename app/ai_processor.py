#!/usr/bin/env python3
"""
Handles content rewriting using a Generative AI model with API key failover.
"""
import json
import google.generativeai as genai
import logging
from urllib.parse import urlparse
import re
import time
from pathlib import Path 
from typing import Any, Dict, List, Optional, Tuple, ClassVar

from .config import AI_API_KEYS, SCHEDULE_CONFIG, AI_GENERATION_CONFIG, GEMINI_MODEL_ID
from .exceptions import AIProcessorError, AllKeysFailedError
from .taxonomy.intelligence import robust_json_parser

logger = logging.getLogger(__name__)

# --- BEGIN: SEO SANITIZATION UTILS (do not duplicate) ---
SEO_LEAK_PATTERNS = [
    r"\bpalavra-?chave\b",
    r"\bfocus\s*keyword\b",
    r"\bmeta\s*description\b",
    r"\byoast\b",
    r"\bseo\b",
    r"\bkeyword\b",
    r"\bdensidade\b",
    r"\blsi\b",
]

FORBIDDEN_PHRASES = [
    "saiba mais",
    "acompanhe aqui",
    "últimas notícias",
    "clique aqui",
]

HASHTAG_RE = re.compile(r"#\w+", flags=re.IGNORECASE)

def sanitize_content(html: str) -> str:
    if not html:
        return html
    cleaned = html

    # remove parágrafos inteiros que contenham jargão de SEO
    combined_pattern = "|".join(SEO_LEAK_PATTERNS)
    cleaned = re.sub(
        r"<p>[^<]*(" + combined_pattern + r")[^<]*</p>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # remove linhas “soltas” com jargão de SEO
    lines = re.split(r"(\r?\n)", cleaned)
    def _bad(s: str) -> bool:
        u = s.lower()
        return any(re.search(p, u) for p in SEO_LEAK_PATTERNS)
    cleaned = "".join(s for s in lines if not _bad(s))

    # remover hashtags
    cleaned = HASHTAG_RE.sub("", cleaned)

    # remover frases promocionais comuns
    for phrase in FORBIDDEN_PHRASES:
        cleaned = re.sub(rf"{re.escape(phrase)}.*?$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)

    # normalizar espaços
    cleaned = re.sub(r">\s+<", "><", cleaned)        # entre tags
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned

def assert_no_seo_leak(html: str):
    low = (html or "").lower()
    for pat in SEO_LEAK_PATTERNS:
        if re.search(pat, low):
            raise ValueError(f"SEO leak detectado em conteudo_final: '{pat}' encontrado.")
# --- END: SEO SANITIZATION UTILS ---

AI_SYSTEM_RULES = """
[REGRAS OBRIGATÓRIAS — CUMPRIR 100%]

NÃO incluir e REMOVER de forma explícita:
- Qualquer texto de interface/comentários dos sites (ex.: "Your comment has not been saved").
- Caixas/infobox de ficha técnica com rótulos como: "Release Date", "Runtime", "Director", "Writers", "Producers", "Cast".
- Elementos de comentários, “trending”, “related”, “read more”, “newsletter”, “author box”, “ratings/review box”.

Somente produzir o conteúdo jornalístico reescrito do artigo principal.
Se algum desses itens aparecer no texto de origem, exclua-os do resultado.
"""


class AIProcessor:
    """
    Handles content rewriting using a Generative AI model with API key failover.
    """
    _prompt_template: ClassVar[Optional[str]] = None

    def __init__(self):
        """
        Initializes the AI processor.
        It uses a single pool of API keys and rotates through them on failure.
        """
        # Flatten the dictionary of keys from config into a single list.
        # This allows the processor to cycle through all available keys regardless of category.
        all_keys = []
        if isinstance(AI_API_KEYS, dict):
            for key_list in AI_API_KEYS.values():
                if isinstance(key_list, list):
                    all_keys.extend(key for key in key_list if key)

        self.api_keys: List[str] = all_keys
        if not self.api_keys:
            raise AIProcessorError("No valid GEMINI_ API keys found in the environment. Please set at least one GEMINI_... key.")

        logger.info(f"AI Processor initialized with {len(self.api_keys)} API key(s).")

        self.current_key_index = 0
        self.model = None
        self._configure_model()

    def _configure_model(self):
        """Configures the generative AI model with the current API key."""
        if self.current_key_index >= len(self.api_keys):
            raise AllKeysFailedError(f"All {len(self.api_keys)} API keys have failed.")

        api_key = self.api_keys[self.current_key_index]
        try:
            genai.configure(api_key=api_key)
            # Enforce JSON output from the model for reliable parsing
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                **AI_GENERATION_CONFIG,
            )
            self.model = genai.GenerativeModel(
                GEMINI_MODEL_ID,
                generation_config=generation_config
            )
            logger.info(f"Configured AI model with API key index {self.current_key_index}.")
        except Exception as e:
            logger.error(f"Failed to configure Gemini with API key index {self.current_key_index}: {e}")
            self._failover_to_next_key()
            self._configure_model()  # Retry configuration with the new key

    def _failover_to_next_key(self):
        """Switches to the next available API key."""
        self.current_key_index += 1
        logger.warning("Failing over to next API key.")

    @classmethod
    def _load_prompt_template(cls) -> str:
        """Loads the universal prompt from 'universal_prompt.txt'."""
        if cls._prompt_template is None:
            try:
                # Assuming the script is run from the project root
                prompt_path = Path('universal_prompt.txt')
                if not prompt_path.exists():
                    # Fallback for when run as a module
                    prompt_path = Path(__file__).resolve().parent.parent / 'universal_prompt.txt'

                with open(prompt_path, 'r', encoding='utf-8') as f:
                    base_template = f.read()
                cls._prompt_template = f"{AI_SYSTEM_RULES}\n\n{base_template}"
            except FileNotFoundError:
                logger.critical("'universal_prompt.txt' not found in the project root.")
                raise AIProcessorError("Prompt template file not found.")
        return cls._prompt_template

    @staticmethod
    def _safe_format_prompt(template: str, fields: Dict[str, Any]) -> str:
        """
        Safely formats a string template that may contain literal curly braces
        by escaping all braces and then un-escaping only the valid placeholders.
        This prevents `ValueError: Invalid format specifier` when the prompt
        contains examples of JSON objects.
        """
        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return ""

        s = template.replace('{', '{{').replace('}', '}}')
        for key in fields:
            s = s.replace('{{' + key + '}}', '{' + key + '}')
        
        return s.format_map(_SafeDict(fields))

    def rewrite_content(
        self,
        title: Optional[str] = None,
        content_html: Optional[str] = None,
        source_url: Optional[str] = None,
        category: Optional[str] = None,
        videos: Optional[List[Dict[str, str]]] = None,
        images: Optional[List[Dict[str, str]]] = None,
        tags: Optional[List[str]] = None,
        fonte_nome: Optional[str] = None,
        source_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Rewrites the given article content using the AI model.
        This method is designed to be robust and backward-compatible.

        Args:
            title: The original title of the article.
            content_html: The full HTML content of the article.
            source_url: The original URL of the article.
            category: The content category (e.g., 'movies'). Overrides instance category.
            videos: A list of dictionaries of extracted YouTube videos.
            images: A list of extracted image URLs.
            tags: A list of extracted tags.
            fonte_nome: The name of the source (e.g., 'ScreenRant').
            source_name: Alternative name for the source.
            **kwargs: Catches extra arguments like 'domain' for backward compatibility.

        Returns:
            A tuple containing a dictionary with the rewritten text and a failure
            reason (or None if successful).
        """
        prompt_template = self._load_prompt_template()

        # Handle defaults and backward compatibility
        videos = videos or []
        images = images or []
        tags = tags or []
        
        # Determine source name, falling back to URL if necessary
        fonte = fonte_nome or source_name or ""
        if not fonte and source_url:
            try:
                fonte = urlparse(source_url).netloc.replace("www.", "")
            except Exception:
                fonte = ""  # Fallback in case of URL parsing error

        final_category = category or ""
        domain = kwargs.get("domain", "")

        fields = {
            "titulo_original": title or "",
            "url_original": source_url or "",
            "content": content_html or "",
            "domain": domain,
            "fonte_nome": fonte,
            "categoria": final_category,
            "schema_original": json.dumps(kwargs.get("schema_original"), indent=2, ensure_ascii=False) if kwargs.get("schema_original") else "Nenhum",
            "tag": (tags[0] if tags else final_category),
            "tags": (", ".join(tags) if tags else final_category),
            "videos_list": "\n".join([v.get("embed_url", "") for v in videos if isinstance(v, dict) and v.get("embed_url")]) or "Nenhum",
            "imagens_list": "\n".join([img.get('src', '') for img in images if isinstance(img, dict)]) if images else "Nenhuma",
            "titulo_final": "",
            "meta_description": "",
            "focus_keyword": "",
        }

        prompt = self._safe_format_prompt(prompt_template, fields)

        last_error = "Unknown error"
        for _ in range(len(self.api_keys)):
            try:
                logger.info(f"Sending content to AI for rewriting (Key index: {self.current_key_index})...")
                response = self.model.generate_content(prompt)

                parsed_data = self._parse_response(response.text)

                if not parsed_data:
                    raise AIProcessorError("Failed to parse or validate AI response. See logs for details.")

                # If the AI returned a specific rejection error, handle it as a failure.
                if "erro" in parsed_data:
                    return None, parsed_data["erro"]

                # --- BEGIN: APPLY CATEGORY/SEO FROM AI (do not duplicate) ---
                from .intelligence import AI_DRIVEN_CATEGORIES, validate_ai_categories
                
                if AI_DRIVEN_CATEGORIES:
                    ai_cats = parsed_data.get("categorias") or []
                    slug_nome_grupo = validate_ai_categories(
                        ai_cats,
                        content_html=parsed_data.get("conteudo_final", ""),
                        title_text=parsed_data.get("titulo_final", "")
                    )
                    parsed_data["__slug_nome_grupo"] = slug_nome_grupo

                # YOAST / Focus keyphrase
                focus_kw = (parsed_data.get("focus_keyphrase") or "").strip()
                related_kws = parsed_data.get("related_keyphrases") or []
                meta_desc = (parsed_data.get("meta_description") or "").strip()

                # guard-rails: não deixar vazio se a IA não mandar
                if not focus_kw:
                    # fallback simples = título truncado
                    focus_kw = (parsed_data.get("titulo_final") or "")[:60].strip()

                # estes três valores serão enviados ao WP após criar o post
                parsed_data["__yoast_focus_kw"] = focus_kw
                parsed_data["__yoast_related_kws"] = related_kws
                parsed_data["__yoast_metadesc"] = meta_desc
                # --- END: APPLY CATEGORY/SEO FROM AI ---

                # --- BEGIN: APPLY SANITIZATION (do not duplicate) ---
                if "conteudo_final" in parsed_data:
                    parsed_data["conteudo_final"] = sanitize_content(parsed_data["conteudo_final"])
                    # opcional: validação dura; se preferir só logar, troque por logger.warning
                    try:
                        assert_no_seo_leak(parsed_data["conteudo_final"])
                    except Exception as e:
                        logger.warning("Sanitization caught SEO leak and cleaned it: %s", e)
                # --- END: APPLY SANITIZATION ---

                # Success: Add a delay between calls to respect rate limits
                time.sleep(SCHEDULE_CONFIG.get('api_call_delay', 30))

                return parsed_data, None

            except Exception as e:
                last_error = str(e)
                logger.error(f"AI content generation failed with key index {self.current_key_index}: {last_error}")
                self._failover_to_next_key()
                if self.current_key_index < len(self.api_keys):
                    self._configure_model()
                else:
                    logger.critical("All API keys have failed.")
                    break  # Exit loop if all keys are exhausted
        
        final_reason = f"All available API keys failed. Last error: {last_error}"
        logger.critical(f"Failed to rewrite content. {final_reason}")
        return None, final_reason

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, Any]]:
        """
        Parses the JSON response from the AI using a robust parser and validates its structure.
        """
        try:
            # Use the robust parser to handle potential malformations from the AI
            data = robust_json_parser(text)

            if data is None:
                # robust_json_parser already logs the specific JSON error
                return None
            
            if not isinstance(data, dict):
                logger.error(f"AI response is not a dictionary. Received type: {type(data)}")
                return None

            # Check for a structured error response from the AI (e.g., content rejected)
            if "erro" in data:
                logger.warning(f"AI returned a rejection error: {data['erro']}")
                return data  # Return the error dict to be handled by the caller

            # Validate the presence of all required keys for a successful rewrite
            required_keys = [
                "titulo_final", "conteudo_final", "meta_description"
            ]
            missing_keys = [key for key in required_keys if key not in data]

            if missing_keys:
                logger.error(f"AI response is missing required keys: {', '.join(missing_keys)}")
                logger.debug(f"Received data: {data}")
                return None

            logger.info("Successfully parsed and validated AI response.")
            return data

        except Exception as e:
            logger.error(f"An unexpected error occurred while parsing AI response: {e}")
            logger.debug(f"Received text: {text[:500]}...")
            return None
