import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
from email.utils import format_datetime

logger = logging.getLogger(__name__)

DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

def _request(url, timeout=15):
    """Makes a request with a default user-agent."""
    return requests.get(url, timeout=timeout, headers={'User-Agent': DEFAULT_UA})

def _clean_url(url):
    """Removes common tracking parameters and fragments from a URL."""
    url = re.sub(r'(\?|&)(utm_[^=]+|gclid|fbclid)=[^&]+', '', url)
    url = url.split('#')[0]
    url = re.sub(r'\s+', '', url)
    return url

def _dedupe_keep_order(seq):
    """Deduplicates a sequence while preserving order."""
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def extract_links_via_jsonld(list_url, limit=12):
    """Extracts links from JSON-LD script tags, which are more stable."""
    try:
        r = _request(list_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
    except requests.RequestException as e:
        logger.error(f"JSON-LD request for {list_url} failed: {e}")
        return []

    items = []
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '')
        except Exception:
            continue

        blobs = data if isinstance(data, list) else [data]
        for blob in blobs:
            if isinstance(blob, dict) and blob.get('@type') in ('NewsArticle', 'BlogPosting', 'Article'):
                title = (blob.get('headline') or '').strip()
                href  = (blob.get('url') or '').strip()
                if title and href:
                    full_url = urljoin(list_url, href) if href.startswith('/') else href
                    items.append((title, full_url))

            if isinstance(blob, dict) and blob.get('@type') == 'ItemList':
                for it in blob.get('itemListElement') or []:
                    if isinstance(it, dict):
                        href = (it.get('url') or '').strip()
                        name = (it.get('name') or '').strip()
                        if not href and isinstance(it.get('item'), dict):
                            href = (it['item'].get('url') or '').strip()
                            name = name or (it['item'].get('name') or '').strip()
                        if href and name:
                            full_url = urljoin(list_url, href) if href.startswith('/') else href
                            items.append((name, full_url))

    # Clean and deduplicate results
    clean_items = _dedupe_keep_order([(t, _clean_url(h)) for t, h in items])
    if limit:
        clean_items = clean_items[:limit]
    
    if clean_items:
        logger.info(f"Extracted {len(clean_items)} links via JSON-LD from {list_url}")
    return clean_items

def extract_links(list_url, selectors, limit=12):
    """Extracts links using CSS selectors as a fallback."""
    try:
        r = _request(list_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
    except requests.RequestException as e:
        logger.error(f"CSS selector request for {list_url} failed: {e}")
        return []

    items = []
    for sel in selectors or ['a']:
        for a in soup.select(sel):
            href = (a.get('href') or '').strip()
            title = (a.get_text() or '').strip()
            if not href or not title or href.startswith(('#', 'javascript:')):
                continue
            
            full_url = urljoin(list_url, href) if href.startswith('/') else href
            
            if urlparse(full_url).netloc and urlparse(full_url).netloc not in urlparse(list_url).netloc:
                continue
                
            items.append((title, full_url))

        if items:
            logger.info(f"Extracted {len(items)} links via CSS selector '{sel}' from {list_url}")
            break

    clean_items = _dedupe_keep_order([(_clean_url(t), _clean_url(h)) for t, h in items])
    if limit:
        clean_items = clean_items[:limit]
    return clean_items

def build_rss_xml(title, link, description, items):
    """Builds a valid RSS 2.0 XML string from extracted items."""
    now = format_datetime(datetime.now(timezone.utc))
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        '  <channel>',
        f'    <title><![CDATA[{title}]]></title>',
        f'    <link>{link}</link>',
        f'    <description><![CDATA[{description}]]></description>',
        f'    <lastBuildDate>{now}</lastBuildDate>',
        f'    <atom:link href="{link}" rel="self" type="application/rss+xml" />'
    ]
    for t, href in items:
        parts.extend([
            '    <item>',
            f'      <title><![CDATA[{t}]]></title>',
            f'      <link>{href}</link>',
            f'      <guid isPermaLink="true">{href}</guid>',
            f'      <pubDate>{now}</pubDate>',
            '    </item>'
        ])
    parts.extend(['  </channel>', '</rss>'])
    return '\n'.join(parts).encode('utf-8')

def build_synthetic_feed(list_url, selectors=None, limit=12):
    """Tries to build a feed using JSON-LD first, then falls back to CSS."""
    items = extract_links_via_jsonld(list_url, limit=limit)
    if not items:
        logger.warning(f"JSON-LD failed for {list_url}. Falling back to CSS selectors.")
        items = extract_links(list_url, selectors or [], limit=limit)

    if not items:
        raise RuntimeError(f'Failed to find any links on {list_url} (JSON-LD and CSS selectors failed)')

    domain = urlparse(list_url).netloc
    title = f'RSS Sintético – {domain}'
    desc = f'Feed gerado automaticamente a partir de {list_url}'

