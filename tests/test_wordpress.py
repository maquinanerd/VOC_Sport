"""
Unit tests for the wordpress module
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import base64
from app.wordpress import WordPressClient


class TestWordPressClient(unittest.TestCase):
    """Test cases for the WordPressClient class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.wp_config = {
            'url': 'https://example.com/wp-json/wp/v2',
            'user': 'testuser',
            'password': 'testpass'
        }
        self.wp_categories = {
            'Notícias': 20,
            'Filmes': 24,
            'Séries': 21,
            'Games': 73
        }
        self.client = WordPressClient(self.wp_config, self.wp_categories)
    
    def test_init_with_auth(self):
        """Test client initialization with authentication"""
        # Check that authorization header is set
        auth_header = self.client.session.headers.get('Authorization')
        self.assertIsNotNone(auth_header)
        self.assertTrue(auth_header.startswith('Basic '))
        
        # Verify base64 encoding
        auth_string = f"{self.wp_config['user']}:{self.wp_config['password']}"
        expected_auth = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
        self.assertEqual(auth_header, f'Basic {expected_auth}')
    
    def test_init_without_auth(self):
        """Test client initialization without authentication"""
        config_no_auth = {'url': 'https://example.com/wp-json/wp/v2'}
        client = WordPressClient(config_no_auth, self.wp_categories)
        
        auth_header = client.session.headers.get('Authorization')
        self.assertIsNone(auth_header)
    
    def test_base_url_normalization(self):
        """Test base URL normalization"""
        test_cases = [
            ('https://example.com', 'https://example.com/wp-json/wp/v2'),
            ('https://example.com/', 'https://example.com/wp-json/wp/v2'),
            ('https://example.com/wp-json/wp/v2', 'https://example.com/wp-json/wp/v2'),
            ('https://example.com/wp-json/wp/v2/', 'https://example.com/wp-json/wp/v2'),
        ]
        
        for input_url, expected_url in test_cases:
            with self.subTest(input_url=input_url):
                config = {'url': input_url, 'user': 'test', 'password': 'test'}
                client = WordPressClient(config, self.wp_categories)
                self.assertEqual(client.base_url, expected_url)
    
    def test_get_domain(self):
        """Test domain extraction"""
        domain = self.client.get_domain()
        self.assertEqual(domain, 'https://example.com')
    
    @patch('requests.Session.get')
    def test_test_connection_success(self, mock_get):
        """Test successful connection test"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        result = self.client.test_connection()
        self.assertTrue(result)
        
        # Verify the correct endpoint was called
        mock_get.assert_called_once_with(
            f"{self.client.base_url}/posts",
            params={'per_page': 1}
        )
    
    @patch('requests.Session.get')
    def test_test_connection_failure(self, mock_get):
        """Test failed connection test"""
        mock_get.side_effect = Exception("Connection failed")
        
        result = self.client.test_connection()
        self.assertFalse(result)
    
    @patch('requests.Session.get')
    @patch('requests.Session.post')
    def test_get_or_create_tag_existing(self, mock_post, mock_get):
        """Test getting an existing tag"""
        # Mock existing tag response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{'id': 123, 'name': 'Test Tag', 'slug': 'test-tag'}]
        mock_get.return_value = mock_response
        
        tag_id = self.client.get_or_create_tag('Test Tag', 'test-tag')
        
        self.assertEqual(tag_id, 123)
        mock_get.assert_called_once_with(
            f"{self.client.base_url}/tags",
            params={'slug': 'test-tag', 'per_page': 1}
        )
        mock_post.assert_not_called()
    
    @patch('requests.Session.get')
    @patch('requests.Session.post')
    def test_get_or_create_tag_new(self, mock_post, mock_get):
        """Test creating a new tag"""
        # Mock no existing tag
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = []
        mock_get.return_value = mock_get_response
        
        # Mock successful tag creation
        mock_post_response = Mock()
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {'id': 124, 'name': 'New Tag', 'slug': 'new-tag'}
        mock_post.return_value = mock_post_response
        
        tag_id = self.client.get_or_create_tag('New Tag', 'new-tag')
        
        self.assertEqual(tag_id, 124)
        mock_post.assert_called_once_with(
            f"{self.client.base_url}/tags",
            json={'name': 'New Tag', 'slug': 'new-tag'}
        )
    
    @patch('requests.Session.get')
    @patch('requests.Session.post')
    def test_get_or_create_tag_creation_failure(self, mock_post, mock_get):
        """Test tag creation failure"""
        # Mock no existing tag
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = []
        mock_get.return_value = mock_get_response
        
        # Mock failed tag creation
        mock_post_response = Mock()
        mock_post_response.status_code = 400
        mock_post.return_value = mock_post_response
        
        tag_id = self.client.get_or_create_tag('New Tag', 'new-tag')
        
        self.assertIsNone(tag_id)
    
    @patch('requests.post')
    def test_upload_media_success(self, mock_post):
        """Test successful media upload"""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'id': 456, 'source_url': 'https://example.com/image.jpg'}
        mock_post.return_value = mock_response
        
        file_data = b'fake image data'
        filename = 'test.jpg'
        
        media_id = self.client.upload_media(file_data, filename)
        
        self.assertEqual(media_id, 456)
        
        # Verify the request was made correctly
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], f"{self.client.base_url}/media")
        self.assertEqual(kwargs['data'], file_data)
        self.assertIn('Content-Type', kwargs['headers'])
        self.assertIn('Content-Disposition', kwargs['headers'])
    
    @patch('requests.post')
    def test_upload_media_failure(self, mock_post):
        """Test failed media upload"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = 'Upload failed'
        mock_post.return_value = mock_response
        
        file_data = b'fake image data'
        filename = 'test.jpg'
        
        media_id = self.client.upload_media(file_data, filename)
        
        self.assertIsNone(media_id)
    
    @patch.object(WordPressClient, 'get_or_create_tag')
    @patch('requests.Session.post')
    def test_create_post_success(self, mock_post, mock_get_tag):
        """Test successful post creation"""
        # Mock tag creation
        mock_get_tag.side_effect = [101, 102]  # Return different IDs for different tags
        
        # Mock successful post creation
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'id': 789, 'status': 'publish'}
        mock_post.return_value = mock_response
        
        post_data = {
            'title': 'Test Post',
            'content': '<p>Test content</p>',
            'excerpt': 'Test excerpt',
            'status': 'publish',
            'categories': [24],
            'tags': ['test-tag', 'another-tag'],
            'featured_media': 456
        }
        
        post_id = self.client.create_post(post_data)
        
        self.assertEqual(post_id, 789)
        
        # Verify the post data sent
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], f"{self.client.base_url}/posts")
        
        sent_data = kwargs['json']
        self.assertEqual(sent_data['title'], 'Test Post')
        self.assertEqual(sent_data['content'], '<p>Test content</p>')
        self.assertEqual(sent_data['excerpt'], 'Test excerpt')
        self.assertEqual(sent_data['status'], 'publish')
        self.assertEqual(sent_data['categories'], [24])
        self.assertEqual(sent_data['tags'], [101, 102])
        self.assertEqual(sent_data['featured_media'], 456)
    
    @patch.object(WordPressClient, 'get_or_create_tag')
    @patch('requests.Session.post')
    def test_create_post_with_meta_retry(self, mock_post, mock_get_tag):
        """Test post creation with meta data retry on failure"""
        # Mock tag creation
        mock_get_tag.return_value = 101
        
        # Mock first call fails, second succeeds
        mock_response_fail = Mock()
        mock_response_fail.status_code = 400
        mock_response_fail.text = 'Meta data not supported'
        
        mock_response_success = Mock()
        mock_response_success.status_code = 201
        mock_response_success.json.return_value = {'id': 790, 'status': 'publish'}
        
        mock_post.side_effect = [mock_response_fail, mock_response_success]
        
        post_data = {
            'title': 'Test Post',
            'content': '<p>Test content</p>',
            'excerpt': 'Test excerpt',
            'tags': ['test-tag']
        }
        
        post_id = self.client.create_post(post_data)
        
        self.assertEqual(post_id, 790)
        self.assertEqual(mock_post.call_count, 2)
        
        # Second call should not have meta data
        second_call_data = mock_post.call_args_list[1][1]['json']
        self.assertNotIn('meta', second_call_data)
    
    @patch('requests.Session.post')
    def test_create_post_failure(self, mock_post):
        """Test post creation failure"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = 'Bad request'
        mock_post.return_value = mock_response
        
        post_data = {
            'title': 'Test Post',
            'content': '<p>Test content</p>'
        }
        
        post_id = self.client.create_post(post_data)
        
        self.assertIsNone(post_id)
    
    @patch('requests.Session.post')
    def test_update_post_success(self, mock_post):
        """Test successful post update"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        post_data = {'title': 'Updated Title'}
        result = self.client.update_post(123, post_data)
        
        self.assertTrue(result)
        mock_post.assert_called_once_with(
            f"{self.client.base_url}/posts/123",
            json=post_data
        )
    
    @patch('requests.Session.post')
    def test_update_post_failure(self, mock_post):
        """Test post update failure"""
        mock_post.side_effect = Exception("Update failed")
        
        post_data = {'title': 'Updated Title'}
        result = self.client.update_post(123, post_data)
        
        self.assertFalse(result)
    
    @patch('requests.Session.delete')
    def test_delete_post_success(self, mock_delete):
        """Test successful post deletion"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_delete.return_value = mock_response
        
        result = self.client.delete_post(123)
        
        self.assertTrue(result)
        mock_delete.assert_called_once_with(f"{self.client.base_url}/posts/123")
    
    @patch('requests.Session.delete')
    def test_delete_post_failure(self, mock_delete):
        """Test post deletion failure"""
        mock_delete.side_effect = Exception("Delete failed")
        
        result = self.client.delete_post(123)
        
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
