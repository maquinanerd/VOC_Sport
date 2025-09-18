import logging
import requests
import time
import json 
import re 
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def _slugify(name: str) -> str:
    """Creates a simple, WordPress-compatible slug from a string."""
    s = name.strip().lower()
    # Remove characters that are not alphanumeric, whitespace, or hyphen
    s = re.sub(r'[^\w\s-]', '', s, flags=re.UNICODE)
    # Replace whitespace and underscores with a hyphen
    s = re.sub(r'[\s_-]+', '-', s, flags=re.UNICODE)
    # Strip leading/trailing hyphens and limit length
    return s.strip('-')[:190] or 'tag'

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

    def _get_existing_tag_id(self, name: str) -> Optional[int]:
        """Searches for an existing tag by name or slug and returns its ID."""
        slug = _slugify(name)
        tags_endpoint = f"{self.api_url}/tags"
        params = {"search": name, "per_page": 100}

        try:
            r = self.session.get(tags_endpoint, params=params, timeout=20)
            r.raise_for_status()
            items = r.json()
            
            # WordPress search can be broad, so we verify the match
            for item in items:
                if item.get('name', '').strip().lower() == name.strip().lower():
                    return int(item['id'])
            for item in items:
                if item.get('slug') == slug:
                    return int(item['id'])
        except requests.RequestException as e:
            logger.error(f"Error searching for tag '{name}': {e}")
        
        return None

    def _create_tag(self, name: str) -> Optional[int]:
        """Creates a new tag and returns its ID."""
        tags_endpoint = f"{self.api_url}/tags"
        payload = {"name": name, "slug": _slugify(name)}
        
        try:
            r = self.session.post(tags_endpoint, json=payload, timeout=20)
            
            if r.status_code in (200, 201):
                tag_id = int(r.json()['id'])
                logger.info(f"Created new tag '{name}' with ID {tag_id}.")
                return tag_id
            
            # Handle race condition where tag was created between search and post
            if r.status_code == 400 and isinstance(r.json(), dict) and r.json().get("code") == "term_exists":
                logger.warning(f"Tag '{name}' already exists (race condition). Re-fetching ID.")
                return self._get_existing_tag_id(name)
            
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error creating tag '{name}': {e}")
            if e.response is not None:
                logger.error(f"Response body: {e.response.text}")

        return None

    def _ensure_tag_ids(self, tags: List[Any], max_tags: int = 10) -> List[int]:
        """Converts a list of tag names/IDs into a list of integer IDs, creating tags if necessary."""
        if not tags:
            return []

        # Normalize input (handles strings, ints, and comma-separated strings)
        norm_tags: List[str] = []
        for t in tags:
            if isinstance(t, int):
                norm_tags.append(str(t))
            elif isinstance(t, str):
                norm_tags.extend([p.strip() for p in t.split(',') if p.strip()])
        
        # Deduplicate and limit
        cleaned_tags = list(dict.fromkeys(norm_tags))[:max_tags]
        
        tag_ids: List[int] = []
        for tag_name in cleaned_tags:
            if tag_name.isdigit():
                tag_ids.append(int(tag_name))
            elif len(tag_name) >= 2:
                tag_id = self._get_existing_tag_id(tag_name) or self._create_tag(tag_name)
                if tag_id:
                    tag_ids.append(tag_id)
        
        logger.info(f"Resolved tags {tags} to IDs: {tag_ids}")
        return tag_ids

    def resolve_tags_by_name(self, tag_names: List[str], create_if_missing: bool = False) -> List[int]:
        """Converts a list of tag names into a list of integer IDs, optionally creating them."""
        if not tag_names:
            return []

        # Deduplicate and limit
        cleaned_tags = list(dict.fromkeys(tag_names))[:10]
        
        tag_ids: List[int] = []
        for tag_name in cleaned_tags:
            if len(tag_name) >= 2:
                tag_id = self._get_existing_tag_id(tag_name)
                if tag_id:
                    tag_ids.append(tag_id)
                elif create_if_missing:
                    if new_id := self._create_tag(tag_name):
                        tag_ids.append(new_id)
        return tag_ids

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

    def set_media_alt_text(self, media_id: int, alt_text: str) -> bool:
        """Sets the alt text for a media item in WordPress."""
        if not alt_text:
            return False
        try:
            endpoint = f"{self.api_url}/media/{media_id}"
            payload = {"alt_text": alt_text}
            r = self.session.post(endpoint, json=payload, timeout=20)
            r.raise_for_status()
            logger.info(f"Successfully set alt text for media ID {media_id}.")
            return True
        except requests.RequestException as e:
            logger.warning(f"Failed to set alt_text on media {media_id}: {e}")
            if e.response is not None:
                logger.warning(f"Response body: {e.response.text}")
            return False

    def find_related_posts(self, term: str, limit: int = 3) -> List[Dict[str, str]]:
        """Searches for posts on the site and returns their title and URL."""
        if not term:
            return []
        try:
            endpoint = f"{self.api_url}/search"
            params = {"search": term, "per_page": limit, "_embed": "self"}
            resp = self.session.get(endpoint, params=params, timeout=15)
            resp.raise_for_status()
            # The 'url' in the search result is the API URL, we need the 'link' from the embedded post object
            return [{"title": i.get("title", ""), "url": i.get("_embedded", {}).get("self", [{}])[0].get("link", "")} for i in resp.json()]
        except requests.RequestException as e:
            logger.error(f"Error searching for related posts with term '{term}': {e}")
            return []

    def create_post(self, payload: Dict[str, Any]) -> Optional[int]:
        """Creates a new post in WordPress."""
        try:
            # Resolve tag names to integer IDs before sending
            if 'tags' in payload and payload['tags']:
                payload['tags'] = self._ensure_tag_ids(payload['tags'])

            posts_endpoint = f"{self.api_url}/posts"
            payload.setdefault('status', 'publish')

            # Log a summary of the payload to avoid overly long logs
            try:
                logger.info(
                    "WP payload: title_len=%d content_len=%d cat=%s tags=%s",
                    len(payload.get('title', '')),
                    len(payload.get('content', '')),
                    payload.get('categories'),
                    payload.get('tags')
                )
                if logger.isEnabledFor(logging.DEBUG):
                    log_payload = json.dumps(payload, indent=2, ensure_ascii=False)
                    logger.debug(f"Sending full payload to WordPress:\n{log_payload}")
            except Exception as log_e:
                logger.warning(f"Could not serialize payload for logging: {log_e}")

            response = self.session.post(posts_endpoint, json=payload, timeout=60)
            
            if not response.ok:
                logger.error(f"WordPress post creation failed with status {response.status_code}: {response.text}")
                response.raise_for_status()

            return response.json().get('id')
        except requests.RequestException as e:
            logger.error(f"Failed to create WordPress post: {e}", exc_info=False)
            return None

    def get_category_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Searches for an existing category by slug and returns its data."""
        endpoint = f"{self.api_url}/categories"
        params = {"slug": slug, "per_page": 1}
        try:
            r = self.session.get(endpoint, params=params, timeout=20)
            r.raise_for_status()
            items = r.json()
            if items and isinstance(items, list):
                # Ensure we have an exact slug match
                for item in items:
                    if item.get('slug') == slug:
                        logger.debug(f"Found category by slug '{slug}' with ID {item['id']}.")
                        return {
                            'id': item['id'],
                            'name': item['name'],
                            'slug': item['slug'],
                            'parent': item.get('parent', 0)
                        }
        except requests.RequestException as e:
            logger.error(f"Error searching for category with slug '{slug}': {e}")
        return None

    def create_category(self, name: str, slug: str, parent_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Creates a new category and returns its data."""
        endpoint = f"{self.api_url}/categories"
        payload = {"name": name, "slug": slug}

        parent_id: Optional[int] = None
        if parent_slug:
            parent_cat = self.get_category_by_slug(parent_slug)
            parent_id = parent_cat['id'] if parent_cat else None
        if parent_id:
            payload['parent'] = parent_id
        
        try:
            r = self.session.post(endpoint, json=payload, timeout=20)
            
            if r.status_code in (200, 201):
                data = r.json()
                logger.info(f"Created new category '{name}' (slug: {slug}) with ID {data['id']}.")
                return {
                    'id': data['id'],
                    'name': data['name'],
                    'slug': data['slug'],
                    'parent': data.get('parent', 0)
                }
            
            if r.status_code == 400 and isinstance(r.json(), dict) and r.json().get("code") == "term_exists":
                logger.warning(f"Category '{name}' already exists (race condition). Re-fetching by slug.")
                return self.get_category_by_slug(slug)
            
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error creating category '{name}': {e}")
            if e.response is not None:
                logger.error(f"Response body: {e.response.text}")
        return None

    def resolve_categories_by_slugs(self, slugs: List[str]) -> List[int]:
        """Resolves a list of category slugs to their corresponding integer IDs."""
        if not slugs:
            return []
        ids = []
        for slug in slugs:
            cat = self.get_category_by_slug(slug)
            if cat and cat.get('id'):
                ids.append(cat['id'])
        return ids

    def update_yoast_meta(self, post_id: int, focus_kw: str, related_kws: List[str], meta_desc: str):
        """
        Updates the Yoast SEO metadata for a given post.
        Note: This requires the meta keys to be exposed in the WP REST API.
        """
        if not post_id:
            return

        payload = {
            "meta": {
                "_yoast_wpseo_focuskw": focus_kw,
                # Yoast stores related keyphrases as a JSON string of objects
                "_yoast_wpseo_keyphrases": json.dumps([{"keyword": kw} for kw in related_kws]) if related_kws else "",
                "_yoast_wpseo_metadesc": meta_desc
            }
        }
        endpoint = f"{self.api_url}/posts/{post_id}"
        try:
            r = self.session.post(endpoint, json=payload, timeout=20)
            r.raise_for_status()
            logger.info(f"Successfully updated Yoast meta for post {post_id}.")
        except requests.RequestException as e:
            logger.warning(f"Could not update Yoast meta via REST for post {post_id}: {e.response.text if e.response else e}")

    def close(self):
        """Closes the requests session."""
        self.session.close()