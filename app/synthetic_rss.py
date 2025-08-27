import re
import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
            out.append(x)
    return out

def extract_links_via_jsonld(list_url, limit=12):
    r = _request(list_url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    items = []
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '')
        except Exception:
            continue

        # Normaliza para lista
        blobs = data if isinstance(data, list) else [data]
        for blob in blobs:
            # NewsArticle ou BlogPosting
            if isinstance(blob, dict) and blob.get('@type') in ('NewsArticle', 'BlogPosting', 'Article'):
                title = (blob.get('headline') or '').strip()
                href  = (blob.get('url') or '').strip()
                if title and href:
                    if href.startswith('/'):
                        href = urljoin(list_url, href)
                    items.append((title, href))

            # ItemList com listas de artigos
            if isinstance(blob, dict) and blob.get('@type') == 'ItemList':
                for it in blob.get('itemListElement') or []:
                    # itemListElement pode ser dict com 'url'/'name' ou posição+item
                    if isinstance(it, dict):
                        href = (it.get('url') or '').strip()
                        name = (it.get('name') or '').strip()
                        if not href and isinstance(it.get('item'), dict):
                            href = (it['item'].get('url') or '').strip()
                            name = name or (it['item'].get('name') or '').strip()
                        if href and name:
                            if href.startswith('/'):
                                href = urljoin(list_url, href)
                            items.append((name, href))

    items = _dedupe_keep_order([(t, _clean_url(h)) for t, h in items])
    if limit:
        items = items[:limit]
    return items


def extract_links(list_url, selectors, limit=12):
    r = _request(list_url)
    return '\n'.join(parts).encode('utf-8')

def build_synthetic_feed(list_url, selectors=None, limit=12):
    # 1) JSON-LD primeiro (mais robusto)
    items = extract_links_via_jsonld(list_url, limit=limit)
    # 2) Se não achar, cai para seletor CSS
    if not items:
        items = extract_links(list_url, selectors or [], limit=limit)

    if not items:
        raise RuntimeError(f'Nenhum link encontrado em {list_url} (JSON-LD e seletores falharam)')

    domain = urlparse(list_url).netloc
    title = f'RSS Sintético – {domain}'
    desc = f'Feed gerado automaticamente a partir de {list_url}'
    return build_rss_xml(title, list_url, desc, items)

