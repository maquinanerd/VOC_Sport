import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
from email.utils import format_datetime

DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

def _request(url, timeout=10):
    return requests.get(url, timeout=timeout, headers={'User-Agent': DEFAULT_UA})

def _clean_url(url):
    # remove utms e tralhas comuns
    url = re.sub(r'(\?|&)(utm_[^=]+|gclid|fbclid)=[^&]+', '', url)
    url = url.split('#')[0]
    # normaliza // e espaços
    url = re.sub(r'\s+', '', url)
    url = url.replace('://www.', '://www.')  # placeholder para custom se quiser
    return url

def _dedupe_keep_order(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def extract_links(list_url, selectors, limit=12):
    r = _request(list_url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    items = []
    for sel in selectors or ['a']:
        for a in soup.select(sel):
            href = (a.get('href') or '').strip()
            title = (a.get_text() or '').strip()
            if not href or not title:
                continue
            if href.startswith('/'):
                href = urljoin(list_url, href)
            # guarda somente links do mesmo domínio
            if urlparse(href).netloc and urlparse(href).netloc not in urlparse(list_url).netloc:
                continue
            # heurística simples: evita anchors ou javascript:
            if href.startswith('#') or href.startswith('javascript:'):
                continue
            items.append((_clean_url(title), _clean_url(href)))

        if items:
            break  # se o seletor atual já rendeu itens, não tenta os próximos

    # dedupe por link
    items = _dedupe_keep_order(items)
    if limit:
        items = items[:limit]
    return items

def build_rss_xml(title, link, description, items):
    now = format_datetime(datetime.now(timezone.utc))
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f'<title><![CDATA[{title}]]></title>',
        f'<link>{link}</link>',
        f'<description><![CDATA[{description}]]></description>',
        f'<lastBuildDate>{now}</lastBuildDate>',
    ]
    for t, href in items:
        parts += [
            '<item>',
            f'<title><![CDATA[{t}]]></title>',
            f'<link>{href}</link>',
            f'<guid isPermaLink="true">{href}</guid>',
            f'<pubDate>{now}</pubDate>',
            '</item>'
        ]
    parts.append('</channel></rss>')
    return '\n'.join(parts).encode('utf-8')

def build_synthetic_feed(list_url, selectors=None, limit=12):
    items = extract_links(list_url, selectors or [], limit=limit)
    if not items:
        raise RuntimeError(f'Nenhum link encontrado em {list_url} com seletores {selectors}')
    domain = urlparse(list_url).netloc
    title = f'RSS Sintético – {domain}'
    desc = f'Feed gerado automaticamente a partir de {list_url}'
    return build_rss_xml(title, list_url, desc, items)