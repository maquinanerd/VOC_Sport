import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import Counter

from slugify import slugify

from ..wordpress import WordPressClient
from ..store import TaxonomyCache

logger = logging.getLogger(__name__)

# --- Constants ---
DATA_PATH = Path(__file__).resolve().parent.parent / "data"
MAX_SPECIFIC_CATEGORIES = 3
MIN_SCORE = 0.6
DEFAULT_PARENT_CATEGORY_NAME = "Notícias"

# --- Data Loading ---

def _load_json_data(filename: str) -> List[Dict[str, Any]]:
    """Loads data from a JSON file in the data directory."""
    try:
        with open(DATA_PATH / filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load taxonomy data from {filename}: {e}")
        return []

CLUBES_SERIE_A = _load_json_data("clubes_serie_a.json")
LIGAS = _load_json_data("ligas.json")
FASES = _load_json_data("fases.json")

# --- Normalization and Slugification ---

def normalize_slug(name: str) -> str:
    """Generates a clean, URL-friendly slug from a string."""
    return slugify(name, to_lower=True, separator='-')

# --- Entity Extraction ---

class TaxonomyExtractor:
    def __init__(self):
        self._club_map = self._build_keyword_map(CLUBES_SERIE_A, include_name=True)
        self._liga_map = self._build_keyword_map(LIGAS)
        self._fase_map = self._build_keyword_map(FASES)
        self._assunto_map = self._build_assunto_map()

    def _build_keyword_map(self, items: List[Dict[str, Any]], include_name: bool = False) -> Dict[str, Dict[str, Any]]:
        """Builds a generic map from keywords to item data."""
        keyword_map = {}
        for item in items:
            keywords = item.get('keywords', [])
            if include_name:
                keywords.append(item['nome'])
                keywords.extend(item.get('apelidos', []))

            for keyword in keywords:
                keyword_map[keyword.lower()] = item
        return keyword_map

    def _build_assunto_map(self) -> Dict[str, Dict[str, Any]]:
        """Builds a map for general topics like 'mercado-da-bola'."""
        assunto_map = {}
        assuntos = [liga for liga in LIGAS if liga['slug'] in ['mercado-da-bola', 'selecao-brasileira']]
        for assunto in assuntos:
            for keyword in assunto.get('keywords', []):
                assunto_map[keyword.lower()] = assunto
        return assunto_map

    def extract_entities(self, text: str) -> Dict[str, Any]:
        """
        Extracts entities (clubs, competitions, etc.) from text using keyword matching.
        Returns a dictionary with lists of found entities and their scores.
        """
        text_lower = text.lower()
        
        # A simple presence check is used for scoring. More advanced methods could use frequency or context.
        clubes = {self._club_map[k]['slug'] for k in self._club_map if k in text_lower}
        competicoes = {self._liga_map[k]['slug'] for k in self._liga_map if k in text_lower}
        fases = {self._fase_map[k]['slug'] for k in self._fase_map if k in text_lower}
        assuntos = {self._assunto_map[k]['slug'] for k in self._assunto_map if k in text_lower}

        scores = {entity: 1.0 for entity in (clubes | competicoes | fases | assuntos)}

        return {
            "clubes": list(clubes),
            "competicoes": list(competicoes - assuntos),
            "fases": list(fases),
            "assuntos": list(assuntos),
            "scores": scores
        }

# --- Category Management ---

class CategoryManager:
    def __init__(self, wp_client: WordPressClient, cache: TaxonomyCache):
        self.wp_client = wp_client
        self.cache = cache
        self.extractor = TaxonomyExtractor()
        self.all_taxonomy_data = LIGAS + CLUBES_SERIE_A + FASES

    def ensure_category(self, name: str, slug: str, parent_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Ensures a category exists in WordPress, creating it if necessary."""
        cached = self.cache.get_category(slug)
        if cached:
            logger.debug(f"Found category '{slug}' in cache.")
            return cached

        existing_by_slug = self.wp_client.get_category_by_slug(slug)
        if existing_by_slug:
            logger.info(f"Found existing category '{name}' (slug: {slug}) on WordPress.")
            self.cache.set_category(slug, existing_by_slug)
            return existing_by_slug

        logger.info(f"Category '{name}' (slug: {slug}) not found. Creating with parent ID {parent_id}...")
        created_category = self.wp_client.create_category(name, slug, parent_id)
        if created_category:
            self.cache.set_category(slug, created_category)
            return created_category
        
        logger.error(f"Failed to create category '{name}'.")
        return None

    def _get_or_create_parent_hierarchy(self, entity_slug: str) -> Optional[int]:
        """Recursively ensures parent categories exist and returns the direct parent ID for an entity."""
        entity_info = next((item for item in self.all_taxonomy_data if item['slug'] == entity_slug), None)
        if not entity_info or not entity_info.get('parent'):
            return None # No parent defined or entity not found

        parent_slug = entity_info['parent']
        grandparent_id = self._get_or_create_parent_hierarchy(parent_slug)

        parent_entity_info = next((item for item in self.all_taxonomy_data if item['slug'] == parent_slug), None)
        if not parent_entity_info:
            return grandparent_id

        parent_category_info = self.ensure_category(
            parent_entity_info['nome'],
            parent_entity_info['slug'],
            grandparent_id
        )
        return parent_category_info['id'] if parent_category_info else None

    def assign_categories(self, title: str, content: str) -> List[int]:
        """
        Extracts entities, resolves hierarchy, creates categories, and returns a list of category IDs.
        """
        text_to_analyze = f"{title} {content}"
        entities = self.extractor.extract_entities(text_to_analyze)
        
        default_parent_slug = normalize_slug(DEFAULT_PARENT_CATEGORY_NAME)
        default_parent_cat = self.ensure_category(DEFAULT_PARENT_CATEGORY_NAME, default_parent_slug)
        
        if not default_parent_cat or 'id' not in default_parent_cat:
            logger.critical("Could not find or create the default parent category 'Notícias'. Aborting.")
            return []
        
        final_category_ids = {default_parent_cat['id']}
        
        valid_entities = {slug for slug, score in entities['scores'].items() if score >= MIN_SCORE}
        if not valid_entities:
            logger.warning(f"Taxonomy fallback: No entities found with score >= {MIN_SCORE}. Assigning only to '{DEFAULT_PARENT_CATEGORY_NAME}'.")
            return list(final_category_ids)

        prioritized_slugs = []
        for cat_type in ['competicoes', 'clubes', 'fases', 'assuntos']:
            for slug in entities[cat_type]:
                if slug in valid_entities and slug not in prioritized_slugs:
                    prioritized_slugs.append(slug)

        for slug in prioritized_slugs:
            if len(final_category_ids) >= MAX_SPECIFIC_CATEGORIES + 1:
                break

            entity_info = next((item for item in self.all_taxonomy_data if item['slug'] == slug), None)
            if not entity_info:
                continue

            parent_id = self._get_or_create_parent_hierarchy(slug)
            
            category = self.ensure_category(entity_info['nome'], slug, parent_id)
            if category and 'id' in category:
                final_category_ids.add(category['id'])
        
        logger.info(f"Assigned category IDs: {list(final_category_ids)}")
        return list(final_category_ids)

def reclassify_existing_posts(wp_client: WordPressClient, limit: int = 200, update: bool = False):
    """
    Fetches existing posts and suggests or applies new categories.
    This is a stub for a potential future feature.
    """
    logger.info(f"Starting reclassification analysis for last {limit} posts (dry run)...")
    # A full implementation would:
    # 1. Instantiate CategoryManager.
    # 2. Fetch posts from WordPress via wp_client.
    # 3. For each post, call assign_categories(post.title, post.content).
    # 4. Compare new IDs with existing IDs and log differences.
    # 5. If update=True, call wp_client.update_post_categories(post.id, new_ids).
    logger.info("Reclassification analysis complete.")
