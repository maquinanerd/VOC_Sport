import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add project root to path to allow imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.taxonomy.intelligence import TaxonomyExtractor, CategoryManager, normalize_slug

# Mock dependencies that are not part of the test subject
mock_wp_client = MagicMock()
mock_cache = MagicMock()

class TestTaxonomyIntelligence(unittest.TestCase):

    def setUp(self):
        """Reset mocks before each test."""
        mock_wp_client.reset_mock()
        mock_cache.reset_mock()

    def test_normalize_slug(self):
        self.assertEqual(normalize_slug("São Paulo"), "sao-paulo")
        self.assertEqual(normalize_slug("Copa do Brasil"), "copa-do-brasil")
        self.assertEqual(normalize_slug("Atlético-MG"), "atletico-mg")

    def test_extract_entities(self):
        extractor = TaxonomyExtractor()
        text = "Vitória do Flamengo sobre o Palmeiras no Brasileirão. O Mengão jogou bem."
        entities = extractor.extract_entities(text)
        
        self.assertIn("flamengo", entities["clubes"])
        self.assertIn("palmeiras", entities["clubes"])
        self.assertIn("brasileirao", entities["competicoes"])
        self.assertGreater(entities["scores"].get("flamengo", 0), 0)

    @patch('app.taxonomy.intelligence.LIGAS', [
        {"nome": "Notícias", "slug": "noticias", "parent": None},
        {"nome": "Brasileirão", "slug": "brasileirao", "parent": "noticias"},
        {"nome": "Série A", "slug": "serie-a", "parent": "brasileirao"},
    ])
    @patch('app.taxonomy.intelligence.CLUBES_SERIE_A', [
        {"nome": "Flamengo", "slug": "flamengo", "parent": "serie-a", "apelidos": ["mengão"]},
        {"nome": "Palmeiras", "slug": "palmeiras", "parent": "serie-a"},
    ])
    def test_assign_categories_brasileirao(self):
        """
        Tests: "Flamengo 3x1 Palmeiras pela 5ª rodada do Brasileirão"
        Expects: [noticias, brasileirao, flamengo, palmeiras] (limited to 3 specific + 1 default)
        """
        # Mock the category creation/lookup process
        def mock_ensure_category(name, slug, parent_id=None):
            cat_map = {
                "noticias": {"id": 1, "name": "Notícias", "slug": "noticias"},
                "brasileirao": {"id": 10, "name": "Brasileirão", "slug": "brasileirao"},
                "serie-a": {"id": 11, "name": "Série A", "slug": "serie-a"},
                "flamengo": {"id": 101, "name": "Flamengo", "slug": "flamengo"},
                "palmeiras": {"id": 102, "name": "Palmeiras", "slug": "palmeiras"},
            }
            mock_cache.get_category.return_value = None # Force lookup
            return cat_map.get(slug)

        manager = CategoryManager(mock_wp_client, mock_cache)
        manager.ensure_category = MagicMock(side_effect=mock_ensure_category)

        title = "Flamengo 3x1 Palmeiras pela 5ª rodada do Brasileirão"
        content = "Grande jogo do Mengão."
        
        category_ids = manager.assign_categories(title, content)

        # Expected IDs: 1 (Notícias), 10 (Brasileirão), 101 (Flamengo), 102 (Palmeiras)
        # The order is not guaranteed, so we check the set.
        self.assertSetEqual(set(category_ids), {1, 10, 101, 102})
        self.assertEqual(len(category_ids), 4) # 1 default + 3 specific

    def test_assign_categories_fallback(self):
        """Tests fallback when no high-confidence entities are found."""
        
        def mock_ensure_category(name, slug, parent_id=None):
            if slug == "noticias":
                return {"id": 1, "name": "Notícias", "slug": "noticias"}
            return None
        
        manager = CategoryManager(mock_wp_client, mock_cache)
        manager.ensure_category = MagicMock(side_effect=mock_ensure_category)

        title = "Uma notícia genérica sobre esportes"
        content = "Texto sem palavras-chave de clubes ou ligas."
        
        category_ids = manager.assign_categories(title, content)

        # Should only contain the default category ID
        self.assertListEqual(category_ids, [1])


if __name__ == '__main__':
    unittest.main()