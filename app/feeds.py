import feedparser
import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _parse_sitemap(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses a sitemap.xml and returns a list of article-like dicts.
    Based on user suggestion.
    """
    try:
        root = ET.fromstring(xml_bytes)
        ns = {'news': 'http://www.google.com/schemas/sitemap-news/0.9'}
        items = []
        # Use a namespace-agnostic way to find url tags
        for url_element in root.findall('.//{*}url'):
            loc = url_element.findtext('{*}loc')
            if not loc:
                continue

            lastmod = url_element.findtext('{*}lastmod')
            
            # Try to find the title in the <news:news> block
            news_block = url_element.find('{http://www.google.com/schemas/sitemap-news/0.9}news')
            title = None
            if news_block is not None:
                title = news_block.findtext('news:title', ns)

            items.append({
                "link": loc,
                "title": title or loc,
                "published": lastmod,
            })

        # Sort by lastmod date (string comparison is fine for ISO 8601), descending.
        items.sort(key=lambda x: x.get("published") or "", reverse=True)
        
        logger.info(f"Parsed {len(items)} items from sitemap.")
        return items[:50] # Limit to 50 most recent
    except ET.ParseError as e:
        logger.error(f"Failed to parse XML sitemap: {e}")
        return []

class FeedReader:
    def __init__(self, user_agent: str):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})

    def _fetch_content(self, url: str) -> Optional[bytes]:
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            return response.content
        except requests.RequestException as e:
            logger.error(f"Failed to fetch feed/sitemap from {url}: {e}")
            return None

    def read_feeds(self, feed_config: Dict[str, Any], source_id: str) -> List[Dict[str, Any]]:
        all_items = []
        feed_type = feed_config.get('type', 'rss')

        for url in feed_config.get('urls', []):
            logger.info(f"Reading {feed_type} feed from {url} for source '{source_id}'")
            content = self._fetch_content(url)
            if not content:
                continue

            if feed_type == 'sitemap':
                parsed_items = _parse_sitemap(content)
                all_items.extend(parsed_items)
            else: # Default to 'rss'
                feed = feedparser.parse(content)
                if feed.bozo:
                    logger.warning(f"Feed from {url} is not well-formed: {feed.bozo_exception}")
                all_items.extend(feed.entries)
        
        seen_links = set()
        unique_items = [item for item in all_items if item.get('link') and (item['link'] not in seen_links and not seen_links.add(item['link']))]
        logger.info(f"Found {len(unique_items)} total unique items for {source_id}.")
        return unique_items