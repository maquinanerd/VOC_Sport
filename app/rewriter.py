import logging
import re
from typing import Dict, List, Any
from bs4 import BeautifulSoup
from slugify import slugify

logger = logging.getLogger(__name__)


class ContentRewriter:
    """Rewrites and validates AI-generated content for WordPress."""

    def _parse_ai_response(self, raw_text: str) -> Dict[str, str]:
        """Parses the raw text from the AI into a structured dictionary."""
        response = {'title': '', 'excerpt': '', 'content': ''}
        try:
            title_match = re.search(r"Novo Título:\s*(.*?)\s*Novo Resumo:", raw_text, re.DOTALL)
            if title_match:
                response['title'] = title_match.group(1).strip()

            excerpt_match = re.search(r"Novo Resumo:\s*(.*?)\s*Novo Conteúdo:", raw_text, re.DOTALL)
            if excerpt_match:
                response['excerpt'] = excerpt_match.group(1).strip()

            content_match = re.search(r"Novo Conteúdo:\s*(.*)", raw_text, re.DOTALL)
            if content_match:
                response['content'] = content_match.group(1).strip()

            if not all(response.values()):
                logger.warning("AI response parsing was incomplete. Check AI output format.")

            return response
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}", exc_info=True)
            return response

    def _sanitize_html(self, html_content: str, domain: str, tags: List[str]) -> str:
        """
        Cleans and validates the HTML content.
        - Ensures all text is wrapped in <p> tags.
        - Validates allowed tags and attributes.
        - Inserts internal links.
        """
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, 'html.parser')

        # Sanitize tags and attributes
        allowed_tags = {'p', 'b', 'a', 'strong', 'em', 'i'}
        allowed_attrs = {'a': ['href', 'title', 'target', 'rel']}

        for tag in soup.find_all(True):
            if tag.name not in allowed_tags:
                tag.unwrap()
                continue

            attrs = dict(tag.attrs)
            for attr, _ in attrs.items():
                if attr not in allowed_attrs.get(tag.name, []):
                    del tag[attr]

        # Insert internal links
        self._insert_internal_links(soup, domain, tags)

        return str(soup)

    def _insert_internal_links(self, soup: BeautifulSoup, domain: str, tags: List[str]):
        """Finds keywords from tags and replaces them with internal links."""
        if not domain or not tags:
            return

        # Create a regex pattern to find any of the tags as whole words
        # Sort by length to match longer tags first (e.g., "Star Wars" before "Star")
        sorted_tags = sorted(tags, key=len, reverse=True)
        tag_pattern = re.compile(r'\b(' + '|'.join(re.escape(tag) for tag in sorted_tags) + r')\b', re.IGNORECASE)

        linked_tags = set()

        for p_tag in soup.find_all('p'):
            for text_node in p_tag.find_all(string=True):
                if text_node.parent.name == 'a':  # Don't link text that is already a link
                    continue

                new_content = tag_pattern.sub(lambda m:
                    f'<a href="{domain}/tag/{slugify(m.group(1))}">{m.group(1)}</a>'
                    if m.group(1).lower() not in linked_tags and (linked_tags.add(m.group(1).lower()) or True)
                    else m.group(1), str(text_node))

                text_node.replace_with(BeautifulSoup(new_content, 'html.parser'))

    def process_content(self, raw_ai_text: str, tags: List[str], domain: str) -> Dict[str, str]:
        """Processes the raw AI text to produce clean, publishable content."""
        logger.info("Processing and validating rewritten content")

        parsed_content = self._parse_ai_response(raw_ai_text)
        parsed_content['content'] = self._sanitize_html(parsed_content['content'], domain, tags)

        logger.info("Content processing completed successfully")
        return parsed_content