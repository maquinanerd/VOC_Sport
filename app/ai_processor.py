#!/usr/bin/env python3
"""
Handles content rewriting using a Generative AI model with intelligent key rotation.
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, ClassVar

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from .ai_client import make_model
from .config import AI_GENERATION_CONFIG, SCHEDULE_CONFIG
from .exceptions import AIProcessorError
from .key_manager import KeyManager
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
    Handles content rewriting using a Generative AI model with intelligent key rotation.
    """
    _prompt_template: ClassVar[Optional[str]] = None

    def __init__(self):
        """
        Initializes the AI processor with a stateful key manager.
        """
        try:
            self.key_manager = KeyManager()
        except ValueError as e:
            raise AIProcessorError(f"Failed to initialize KeyManager: {e}")

        logger.info("AI Processor initialized with KeyManager.")

    @classmethod
    def _load_prompt_template(cls) -> str:
        """Loads the universal prompt from 'universal_prompt.txt'."""
        if cls._prompt_template is None:
            try:
                prompt_path = Path('universal_prompt.txt')
                if not prompt_path.exists():
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
        Safely formats a string template that may contain literal curly braces.
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
        Rewrites content using the AI, with intelligent key rotation and error handling.
        """
        prompt_template = self._load_prompt_template()

        # Prepare prompt fields (unchanged)
        videos = videos or []
        images = images or []
        tags = tags or []
        
        from urllib.parse import urlparse
        fonte = fonte_nome or source_name or ""
        if not fonte and source_url:
            try:
                fonte = urlparse(source_url).netloc.replace("www.", "")
            except Exception:
                fonte = ""

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
        }
        prompt = self._safe_format_prompt(prompt_template, fields)

        last_error = "No available keys."
        
        while True:
            key_info = self.key_manager.get_next_available_key(category)

            if not key_info:
                logger.critical("All API keys are on cooldown or have hit their quota. Cannot proceed.")
                return None, "All API keys are currently unavailable."

            key_index, api_key = key_info
            
            try:
                # Use the new model factory
                model = make_model(api_key, use_fallback=False)
                generation_config = genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    **AI_GENERATION_CONFIG,
                )
                model.generation_config = generation_config

                logger.info(f"Sending content to AI for rewriting (Key index: {key_index})...")
                response = model.generate_content(prompt)
                
                # --- Success ---
                self.key_manager.report_success(category, key_index)

                parsed_data = self._parse_response(response.text)

                if not parsed_data:
                    raise AIProcessorError("Failed to parse or validate AI response.")

                if "erro" in parsed_data:
                    return None, parsed_data["erro"]

                # --- Post-processing steps (unchanged) ---
                from .intelligence import AI_DRIVEN_CATEGORIES, validate_ai_categories
                if AI_DRIVEN_CATEGORIES:
                    ai_cats = parsed_data.get("categorias") or []
                    slug_nome_grupo = validate_ai_categories(
                        ai_cats,
                        content_html=parsed_data.get("conteudo_final", ""),
                        title_text=parsed_data.get("titulo_final", "")
                    )
                    parsed_data["__slug_nome_grupo"] = slug_nome_grupo

                focus_kw = (parsed_data.get("focus_keyphrase") or "").strip()
                if not focus_kw:
                    focus_kw = (parsed_data.get("titulo_final") or "")[:60].strip()
                
                parsed_data["__yoast_focus_kw"] = focus_kw
                parsed_data["__yoast_related_kws"] = parsed_data.get("related_keyphrases") or []
                parsed_data["__yoast_metadesc"] = (parsed_data.get("meta_description") or "").strip()

                if "conteudo_final" in parsed_data:
                    parsed_data["conteudo_final"] = sanitize_content(parsed_data["conteudo_final"])
                    try:
                        assert_no_seo_leak(parsed_data["conteudo_final"])
                    except Exception as e:
                        logger.warning("Sanitization caught SEO leak: %s", e)
                
                time.sleep(SCHEDULE_CONFIG.get('api_call_delay', 10)) # Shorter delay as we are rotating keys
                return parsed_data, None

            except google_exceptions.ResourceExhausted as e:
                last_error = str(e)
                logger.warning(f"Quota exceeded for key index {key_index} (429). Applying cooldown. Error: {last_error}")
                self.key_manager.report_failure(category, key_index)
                # Loop continues to the next key

            except Exception as e:
                last_error = str(e)
                if "API key not valid" in last_error:
                    logger.error(f"API key at index {key_index} is invalid. Discarding.")
                    self.key_manager.report_failure(category, key_index, is_permanent=True)
                elif "Publisher Model `projects/" in last_error:
                    logger.critical(f"Vertex AI path detected for key index {key_index}. This is a critical configuration error. Error: {last_error}")
                    # This is a fatal config error, maybe we should stop or at least mark key as bad
                    self.key_manager.report_failure(category, key_index)
                elif "quota" in last_error.lower() or "429" in last_error:
                    logger.warning(f"Quota exceeded for key index {key_index}. Applying cooldown. Error: {last_error}")
                    self.key_manager.report_failure(category, key_index)
                else:
                    logger.error(f"AI content generation failed for key index {key_index}: {last_error}")
                    # Report a generic failure for other errors
                    self.key_manager.report_failure(category, key_index)
                # Loop continues to the next key
        
        final_reason = f"Failed to rewrite content after trying available keys. Last error: {last_error}"
        logger.critical(final_reason)
        return None, final_reason

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, Any]]:
        """
        Parses the JSON response from the AI using a robust parser and validates its structure.
        """
        try:
            data = robust_json_parser(text)

            if data is None:
                return None
            
            if not isinstance(data, dict):
                logger.error(f"AI response is not a dictionary. Received type: {type(data)}")
                return None

            if "erro" in data:
                logger.warning(f"AI returned a rejection error: {data['erro']}")
                return data

            required_keys = ["titulo_final", "conteudo_final", "meta_description"]
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
