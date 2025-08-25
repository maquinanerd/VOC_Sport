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
from typing import Any, Dict, List, Optional, Tuple

from .config import AI_CONFIG, SCHEDULE_CONFIG
from .exceptions import AIProcessorError, AllKeysFailedError

logger = logging.getLogger(__name__)

AI_SYSTEM_RULES = """
[REGRAS OBRIGATÓRIAS — CUMPRIR 100%]

NÃO incluir e REMOVER de forma explícita:
- Qualquer texto de interface/comentários dos sites (ex.: "Your comment has not been saved").
- Caixas/infobox de ficha técnica com rótulos como: "Release Date", "Runtime", "Director", "Writers", "Producers", "Cast".
- Elementos de comentários, “trending”, “related”, “read more”, “newsletter”, “author box”, “ratings/review box”.

Somente produzir o conteúdo jornalístico reescrito do artigo principal.
Se algum desses itens aparecer no texto de origem, exclua-os do resultado.
"""

# Log the number of keys found for diagnostics at startup.
for category, keys in AI_CONFIG.items():
    # Filter out empty/None keys before counting
    valid_keys_count = len([k for k in keys if k])
    if valid_keys_count > 0:
        logger.info(f"Found {valid_keys_count} API keys for category '{category}'.")
    else:
        logger.warning(f"No API keys found for category '{category}'.")


class AIProcessor:
    """
    Handles content rewriting using a Generative AI model with API key failover.
    """
    _prompt_template: Optional[str] = None

    def __init__(self, category: str):
        """
        Initializes the AI processor for a specific content category.

        Args:
            category: The content category (e.g., 'movies', 'series').

        Raises:
            AIProcessorError: If the category is invalid or has no API keys.
        """
        if category not in AI_CONFIG:
            raise AIProcessorError(f"Invalid AI category specified: '{category}'. No configuration found.")

        self.category = category
        self.api_keys: List[str] = [key for key in AI_CONFIG.get(category, []) if key]
        if not self.api_keys:
            raise AIProcessorError(f"No valid API keys found for category '{category}'.")

        self.current_key_index = 0
        self.model = None
        self._configure_model()

    def _configure_model(self):
        """Configures the generative AI model with the current API key."""
        if self.current_key_index >= len(self.api_keys):
            raise AllKeysFailedError(f"All {len(self.api_keys)} API keys for category '{self.category}' have failed.")

        api_key = self.api_keys[self.current_key_index]
        try:
            genai.configure(api_key=api_key)
            # Enforce JSON output from the model for reliable parsing
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json"
            )
            self.model = genai.GenerativeModel(
                'gemini-1.5-flash-latest',
                generation_config=generation_config
            )
            logger.info(f"Using API key index {self.current_key_index} for category '{self.category}'.")
        except Exception as e:
            logger.error(f"Failed to configure Gemini with API key index {self.current_key_index}: {e}")
            self._failover_to_next_key()
            self._configure_model()  # Retry configuration with the new key

    def _failover_to_next_key(self):
        """Switches to the next available API key."""
        self.current_key_index += 1
        logger.warning(f"Failing over to next API key for category '{self.category}'.")

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

    def rewrite_content(
        self,
        title: Optional[str] = None,
        content_html: Optional[str] = None,
        source_url: Optional[str] = None,
        category: Optional[str] = None,
        videos: Optional[List[Dict[str, str]]] = None,
        images: Optional[List[str]] = None,
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
        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return ""

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

        final_category = category or self.category or ""
        domain = kwargs.get("domain", "")

        fields = {
            "titulo_original": title or "",
            "url_original": source_url or "",
            "content": content_html or "",
            "domain": domain,
            "fonte_nome": fonte,
            "categoria": final_category,
            "tag": (tags[0] if tags else final_category),
            "tags": (", ".join(tags) if tags else final_category),
            "videos_list": "\n".join([v.get("embed_url", "") for v in videos if isinstance(v, dict) and v.get("embed_url")]) or "Nenhum",
            "imagens_list": "\n".join(images) if images else "Nenhuma",
            "titulo_final": "",
            "meta_description": "",
            "focus_keyword": "",
        }

        # Log placeholders in the template that are not in the fields dict for debugging
        placeholders = re.findall(r"{(\w+)}", prompt_template)
        for p in placeholders:
            if p not in fields:
                logger.warning(f"Prompt template placeholder '{{{p}}}' is not in the provided fields dictionary.")

        prompt = prompt_template.format_map(_SafeDict(fields))

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
        
        final_reason = f"All API keys for category '{self.category}' failed. Last error: {last_error}"
        logger.critical(f"Failed to rewrite content. {final_reason}")
        return None, final_reason

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, Any]]:
        """
        Parses the JSON response from the AI and validates its structure.
        """
        try:
            clean_text = text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:-3].strip()
            elif clean_text.startswith("```"):
                clean_text = clean_text[3:-3].strip()

            data = json.loads(clean_text)

            if not isinstance(data, dict):
                logger.error(f"AI response is not a dictionary. Received type: {type(data)}")
                return None

            # Check for a structured error response from the AI (e.g., content rejected)
            if "erro" in data:
                logger.warning(f"AI returned a rejection error: {data['erro']}")
                return data  # Return the error dict to be handled by the caller

            # Validate the presence of all required keys for a successful rewrite
            required_keys = [
                "titulo_final", "conteudo_final", "meta_description",
                "focus_keyword", "tags"
            ]
            missing_keys = [key for key in required_keys if key not in data]

            if missing_keys:
                logger.error(f"AI response is missing required keys: {', '.join(missing_keys)}")
                logger.debug(f"Received data: {data}")
                return None

            logger.info("Successfully parsed and validated AI response.")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from AI response: {e}")
            logger.debug(f"Received text: {text[:500]}...")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while parsing AI response: {e}")
            logger.debug(f"Received text: {text[:500]}...")
            return None
