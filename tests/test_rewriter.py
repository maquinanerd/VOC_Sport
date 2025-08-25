"""
Unit tests for the rewriter module
"""

import unittest
from app.rewriter import ContentRewriter


class TestContentRewriter(unittest.TestCase):
    """Test cases for the ContentRewriter class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.rewriter = ContentRewriter()
    
    def test_validate_title(self):
        """Test title validation removes HTML"""
        test_cases = [
            ("Plain title", "Plain title"),
            ("<b>Bold title</b>", "Bold title"),
            ("<a href='#'>Link title</a>", "Link title"),
            ("Title with <span>span</span>", "Title with span"),
            ("", ""),
            ("<script>alert('xss')</script>Clean title", "Clean title")
        ]
        
        for input_title, expected in test_cases:
            with self.subTest(input_title=input_title):
                result = self.rewriter.validate_title(input_title)
                self.assertEqual(result, expected)
    
    def test_validate_excerpt(self):
        """Test excerpt validation"""
        test_cases = [
            ("Plain excerpt", "Plain excerpt"),
            ("<p>HTML excerpt</p>", "HTML excerpt"),
            ("Very " + "long " * 100 + "excerpt", "Very " + "long " * 47 + "long..."),
            ("", "")
        ]
        
        for input_excerpt, expected_start in test_cases:
            with self.subTest(input_excerpt=input_excerpt):
                result = self.rewriter.validate_excerpt(input_excerpt)
                if "..." in expected_start:
                    self.assertTrue(result.endswith("..."))
                    self.assertTrue(len(result) <= 300)
                else:
                    self.assertEqual(result, expected_start)
    
    def test_sanitize_html(self):
        """Test HTML sanitization"""
        test_html = """
        <p>This is a paragraph with <b>bold</b> text.</p>
        <script>alert('xss');</script>
        <div>This div should be unwrapped</div>
        <a href="http://example.com">Valid link</a>
        <img src="image.jpg" alt="Valid image" onclick="alert('xss')">
        <iframe src="https://youtube.com/embed/video">YouTube embed</iframe>
        """
        
        result = self.rewriter.sanitize_html(test_html)
        
        # Should contain allowed tags
        self.assertIn('<p>', result)
        self.assertIn('<b>', result)
        self.assertIn('<a href="http://example.com">', result)
        self.assertIn('<img', result)
        self.assertIn('<iframe', result)
        
        # Should not contain disallowed tags or attributes
        self.assertNotIn('<script>', result)
        self.assertNotIn('<div>', result)
        self.assertNotIn('onclick=', result)
        self.assertNotIn('alert', result)
    
    def test_wrap_paragraphs(self):
        """Test paragraph wrapping"""
        test_cases = [
            ("Plain text", "<p>Plain text</p>"),
            ("Line 1\nLine 2", "<p>Line 1\nLine 2</p>"),
            ("<p>Already wrapped</p>", "<p>Already wrapped</p>"),
        ]
        
        for input_content, expected in test_cases:
            with self.subTest(input_content=input_content):
                result = self.rewriter.wrap_paragraphs(input_content)
                self.assertIn(expected, result)
    
    def test_insert_internal_links(self):
        """Test internal link insertion"""
        content = "<p>This article talks about Spider-Man and Marvel movies.</p>"
        domain = "https://example.com"
        tags = ["spider-man", "marvel"]
        
        result = self.rewriter.insert_internal_links(content, domain, tags)
        
        # Should contain internal links
        self.assertIn('href="https://example.com/tag/spider-man"', result)
        self.assertIn('href="https://example.com/tag/marvel"', result)
    
    def test_should_bold_tag(self):
        """Test bold tag determination"""
        test_cases = [
            ("marvel-movie", True),
            ("netflix-series", True), 
            ("disney-film", True),
            ("random-tag", False),
            ("generic-news", False)
        ]
        
        for tag, expected in test_cases:
            with self.subTest(tag=tag):
                result = self.rewriter._should_bold_tag(tag)
                self.assertEqual(result, expected)
    
    def test_preserve_media(self):
        """Test media preservation in content"""
        content = "<p>Some content</p>"
        images = [
            {"src": "https://example.com/image1.jpg", "alt": "Test image 1"},
            {"src": "https://example.com/image2.jpg", "alt": "Test image 2"}
        ]
        videos = [
            {"src": "https://youtube.com/embed/test", "html": '<iframe src="https://youtube.com/embed/test"></iframe>'}
        ]
        
        result = self.rewriter.preserve_media(content, images, videos)
        
        # Should contain images
        self.assertIn('src="https://example.com/image1.jpg"', result)
        self.assertIn('src="https://example.com/image2.jpg"', result)
        
        # Should contain video
        self.assertIn('src="https://youtube.com/embed/test"', result)
    
    def test_process_content_integration(self):
        """Test complete content processing"""
        ai_content = {
            'title': '<b>Test Title</b>',
            'excerpt': '<p>This is a test excerpt that is quite long.</p>',
            'content': 'This is content about Spider-Man from Marvel.'
        }
        
        images = [{"src": "https://example.com/test.jpg", "alt": "Test"}]
        videos = []
        domain = "https://example.com"
        tags = ["spider-man", "marvel"]
        
        result = self.rewriter.process_content(ai_content, images, videos, domain, tags)
        
        # Title should be plain text
        self.assertEqual(result['title'], 'Test Title')
        
        # Excerpt should be clean
        self.assertEqual(result['excerpt'], 'This is a test excerpt that is quite long.')
        
        # Content should be processed
        self.assertIn('<p>', result['content'])
        self.assertIn('example.com/tag/', result['content'])


if __name__ == '__main__':
    unittest.main()
