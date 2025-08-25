"""
Unit tests for the tags module
"""

import unittest
from app.tags import TagExtractor


class TestTagExtractor(unittest.TestCase):
    """Test cases for the TagExtractor class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.extractor = TagExtractor()
    
    def test_extract_franchise_tags(self):
        """Test extraction of known franchise tags"""
        test_text = "Marvel's Spider-Man and DC's Batman are featured in new movies from Disney and Warner Bros."
        
        tags = self.extractor.extract_franchise_tags(test_text)
        
        expected_tags = {'marvel', 'spider-man', 'dc', 'batman', 'disney', 'warner-bros'}
        self.assertTrue(expected_tags.issubset(tags))
    
    def test_extract_quoted_terms(self):
        """Test extraction of quoted terms"""
        test_text = 'The movie "Avengers: Endgame" and series "Stranger Things" are popular.'
        
        tags = self.extractor.extract_quoted_terms(test_text)
        
        expected_tags = {'avengers-endgame', 'stranger-things'}
        self.assertTrue(expected_tags.issubset(tags))
    
    def test_extract_capitalized_terms(self):
        """Test extraction of capitalized terms"""
        test_text = "Netflix announced that House of Cards will return. Netflix confirmed the news."
        
        tags = self.extractor.extract_capitalized_terms(test_text)
        
        # Netflix should be detected (appears multiple times)
        self.assertIn('netflix', tags)
        # House of Cards should be detected
        self.assertIn('house-of-cards', tags)
    
    def test_extract_from_title(self):
        """Test tag extraction from titles"""
        test_titles = [
            "Marvel's Spider-Man Gets New Trailer",
            "Breaking: Netflix Cancels Popular Series",
            "New Batman Movie: Everything We Know"
        ]
        
        expected_results = [
            ['marvel', 'spider-man'],
            ['netflix'],
            ['batman']
        ]
        
        for title, expected in zip(test_titles, expected_results):
            with self.subTest(title=title):
                tags = self.extractor.extract_from_title(title)
                for expected_tag in expected:
                    self.assertIn(expected_tag, tags)
    
    def test_validate_tags(self):
        """Test tag validation"""
        test_tags = {
            'marvel',           # Valid
            'spider-man',       # Valid
            'a',               # Too short - invalid
            '123',             # Numeric - invalid
            'new',             # Generic - invalid
            'very-long-tag-name-that-should-be-valid',  # Valid
            '',                # Empty - invalid
            'netflix'          # Valid
        }
        
        valid_tags = self.extractor.validate_tags(test_tags)
        
        # Check valid tags are included
        expected_valid = ['marvel', 'spider-man', 'netflix', 'very-long-tag-name-that-should-be-valid']
        for tag in expected_valid:
            self.assertIn(tag, valid_tags)
        
        # Check invalid tags are excluded
        invalid_tags = ['a', '123', 'new', '']
        for tag in invalid_tags:
            self.assertNotIn(tag, valid_tags)
    
    def test_extract_tags_comprehensive(self):
        """Test comprehensive tag extraction"""
        title = "Marvel's Spider-Man: No Way Home Gets New Trailer"
        content = """
        Marvel Studios has released a new trailer for "Spider-Man: No Way Home" 
        starring Tom Holland. The movie will be available on Disney+ and Netflix 
        after its theatrical release. Director Jon Watts confirmed that this 
        Spider-Man movie will feature multiple villains from previous films.
        """
        
        tags = self.extractor.extract_tags(content, title)
        
        # Should extract major franchises and names
        expected_tags = [
            'marvel', 'spider-man', 'disney', 'netflix', 'tom-holland', 'jon-watts'
        ]
        
        for expected_tag in expected_tags:
            self.assertIn(expected_tag, tags, f"Expected tag '{expected_tag}' not found in {tags}")
        
        # Should limit number of tags
        self.assertLessEqual(len(tags), 15)
    
    def test_empty_input(self):
        """Test behavior with empty input"""
        tags = self.extractor.extract_tags("", "")
        self.assertEqual(tags, [])
        
        tags = self.extractor.extract_tags("Some content", "")
        self.assertIsInstance(tags, list)
    
    def test_no_franchises_content(self):
        """Test with content containing no known franchises"""
        content = "This is a generic article about something unrelated to entertainment."
        title = "Generic News Article"
        
        tags = self.extractor.extract_tags(content, title)
        
        # Should still return a list, but likely empty or with generic terms
        self.assertIsInstance(tags, list)
        # Should not contain franchise tags
        franchise_tags = ['marvel', 'dc', 'disney', 'netflix']
        for franchise_tag in franchise_tags:
            self.assertNotIn(franchise_tag, tags)


if __name__ == '__main__':
    unittest.main()
