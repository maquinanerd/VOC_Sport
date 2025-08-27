"""
RSS feed reading and normalization module
"""

import logging
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urljoin

import feedparser
import requests
from dateutil import parser as date_parser
from . import synthetic_rss

logger = logging.getLogger(__name__)


class FeedReader:
    """RSS feed reader with normalization and deduplication"""
    
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})
        
    def normalize_item(self, entry: Any, source_id: str) -> Dict[str, Any]:
        """Normalize a feed entry to a standard format"""
        try:
            # Get unique identifier (prefer GUID, fallback to link)
            item_id = getattr(entry, 'guid', None) or getattr(entry, 'link', '')
            if not item_id:
                # Generate ID from title + source
                title = getattr(entry, 'title', '')
                item_id = hashlib.md5(f"{source_id}:{title}".encode()).hexdigest()
            
            # Parse publication date
            published_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, 'published'):
                try:
                    published_at = date_parser.parse(entry.published)
                except:
                    pass
            
            if not published_at:
                published_at = datetime.now()
            
            # Extract basic information
            title = getattr(entry, 'title', '').strip()
            link = getattr(entry, 'link', '').strip()
            summary = getattr(entry, 'summary', '').strip()
            
            # Clean up summary HTML
            if summary:
                import re
                summary = re.sub(r'<[^>]+>', '', summary)
                summary = summary.replace('&nbsp;', ' ').strip()
            
            return {
                'id': item_id,
                'title': title,
                'link': link,
                'summary': summary,
                'published_at': published_at,
                'source_id': source_id
            }
            
        except Exception as e:
            logger.error(f"Error normalizing feed entry: {str(e)}")
            return {}
    
    def read_single_feed(self, url: str, source_id: str, feed_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Read a single RSS feed and return normalized items"""
        feed_content = None
        try:
            logger.debug(f"Attempting to read feed: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            feed_content = response.content
            logger.info(f"Successfully fetched official RSS feed from {url}")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch RSS feed from {url} ({e}). Checking for synthetic fallback.")
            synthetic_config = feed_config.get('synthetic_from')
            if synthetic_config:
                list_url = synthetic_config.get('list_url')
                logger.info(f"Attempting to generate synthetic feed for {source_id} from {list_url}")
                try:
                    feed_content = synthetic_rss.build_synthetic_feed(
                        list_url=list_url,
                        selectors=synthetic_config.get('selectors'),
                        limit=synthetic_config.get('limit', 12)
                    )
                    logger.info(f"Successfully generated synthetic feed for {source_id}.")
                except Exception as synth_e:
                    logger.error(f"Synthetic feed generation for {source_id} failed: {synth_e}", exc_info=True)
                    return []
            else:
                logger.error(f"Error reading feed {url} and no synthetic fallback is configured.")
                return []

        if not feed_content:
            return []

        feed = feedparser.parse(feed_content)
        if feed.bozo and feed.bozo_exception:
            logger.warning(f"Feed parse warning for {url}: {feed.bozo_exception}")

        items = [self.normalize_item(e, source_id) for e in feed.entries if e.get('title') and e.get('link')]
        logger.info(f"Parsed {len(items)} items from feed content for {source_id}.")
        return items

    def read_feeds(self, feed_config: Dict[str, Any], source_id: str) -> List[Dict[str, Any]]:
        """Read multiple RSS feeds and return combined normalized items"""
        all_items = []
        urls = feed_config.get('urls', [])
        for url in urls:
            items = self.read_single_feed(url, source_id, feed_config)
            all_items.extend(items)
        
        # Deduplicate by link
        seen_links = set()
        unique_items = []
        for item in all_items:
            if item['link'] not in seen_links:
                seen_links.add(item['link'])
                unique_items.append(item)
        
        # Sort by published date (newest first)
        unique_items.sort(key=lambda x: x['published_at'], reverse=True)
        
        logger.info(f"Total unique items for {source_id}: {len(unique_items)}")
        return unique_items
