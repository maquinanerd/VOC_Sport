import unittest
from bs4 import BeautifulSoup, Tag
from app.html_utils import (
    remove_lance_widgets,
    strip_lance_cdn,
    convert_twitter_embeds_to_oembed,
    normalize_images_with_captions,
)

class TestLanceHtmlUtils(unittest.TestCase):

    def test_remove_lance_widgets_robustness(self):
        """
        Tests the robustness of remove_lance_widgets against the
        'NavigableString' object has no attribute 'parent' error.
        This happens when a node is decomposed while iterating.
        """
        html = """
        <div>
            <div class="widget-to-remove">
                <h3>Relacionadas</h3>
                <a href="#">Link 1</a>
                <a href="#">Link 2</a>
                <a href="#">Link 3</a>
                <!-- This text node could be detached if the parent is removed first -->
                <span>Veja também</span>
            </div>
            <p>Main content should remain.</p>
        </div>
        """
        soup = BeautifulSoup(html, 'lxml')
        try:
            # This call should not raise an AttributeError
            remove_lance_widgets(soup)
        except AttributeError as e:
            self.fail(f"remove_lance_widgets raised an unexpected AttributeError: {e}")

        # Assert that the widget was removed
        self.assertIsNone(soup.find('div', class_='widget-to-remove'))
        self.assertIsNotNone(soup.find('p', string='Main content should remain.'))
        self.assertNotIn('Relacionadas', str(soup))
        self.assertNotIn('Veja também', str(soup))

    def test_convert_twitter_embed_from_tag_root(self):
        """
        Tests that convert_twitter_embeds_to_oembed works when passed a Tag,
        not just the top-level BeautifulSoup object, preventing the
        'NoneType' object is not callable error.
        """
        html = """
        <html><body>
            <main>
                <h1>Article Title</h1>
                <p>Some text.</p>
                <blockquote class="twitter-tweet">
                    <p>Loading tweet...</p>
                    <a href="https://twitter.com/someuser/status/1234567890"></a>
                </blockquote>
                <p>More text.</p>
            </main>
        </body></html>
        """
        soup = BeautifulSoup(html, 'lxml')
        # Simulate passing a sub-tree (a Tag object) as it happens in the extractor
        main_tag = soup.find('main')

        try:
            # This call should not raise a TypeError
            convert_twitter_embeds_to_oembed(main_tag)
        except TypeError as e:
            self.fail(f"convert_twitter_embeds_to_oembed raised an unexpected TypeError: {e}")

        # Assert that the blockquote was replaced with a <p> containing the URL
        self.assertIsNone(main_tag.find('blockquote', class_='twitter-tweet'))
        tweet_p = main_tag.find('p', string='https://twitter.com/someuser/status/1234567890')
        self.assertIsNotNone(tweet_p)
        self.assertEqual(tweet_p.get_text(), 'https://twitter.com/someuser/status/1234567890')

    def test_strip_lance_cdn_url(self):
        """Tests the removal of Lance's CDN parameters from image URLs."""
        parametrized_url = "https://lncimg.lance.com.br/cdn-cgi/image/width=870,height=580,quality=75,format=webp/uploads/2024/01/image.jpg"
        expected_url = "https://lncimg.lance.com.br/uploads/2024/01/image.jpg"
        self.assertEqual(strip_lance_cdn(parametrized_url), expected_url)

        # Test with an already clean URL
        clean_url = "https://lncimg.lance.com.br/uploads/2024/01/image.jpg"
        self.assertEqual(strip_lance_cdn(clean_url), clean_url)

        # Test with a non-Lance URL
        other_url = "https://example.com/image.jpg"
        self.assertEqual(strip_lance_cdn(other_url), other_url)

    def test_full_lance_image_normalization(self):
        """
        Tests the end-to-end normalization for Lance, ensuring widgets are removed
        and only valid article images remain.
        """
        html = """
        <div>
            <div class="card-related"><figure><img src="https://lncimg.lance.com.br/cdn-cgi/image/w=300/uploads/2024/09/related-thumb.jpg"><figcaption>Relacionadas</figcaption></figure></div>
            <figure><img src="https://lncimg.lance.com.br/cdn-cgi/image/w=800/uploads/2024/09/main-article-image.jpg" alt="Main image"><figcaption>Legenda da foto principal. (Foto: Lance! Press)</figcaption></figure>
            <img src="https://lncimg.lance.com.br/assets/v1.2/img/logo-lance.svg">
            <aside><h3>Mais notícias</h3><img src="https://lncimg.lance.com.br/uploads/2024/09/another-thumb.jpg"></aside>
        </div>
        """
        source_url = "https://www.lance.com.br/some-article.html"
        result_html = normalize_images_with_captions(html, source_url=source_url)
        soup = BeautifulSoup(result_html, 'lxml')

        self.assertNotIn("related-thumb.jpg", result_html)
        self.assertNotIn("another-thumb.jpg", result_html)
        self.assertNotIn("logo-lance.svg", result_html)

        main_img = soup.find('img')
        self.assertIsNotNone(main_img)
        self.assertEqual(main_img['src'], "https://lncimg.lance.com.br/uploads/2024/09/main-article-image.jpg")
        
        figure = main_img.find_parent('figure')
        self.assertIsNotNone(figure)
        figcaption = figure.find('figcaption')
        self.assertIsNotNone(figcaption)
        self.assertIn("Legenda da foto principal.", figcaption.get_text())