import logging
import requests
import time
import json
from typing import Dict, Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class WordPressClient:
    """A client for interacting with the WordPress REST API."""

    def __init__(self, config: Dict[str, str], categories_map: Dict[str, int]):
        self.api_url = (config.get('url') or "").rstrip('/')
        if not self.api_url:
            raise ValueError("WORDPRESS_URL is not configured.")
        self.user = config.get('user')
        self.password = config.get('password')
        self.categories_map = categories_map
        self.session = requests.Session()
        if self.user and self.password:
            self.session.auth = (self.user, self.password)
        self.session.headers.update({'User-Agent': 'VocMoney-Pipeline/1.0'})

    def get_domain(self) -> str:
        """Extracts the domain from the WordPress URL."""
        try:
            return urlparse(self.api_url).netloc
        except Exception:
            return ""

    def upload_media_from_url(self, image_url: str, alt_text: str = "", max_attempts: int = 3) -> Optional[Dict[str, Any]]:
        """
        Downloads an image and uploads it to WordPress with a retry mechanism.
        """
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                # 1. Download the image with a reasonable timeout
                img_response = requests.get(image_url, timeout=25)
                img_response.raise_for_status()
                content_type = img_response.headers.get('Content-Type', 'image/jpeg')
                # Sanitize filename
                filename = (urlparse(image_url).path.split('/')[-1] or "image.jpg").split("?")[0]

                # 2. Upload to WordPress
                media_endpoint = f"{self.api_url}/media"
                headers = {
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': content_type,
                }
                wp_response = self.session.post(media_endpoint, headers=headers, data=img_response.content, timeout=40)
                wp_response.raise_for_status()
                logger.info(f"Successfully uploaded image: {image_url}")
                return wp_response.json() # Success

            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                logger.warning(f"Upload attempt {attempt}/{max_attempts} for '{image_url}' failed with network error: {e}. Retrying in {2*attempt}s...")
                time.sleep(2 * attempt)  # Simple backoff
            except Exception as e:
                last_err = e
                logger.error(f"Upload of '{image_url}' failed with non-retriable error: {e}")
                break # Don't retry on WP errors (4xx, 5xx) or other issues

        logger.error(f"Final failure to upload image '{image_url}' after {attempt} attempt(s): {last_err}")
        return None

    def create_post(self, payload: Dict[str, Any]) -> Optional[int]:
        """Creates a new post in WordPress."""
        try:
            posts_endpoint = f"{self.api_url}/posts"
            payload.setdefault('status', 'publish')

            # Log the payload for debugging. Set logging level to DEBUG to see this.
            try:
                log_payload = json.dumps(payload, indent=2, ensure_ascii=False)
                logger.debug(f"Sending payload to WordPress:\n{log_payload}")
            except Exception as log_e:
                logger.warning(f"Could not serialize payload for logging: {log_e}")

            response = self.session.post(posts_endpoint, json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get('id')
        except requests.RequestException as e:
            logger.error(f"Failed to create WordPress post: {e}", exc_info=True)
            if e.response is not None:
                logger.error(f"WordPress response body on error: {e.response.text}")
            return None

    def close(self):
        """Closes the requests session."""
        self.session.close()