import feedparser
import logging
import requests
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import gzip
import time
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

NS = {"ns":"http://www.sitemaps.org/schemas/sitemap/0.9",
      "news":"http://www.google.com/schemas/sitemap-news/0.9"}

def _stable_id_from(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def normalize_item(raw: dict) -> dict:
    """
    Aceita item vindo de RSS (feedparser) ou de sitemap e garante chaves padronizadas.
    Preferência de ID:
      1) guid/id do RSS se existir e for não-vazio
      2) link/url/loc
      3) fallback: hash de title+published
    """
    # Possíveis nomes vindos do parser
    guid = raw.get("guid") or raw.get("id")  # feedparser pode pôr 'id'
    link = raw.get("link") or raw.get("url") or raw.get("loc")
    title = raw.get("title") or raw.get("news_title") or ""
    published = raw.get("published") or raw.get("pubDate") or raw.get("lastmod")
    author = raw.get("author") or raw.get("dc_creator") or None
    summary = raw.get("summary") or raw.get("description") or None

    # Normaliza data (deixa string se não souber converter)
    def _parse_dt(dt):
        if not dt or not isinstance(dt, str):
            return dt
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(dt, fmt).isoformat()
            except (ValueError, TypeError):
                continue
        return dt  # mantém como veio

    published_iso = _parse_dt(published)

    # Monta ID estável
    if guid:
        ext_id = str(guid).strip()
    elif link:
        ext_id = _stable_id_from(link)
    else:
        ext_id = _stable_id_from(f"{title}|{published_iso or ''}")

    return {
        "id": ext_id,
        "url": link,
        "title": title.strip() if isinstance(title, str) else title,
        "published": published_iso,
        "author": author,
        "summary": summary,
        "_raw": raw,
    }

class FeedReader:
    def __init__(self, user_agent: str):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})

    def _fetch_content(self, url: str) -> Optional[bytes]:
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            
            content = response.content
            ctype = response.headers.get("Content-Type", "").lower()
            
            # Decompress if it's a gzipped file
            if "gzip" in ctype or url.endswith(".gz"):
                try:
                    content = gzip.decompress(content)
                except (gzip.BadGzipFile, OSError) as e:
                    logger.warning(
                        f"Content from {url} seems to be gzipped but failed to decompress. "
                        f"Proceeding with original content. Error: {e}"
                    )
                except Exception as e:
                    logger.error(f"An unexpected error occurred during gzip decompression for {url}: {e}")
                    return None
            
            return content
        except requests.RequestException as e:
            logger.error(f"Failed to fetch feed/sitemap from {url}: {e}")
            return None

    def _parse_sitemap(
        self,
        xml_bytes: bytes,
        limit: int = 50,
        allow_regex: Optional[str] = None,
        deny_regex: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Parses a sitemap.xml (or sitemapindex.xml) and returns a list of article-like dicts.
        Handles nested sitemap indexes by fetching them.
        """
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML sitemap: {e}")
            return []

        allow = re.compile(allow_regex) if allow_regex else None
        deny  = re.compile(deny_regex)  if deny_regex  else None
        items = []

        # Handle sitemap index by fetching and parsing child sitemaps
        if root.tag.endswith("sitemapindex"):
            logger.info("Detected sitemap index. Fetching child sitemaps.")
            child_sitemap_urls = [
                sm.findtext("ns:loc", NS)
                for sm in root.findall(".//ns:sitemap", NS)
                if sm.findtext("ns:loc", NS)
            ]

            for url in child_sitemap_urls:
                if len(items) >= limit:
                    break
                logger.debug(f"Fetching child sitemap from {url}")
                child_bytes = self._fetch_content(url)
                if child_bytes:
                    # Recursive call to parse the child sitemap, passing regexes
                    items.extend(self._parse_sitemap(
                        child_bytes, limit=limit, allow_regex=allow_regex, deny_regex=deny_regex
                    ))
                    time.sleep(0.2)  # Be polite
            
            # Sort and limit at the very end of processing the index
            items.sort(key=lambda x: x.get("published") or "", reverse=True)
            logger.info(f"Parsed {len(items)} total items from sitemap index.")
            return items[:limit]
        
        # Handle regular sitemap (urlset)
        for url_element in root.findall(".//ns:url", NS):
            loc_el = url_element.find("ns:loc", NS)
            if loc_el is None or not (loc := (loc_el.text or "").strip()):
                continue

            if deny and deny.search(loc):
                continue
            if allow and not allow.search(loc):
                continue

            lastmod = url_element.findtext("ns:lastmod", NS)
            
            title = None
            news_block = url_element.find("news:news", NS)
            if news_block is not None:
                title_element = news_block.find("news:title", NS)
                if title_element is not None and title_element.text:
                    title = title_element.text.strip()

            if not loc:
                continue

            items.append({
                "link": loc,
                "guid": loc,
                "title": title or loc,
                "published": lastmod,
            })

        # For a single sitemap, sort and limit here.
        items.sort(key=lambda x: x.get("published") or "", reverse=True)
        logger.info(f"Parsed {len(items)} items from sitemap.")
        return items[:limit]

    def read_feeds(self, feed_config: Dict[str, Any], source_id: str) -> List[Dict[str, Any]]:
        raw_items = []
        feed_type = feed_config.get('type', 'rss')

        for url in feed_config.get('urls', []):
            logger.info(f"Reading {feed_type} feed from {url} for source '{source_id}'")
            content = self._fetch_content(url)
            if not content:
                continue

            if feed_type == 'sitemap':
                raw_items.extend(self._parse_sitemap(
                    content, limit=50,
                    allow_regex=feed_config.get('allow_regex'),
                    deny_regex=feed_config.get('deny_regex')
                ))
            else: # Default to 'rss'
                feed = feedparser.parse(content)
                if feed.bozo:
                    logger.warning(f"Feed from {url} is not well-formed: {feed.bozo_exception}")
                raw_items.extend(feed.entries)
        
        all_items = [normalize_item(item) for item in raw_items]

        if logger.isEnabledFor(logging.DEBUG):
            if raw_items:
                logger.debug("RAW sample for %s: %r", source_id, raw_items[0])
            if all_items:
                logger.debug("Normalized sample for %s: %r", source_id, all_items[0])

        seen_urls = set()
        unique_items = []
        for item in all_items:
            item_url = item.get('url')
            if item_url and item_url not in seen_urls:
                unique_items.append(item)
                seen_urls.add(item_url)
        logger.info(f"Found {len(unique_items)} total unique items for {source_id}.")
        return unique_items