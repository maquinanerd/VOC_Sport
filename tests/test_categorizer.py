"""
Unit tests for the categorizer module
"""

import unittest
from app.categorizer import Categorizer


class TestCategorizer(unittest.TestCase):
    """Test cases for the Categorizer class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.categorizer = Categorizer()
        self.test_categories = {
            'Notícias': 20,
            'Filmes': 24,
            'Séries': 21,
            'Games': 73
        }
    
    def test_get_feed_type_movies(self):
        """Test movie feed type detection"""
        test_cases = [
            'screenrant_movies',
            'movieweb_movies',
            'collider_movies',
            'cbr_movies'
        ]
        
        for source_id in test_cases:
            with self.subTest(source_id=source_id):
                feed_type = self.categorizer.get_feed_type(source_id)
                self.assertEqual(feed_type, 'movies')
    
    def test_get_feed_type_series(self):
        """Test TV/series feed type detection"""
        test_cases = [
            'screenrant_tv',
            'collider_tv',
            'cbr_tv'
        ]
        
        for source_id in test_cases:
            with self.subTest(source_id=source_id):
                feed_type = self.categorizer.get_feed_type(source_id)
                self.assertEqual(feed_type, 'series')
    
    def test_get_feed_type_games(self):
        """Test game feed type detection"""
        test_cases = [
            'gamerant_games',
            'thegamer_games'
        ]
        
        for source_id in test_cases:
            with self.subTest(source_id=source_id):
                feed_type = self.categorizer.get_feed_type(source_id)
                self.assertEqual(feed_type, 'games')
    
    def test_get_feed_type_fallback(self):
        """Test fallback behavior for unknown feeds"""
        unknown_feeds = [
            'unknown_feed',
            'random_source',
            'test_feed'
        ]
        
        for source_id in unknown_feeds:
            with self.subTest(source_id=source_id):
                feed_type = self.categorizer.get_feed_type(source_id)
                self.assertEqual(feed_type, 'movies')  # Default fallback
    
    def test_map_category_movies(self):
        """Test category mapping for movie feeds"""
        movie_feeds = ['screenrant_movies', 'movieweb_movies']
        
        for source_id in movie_feeds:
            with self.subTest(source_id=source_id):
                category_id = self.categorizer.map_category(source_id, self.test_categories)
                self.assertEqual(category_id, 24)  # Filmes category
    
    def test_map_category_series(self):
        """Test category mapping for TV/series feeds"""
        tv_feeds = ['screenrant_tv', 'collider_tv']
        
        for source_id in tv_feeds:
            with self.subTest(source_id=source_id):
                category_id = self.categorizer.map_category(source_id, self.test_categories)
                self.assertEqual(category_id, 21)  # Séries category
    
    def test_map_category_games(self):
        """Test category mapping for game feeds"""
        game_feeds = ['gamerant_games', 'thegamer_games']
        
        for source_id in game_feeds:
            with self.subTest(source_id=source_id):
                category_id = self.categorizer.map_category(source_id, self.test_categories)
                self.assertEqual(category_id, 73)  # Games category
    
    def test_map_category_empty_categories(self):
        """Test behavior with empty category dict"""
        category_id = self.categorizer.map_category('screenrant_movies', {})
        self.assertEqual(category_id, 1)  # Fallback to WordPress default
    
    def test_get_category_for_ai(self):
        """Test AI category mapping"""
        test_cases = [
            ('screenrant_movies', 'movies'),
            ('screenrant_tv', 'series'),
            ('gamerant_games', 'games'),
            ('unknown_feed', 'movies')  # Fallback
        ]
        
        for source_id, expected_ai_category in test_cases:
            with self.subTest(source_id=source_id):
                ai_category = self.categorizer.get_category_for_ai(source_id)
                self.assertEqual(ai_category, expected_ai_category)


if __name__ == '__main__':
    unittest.main()
