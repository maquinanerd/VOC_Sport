import logging
import trafilatura
from bs4 import BeautifulSoup
import requests
import html
from typing import Dict, Optional, Any, Set, List, Tuple, Union
import json
import re
import os
import time
from urllib.parse import urljoin, urlparse, parse_qs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .html_utils import normalize_images_with_captions
from .config import USER_AGENT
from trafilatura.metadata import extract_metadata as trafilatura_extract_metadata # New import

logger = logging.getLogger(__name__)

def _coerce_url(candidate: Any) -> Optional[str]:
    """
    Aceita str, dict (ex.: {'url': ...} / {'src': ...} / {'href': ...} / {'content': ...})
    e listas (pega o primeiro válido). Retorna URL (str) ou None.
    """
    if not candidate:
        return None

    # já é string?
    if isinstance(candidate, str):
        u = candidate.strip()
        return u or None

    # lista/tupla: pega o primeiro válido
    if isinstance(candidate, (list, tuple)):
        for item in candidate:
            u = _coerce_url(item)
            if u:
                return u
        return None

    # dict: tenta chaves comuns
    if isinstance(candidate, dict):
        for k in ('url', 'src', 'href', 'content'):
            v = candidate.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            # às vezes vem lista dentro do dict
            if isinstance(v, (list, tuple)):
                u = _coerce_url(v)
                if u:
                    return u
        # às vezes o dict tem só uma key com a URL
        for v in candidate.values():
            u = _coerce_url(v)
            if u:
                return u
        return None

    # desconhecido
    return None

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

BAD_IMAGE_KEYWORDS = {
    'author', 'autor', 'avatar', 'byline', 'perfil', 'profile',
    'placeholder', 'logo', 'logomarca', 'brand', 'marca',
    'icon', 'favicon', 'sprite', 'comment', 'user', 'usuario', 'usuário'
}

BAD_IMAGE_DOMAINS = {
    'gravatar.com', 'twimg.com', 'facebook.com', 'fbcdn.net',
    'gstatic.com', 'googleusercontent.com',
    # Adicionados conforme sugestão para bloquear trackers e placeholders
    "schema.org", "scorecardresearch.com", "doubleclick.net",
    "quantserve.com", "chartbeat.com", "google-analytics.com"
}

# aceita query ?width=1200&height=630 e sufixos -1200x630.jpg
DIM_SUFFIX_RE = re.compile(r'-(\d{2,5})x(\d{2,5})(?=\.[a-z]{3,4})(?:\?.*)?$', re.IGNORECASE)

def _guess_dimensions_from_url(url: str) -> Tuple[Optional[int], Optional[int]]:
    try:
        p = urlparse(url)
        q = parse_qs(p.query or '')
        w = q.get('width') or q.get('w')
        h = q.get('height') or q.get('h')
        if w and h:
            return int(w[0]), int(h[0])
        m = DIM_SUFFIX_RE.search(p.path)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None

def _is_bad_domain(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ''
        return any(host.endswith(d) for d in BAD_IMAGE_DOMAINS)
    except Exception:
        return False


YOUTUBE_DOMAINS = (
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be",
)

_YT_PATTERNS = (
    r"(?:youtube\.com/(?:embed/|shorts/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})",
)

PRIORITY_CDN_DOMAINS = (
    "static1.srcdn.com",              # ScreenRant
    "static1.colliderimages.com",     # Collider
    "static1.cbrimages.com",          # CBR
    "static1.moviewebimages.com",     # MovieWeb
    "static0.gamerantimages.com", "static1.gamerantimages.com",
    "static2.gamerantimages.com", "static3.gamerantimages.com",  # GameRant
    "static1.thegamerimages.com",     # TheGamer
)

FORBIDDEN_TEXT_EXACT: Set[str] = {
    "Your comment has not been saved",
}

FORBIDDEN_LABELS: Set[str] = {
    "Release Date", "Runtime", "Director", "Directors", "Writer", "Writers",
    "Producer", "Producers", "Cast"
}

JUNK_IMAGE_PATTERNS = (
    "placeholder", "sprite", "icon", "emoji", ".svg",
    # From user suggestion to filter out non-content images
    "cta", "read-more", "share", "logo", "banner"
)

# Blocos a ignorar (relacionados/sidebars/galerias etc.)
_BAD_SECTION_RX = re.compile(
    r"(related|trending|more|sidebar|aside|recommend|recommended|"
    r"gallery|carousel|slideshow|video|playlist|social|share|"
    r"footer|header|nav|subscribe|newsletter|ad|advert|sponsor|"
    # From user suggestion
    r"cta|banner|paid|outbrain|taboola|"
    r"screen-hub|screenhub|hub|most-popular|popular)",
    re.I
)


def _parse_srcset(srcset: str):
    """Retorna a URL com maior largura declarada em um srcset."""
    best = None
    best_w = -1
    for part in (srcset or "").split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        url = tokens[0]
        w = 0
        if len(tokens) > 1 and tokens[1].endswith("w"):
            try:
                w = int(tokens[1][:-1])
            except Exception:
                w = 0
        if w >= best_w:
            best_w = w
            best = url
    return best


def _has_bad_keyword(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in BAD_IMAGE_KEYWORDS)

def _is_junk_filename(url: str) -> bool:
    """Checks if the image filename suggests it's a non-content image."""
    try:
        name = urlparse(url).path.rsplit("/", 1)[-1].lower()
        return any(snippet in name for snippet in JUNK_IMAGE_PATTERNS)
    except Exception:
        return False # Fail safe

def _passes_min_size(url: str, min_w: int = 600, min_h: int = 315) -> bool:
    w, h = _guess_dimensions_from_url(url)
    if w is None or h is None:
        # Sem dimensão explícita: aceita provisoriamente (muitos sites não expõem)
        return True
    if w < min_w or h < min_h:
        return False
    # evita quase-quadradas/estranhas como avatar 150x150
    ar = w / h if h else 0
    return 0.6 <= ar <= 2.2

def is_valid_article_image(url: str) -> bool:
    if not url or url.startswith('data:'):
        return False
    if _is_bad_domain(url):
        return False
    if _has_bad_keyword(url):
        return False
    if _is_junk_filename(url):
        return False
    if not _passes_min_size(url):
        return False
    return True

def pick_featured_image(candidates: list[str]) -> Optional[str]:
    """Retorna a primeira imagem que passa no filtro."""
    for u in candidates:
        if is_valid_article_image(u):
            return u
    return None


def _abs(u: str, base: str) -> Optional[str]:
    if not u:
        return None
    u = u.strip()
    if not u or u.startswith("data:"):
        return None
    return urljoin(base, u)


def _extract_from_style(style_attr: str) -> Optional[str]:
    if not style_attr:
        return None
    m = re.search(r"url\((['\"]?)(.*?)\1\)", style_attr)
    return m.group(2) if m else None


def _find_article_body(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Tenta localizar o nó raiz do corpo do artigo.
    - Prefere seletores comuns (article body/content)
    - Evita nós com classes/ids que casem _BAD_SECTION_RX
    - Fallback: nó com mais <p> + <figure>
    """    
    # Enhanced with user suggestions for more specific content containers
    candidates = soup.select(
        "article .entry-content, article .content, article [itemprop='articleBody'], "
        ".post-content, .single-content, .post-body, "
        "[itemprop='articleBody'], .article-body, .article-content, " # Original selectors
        "article" # Fallback
    )
    if not candidates:
        candidates = soup.find_all(True)

    best, best_score = None, -1
    for c in candidates:
        classes = " ".join(c.get("class", [])) + " " + (c.get("id") or "")
        if _BAD_SECTION_RX.search(classes):
            continue
        # Evita wrappers muito genéricos do site
        if c.name in ("header", "footer", "nav", "aside"):
            continue
        score = len(c.find_all("p")) + len(c.find_all("figure"))
        if score > best_score:
            best, best_score = c, score
    return best or soup


def collect_images_from_article(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    Coleta URLs de imagens relevantes SOMENTE DO CORPO DO ARTIGO.
    Fontes consideradas:
      - <img> (src, data-*, srcset)
      - <picture><source srcset="...">
      - nós com atributos data-*
      - estilos inline: background-image
      - <figure> contendo <img>
    Aplica filtros de junk/thumb e prioriza CDNs conhecidas.
    """
    root = _find_article_body(soup)
    urls: list[str] = []

    def _push(candidate: Optional[str]) -> None:
        if not candidate:
            return
        abs_u = _abs(candidate, base_url)
        if not abs_u:
            return
        if not is_valid_article_image(abs_u):
            return
        urls.append(abs_u.rstrip("/"))

    # 1) <img> tags
    for img in root.select("img:not([aria-hidden='true'])"):
        cand = None
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image", "data-img-url"):
            if img.get(attr):
                cand = img.get(attr)
                break
        if not cand and img.get("srcset"):
            cand = _parse_srcset(img.get("srcset"))
        _push(cand)

    # 2) <picture><source>
    for source in root.select("picture source[srcset]"):
        _push(_parse_srcset(source.get("srcset", "")))

    # 2.5) <noscript> com <img> (fallback de lazy-load)
    for ns in root.find_all("noscript"):
        try:
            inner = BeautifulSoup(ns.string or "", "html.parser")
        except Exception:
            continue
        for img in inner.find_all("img"):
            _push(img.get("src") or img.get("data-src") or img.get("data-original"))

    # 3) nós com data-* comuns
    for node in root.select('[data-img-url], [data-image], [data-src], [data-original]'):
        cand = node.get("data-img-url") or node.get("data-image") or node.get("data-src") or node.get("data-original")
        _push(cand)

    # 4) estilos inline background-image
    for node in root.select('[style*="background-image"]'):
        _push(_extract_from_style(node.get("style", "")))

    # 5) <figure> com <img> (ou srcset)
    for fig in root.find_all("figure"):
        img = fig.find("img")
        if img:
            if img.get("src"):
                _push(img.get("src"))
            elif img.get("srcset"):
                _push(_parse_srcset(img.get("srcset", "")))

    # de-dup preservando preferência das CDNs
    dedup: dict[str, int] = {}
    for u in urls:
        host = urlparse(u).netloc
        pref = 0 if host in PRIORITY_CDN_DOMAINS else 1
        dedup[u] = min(dedup.get(u, pref), pref)
    ordered = sorted(dedup.items(), key=lambda kv: (kv[1], kv[0]))
    return [u for u, _ in ordered]

# --- New helper functions from user prompt ---
def _get(url, timeout=25, tries=2):
    last_err = None
    for _ in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
            if 200 <= r.status_code < 300 and "text/html" in r.headers.get("Content-Type",""):
                return r
        except Exception as e:
            last_err = e
        time.sleep(0.6)
    if last_err:
        raise last_err
    raise RuntimeError(f"HTTP error fetching {url}")

def _clean_text(s):
    if not s: return ""
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()

def _trafilatura_extract_core(url, html_text): # Renamed to avoid conflict with class method
    downloaded = trafilatura.extract(
        filecontent=html_text,
        url=url,
        include_images=False,
        include_links=False,
        with_metadata=True,
    )
    if not downloaded:
        return None
    meta = trafilatura_extract_metadata(html_text, url) # Use the imported metadata extractor
    return {
        "title": (meta.title if meta and meta.title else None),
        "text": downloaded.strip(),
        "author": (", ".join(meta.author) if meta and meta.author else None),
        "date": (meta.date if meta and meta.date else None),
        "top_image": None, # This will be filled by _pick_featured_image later
    }

def _wp_fallback(soup):
    # WordPress common selectors: title, content, author, date, image
    title = soup.select_one("h1.asset-title, h1.entry-title, h1.post-title, header h1") # Added asset-title for infomoney
    content = soup.select_one("div.article-content, div.entry-content, .single-post-content, .post-content, article .content")
    author = soup.select_one('[rel="author"], .author-name, .byline .author a, .byline a[rel="author"]')
    date = soup.select_one("time[datetime], .post-date, .entry-date")
    img = soup.select_one("article figure img, .wp-block-image img, .post-thumbnail img")
    return {
        "title": _clean_text(title.get_text()) if title else None,
        "text": _clean_text("\n".join([p.get_text(" ", strip=True) for p in content.select("p")])) if content else None,
        "author": _clean_text(author.get_text()) if author else None,
        "date": (date.get("datetime") if date and date.has_attr("datetime") else _clean_text(date.get_text()) if date else None),
        "top_image": (img.get("src") if img and img.has_attr("src") else None),
    }

def _estadao_arc_fallback(soup):
    # Estadão (Arc): title and body are often in <article> with specific blocks
    title = soup.select_one("h1.n--noticia__title, h1, header h1") # Added n--noticia__title for estadao
    paras = soup.select("[data-qa='body-text']") or soup.select("article p")
    text = _clean_text("\n".join(p.get_text(" ", strip=True) for p in paras)) if paras else None
    author = soup.select_one("[data-qa='author-name'], .author-name, a[rel='author']")
    date = soup.select_one("time[datetime]")
    img = soup.select_one("figure img, .lead-media img")
    return {
        "title": _clean_text(title.get_text()) if title else None,
        "text": text,
        "author": _clean_text(author.get_text()) if author else None,
        "date": date.get("datetime") if date and date.has_attr("datetime") else None,
        "top_image": img.get("src") if img and img.has_attr("src") else None,
    }

def _choose_best(a, b):
    # Fills empty fields in A with values from B
    if not a: return b
    if not b: return a
    out = {}
    for k in {"title","text","author","date","top_image"}:
        out[k] = a.get(k) or b.get(k)
    return out

def _extract_site_specific(soup: BeautifulSoup, url: str, selectors: Dict[str, Union[str, List[str]]]) -> Optional[Dict[str, Any]]:
    """
    Helper for site-specific extraction using a dictionary of CSS selectors.
    Falls back gracefully by returning None if key elements are not found.
    """
    try:
        # Find title
        title_tag = soup.select_one(str(selectors['title']))
        title = title_tag.get_text(strip=True) if title_tag else None

        # Find content body
        content_tag = soup.select_one(str(selectors['content']))

        if not title or not content_tag:
            logger.warning(f"Specific extractor failed to find title/content for {url}. Will fall back to generic.")
            return None

        # Basic cleanup inside content
        for junk_selector in selectors.get('junk', []):
            for junk_tag in content_tag.select(str(junk_selector)):
                junk_tag.decompose()
        
        content_html = str(content_tag)

        # Use existing helpers for media and metadata
        # Note: These helpers operate on the *original* soup object to find meta tags, etc.
        extractor = ContentExtractor() # Temporary instance to access helpers
        featured_image_url = extractor._pick_featured_image(soup, url)
        images = collect_images_from_article(soup, url) # This also uses its own logic to find the body
        videos = extractor._extract_youtube_videos(soup)
        
        excerpt_tag = soup.select_one('meta[name="description"], meta[property="og:description"]')
        excerpt = excerpt_tag['content'].strip() if excerpt_tag and excerpt_tag.get('content') else ''

        # Ensure the featured image isn't duplicated in the body images list
        other_images = [img for img in images if img != featured_image_url]

        result = {
            "title": title,
            "content": content_html,
            "excerpt": excerpt,
            "featured_image_url": featured_image_url,
            "images": other_images,
            "videos": videos,
            "source_url": url,
        }
        
        logger.info(f"Successfully extracted content using specific extractor for {url}. Title: {result['title'][:50]}...")
        return result

    except Exception as e:
        # Log with exc_info=False to avoid a huge traceback for a common fallback case
        logger.error(f"Error in site-specific extractor for {url}: {e}. Falling back to generic.", exc_info=False)
        return None

def _extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Encontra e parseia todos os scripts do tipo ld+json da página.
    """
    json_ld_data = []
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        if script.string:
            try:
                # Corrigir JSONs malformados com vírgulas extras
                clean_str = re.sub(r',\s*([}\]])', r'\1', script.string)
                data = json.loads(clean_str)
                if isinstance(data, dict):
                    json_ld_data.append(data)
                elif isinstance(data, list):
                    json_ld_data.extend([d for d in data if isinstance(d, dict)])
            except json.JSONDecodeError:
                logger.warning("Falha ao parsear script JSON-LD.", exc_info=False)
    return json_ld_data

def _find_news_article_in_json_ld(json_ld_data: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Busca nos dados JSON-LD parseados por um objeto NewsArticle, Article ou BlogPosting.
    """
    for data in json_ld_data:
        graph = data.get('@graph', [data])
        for item in graph:
            if isinstance(item, dict) and item.get('@type') in ('NewsArticle', 'Article', 'BlogPosting'):
                return item
    return None

# --- New constants for related content removal ---
LEIA_HEADING_RE = re.compile(r"(leia também|veja também|relacionad[oa]s|recomendad[oa]s|tópicos relacionados)", re.I)

# Site-specific rules for related content
SITE_SPECIFIC_RELATED_SELECTORS = {
    "infomoney.com.br": [
        ".single__related", ".article__related", ".post-related", ".related-posts",
        ".rm-related", ".block-related", ".single__sidebar", ".article__sidebar",
        "section.single__see-also", ".wp-block-infomoney-blocks-infomoney-read-more",
    ],
    "estadao.com.br": [
        ".links-relacionados", ".mat-relacionadas", ".es-relacionadas",
        ".stories-related", ".see-also", ".link-relacionado", ".box-relacionadas",
    ],
}


class ContentExtractor:
    """Extrai e limpa conteúdo para o pipeline."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        # Configure retries with backoff as requested
        retries = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            # Increased timeout to 75s as requested
            resp = self.session.get(url, timeout=75.0, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch HTML from {url}: {e}")
            return None

    def _pre_clean_html(self, soup: BeautifulSoup, url: str) -> str:
        """Remove widgets/ads/blocos óbvios ANTES da extração."""
        # --- New robust related content removal logic from user patch ---
        try:
            # 1. Remove sections by heading text (e.g., "Leia também")
            # Iterate backwards to avoid issues with modifying the list while iterating
            for h in reversed(soup.find_all(re.compile("^h[1-6]$"))):
                heading_text = h.get_text(" ", strip=True)
                if heading_text and LEIA_HEADING_RE.search(heading_text):
                    parent_container = h.find_parent(('section', 'aside', 'div'))
                    if parent_container and len(parent_container.find_all(re.compile("^h[1-6]$"))) <= 2:
                        logger.debug(f"Decomposing parent container '{parent_container.name}' of related heading: {heading_text}")
                        parent_container.decompose()
                    else:
                        logger.debug(f"Decomposing related heading and its sibling: {heading_text}")
                        next_sibling = h.find_next_sibling()
                        if next_sibling and next_sibling.name in ("div", "ul", "section", "ol"):
                            next_sibling.decompose()
                        h.decompose()
            
            # 2. Remove by site-specific selectors
            source_host = (urlparse(url).hostname or "").replace("www.", "")
            if source_host in SITE_SPECIFIC_RELATED_SELECTORS:
                for sel in SITE_SPECIFIC_RELATED_SELECTORS[source_host]:
                    for el in soup.select(sel):
                        el.decompose()
            
            # 3. Remove links that are likely related content wrappers
            for a in soup.select("a"):
                cls = " ".join(a.get("class", [])).lower()
                if any(k in cls for k in ["relacion", "related", "leia", "veja"]) or a.get("data-gtm-cta") in ("related", "see_more"):
                    a.decompose()

        except Exception as e:
            logger.warning(f"Error during advanced related content removal for {url}: {e}", exc_info=False)
        # --- End of new logic ---

        # Merged list from original and user suggestions for more robust cleaning
        selectors_to_remove = {
            # User-suggested selectors for CTAs, ads, and social sharing
            ".cta-middle", ".infomoney-read-more", ".read-more", ".post__related",
            ".sharing", ".share", ".social", ".banner", ".ads", ".advertisement",
            "[data-ad]", "[data-ad-slot]",
            ".sponsored", ".paid-content", ".partner", ".outbrain", ".taboola",
            
            # Original selectors
            '[class*="srdb"]', '[class*="rating"]', '.review', '.score', '.meter',
            'header', 'footer', 'nav', 'aside',
            '[class*="related"]', '[id*="related"]',
            # From user's patch (GENERIC_REL_SELECTORS)
            "[class*='relacionad']", "[class*='relaciona']", "[class*='recommend']",
            "[class*='veja-tambem']", "[class*='leia-tambem']", "[id*='relacionad']",
            "[id*='leia']", "section[aria-label*='Leia']", "section[aria-label*='Relacionad']",
            '[class*="trending"]', '[id*="trending"]', 'div.widget',
            '[class*="sidebar"]',  '[id*="sidebar"]',
            '[class*="recommend"]','[class*="recommended"]',
            '[class*="screen-hub"]','[class*="screenhub"]',
            '[class*="most-popular"]','[id*="most-popular"]',
            '[class*="popular"]','[id*="popular"]',
            '[class*="newsletter"]','[id*="newsletter"]',
            '[class*="ad-"]','[id*="ad-"]','[class*="advert"]','[id*="advert"]',
            '.comments', '#comments',
            '.author', '.author-box', '.post-author', '.byline', '.entry-author',
            '.avatar', '.author__image', '.author-profile',
            '.subscribe',
        }
        for sel in selectors_to_remove:
            for el in soup.select(sel):
                try:
                    el.decompose()
                except Exception:
                    pass

        # remover texto "powered by srdb"
        for text_node in soup.find_all(string=lambda t: isinstance(t, str) and "powered by srdb" in t.lower()):
            p = text_node.find_parent()
            if p:
                try:
                    p.decompose()
                except Exception:
                    pass

        logger.info("Pre-cleaned HTML, removing unwanted widgets and blocks.")

        # Focus on the main article body to avoid extracting junk from sidebars
        article = (
            soup.select_one("[itemprop='articleBody']") or
            soup.select_one("div#mc-body") or  # fallback GE
            soup
        )

        return str(article)

    def _remove_forbidden_blocks(self, soup: BeautifulSoup) -> None:
        """Remove infobox técnica e mensagens indesejadas do html extraído."""
        for t in soup.find_all(string=True):
            s = (t or "").strip()
            if s and s in FORBIDDEN_TEXT_EXACT:
                try:
                    t.parent.decompose()
                except Exception:
                    pass

        candidates = []
        for tag in soup.find_all(["div", "section", "aside", "ul", "ol"]):
            text = " ".join(tag.get_text(separator="\n").split())
            lbl_count = sum(1 for lbl in FORBIDDEN_LABELS
                            if re.search(rf"(^|\n)\s*{re.escape(lbl)}\s*(\n|:|$)", text, flags=re.I))
            if lbl_count >= 2:
                candidates.append(tag)
        for c in candidates:
            try:
                c.decompose()
            except Exception:
                pass

        for tag in soup.find_all(["p", "li", "span", "h3", "h4"]):
            if not tag.parent:
                continue
            s = (tag.get_text() or "").strip().rstrip(':').strip()
            if s in FORBIDDEN_TEXT_EXACT or s in FORBIDDEN_LABELS:
                try:
                    tag.decompose()
                except Exception:
                    pass

    def _convert_data_img_to_figure(self, soup: BeautifulSoup):
        """
        Converte divs com 'data-img-url' em <figure><img>.
        Faz APENAS dentro do corpo do artigo para não pegar sidebar.
        """
        root = _find_article_body(soup)
        converted = 0
        for div in root.select('div[data-img-url]'):
            img_url = div['data-img-url']
            fig = soup.new_tag('figure')
            img = soup.new_tag('img', src=img_url)
            cap = soup.new_tag('figcaption')
            caption_text = div.get_text(strip=True)
            if caption_text:
                cap.string = caption_text
                img['alt'] = caption_text
            fig.append(img)
            if caption_text:
                fig.append(cap)
            try:
                div.replace_with(fig)
                converted += 1
            except Exception:
                pass
        if converted:
            logger.info(f"Converted {converted} 'data-img-url' divs to <figure> tags.")

    def _pick_featured_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """
        Picks the featured image with a clear priority:
        1. og:image / og:image:secure_url
        2. twitter:image
        3. First valid <img> inside <article> or <figure>
        It also filters out known tracker/placeholder domains.
        """
        # Helper to check domain and basic validity
        def is_valid_source_url(url: Optional[str]) -> bool:
            if not url or not url.strip().startswith(("http://", "https")):
                return False
            try:
                host = urlparse(url).netloc.lower()
                if not host or any(bad_domain in host for bad_domain in BAD_IMAGE_DOMAINS):
                    return False
            except Exception:
                return False
            return True

        # 1) og:image / og:image:secure_url
        for prop in ("og:image", "og:image:secure_url"):
            tag = soup.find("meta", property=prop)
            if tag and is_valid_source_url(tag.get("content")):
                return urljoin(base_url, tag["content"])

        # 2) twitter:image
        tag = soup.find("meta", attrs={"name": "twitter:image"})
        if tag and is_valid_source_url(tag.get("content")):
            return urljoin(base_url, tag["content"])

        # 3) First <figure><img> or <article><img>
        for img in soup.select("article img, .content img, figure img"):
            src = img.get("data-src") or img.get("src")
            if is_valid_source_url(src):
                return urljoin(base_url, src)
        
        logger.warning(f"Could not find a valid featured image for {base_url}")
        return None

    def _extract_youtube_id(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        """
        Extracts a YouTube video ID from a URL using various patterns.
        Optionally uses the soup object to find a fallback ID in meta tags.
        """
        if not url:
            return None

        # 1) Common patterns (embed/shorts/youtu.be)
        for pattern in _YT_PATTERNS:
            m = re.search(pattern, url)
            if m:
                return m.group(1)

        # 2) watch?v=ID
        try:
            pu = urlparse(url)
            if "youtube.com" in pu.netloc and pu.path == "/watch":
                q = parse_qs(pu.query)
                if "v" in q and len(q["v"][0]) == 11:
                    return q["v"][0]
        except Exception:
            pass

        # 3) Optional fallback using og:image (only if soup is provided)
        if soup is not None:
            try:
                og = soup.find("meta", property="og:image")
                if og and og.get("content"):
                    # og:image often ends with .../<ID>/hqdefault.jpg
                    mm = re.search(r"/([A-Za-z0-9_-]{11})/hqdefault", og["content"])
                    if mm:
                        return mm.group(1)
            except Exception:
                pass

        return None

    def _extract_youtube_videos(self, soup: BeautifulSoup) -> list[dict]:
        ids = []
        for iframe in soup.find_all("iframe"):
            vid = self._extract_youtube_id(iframe.get("src", ""), soup=soup)
            if vid:
                ids.append(vid)
        for div in soup.select('.w-youtube[id], .youtube[id], [data-youtube-id]'):
            vid = div.get("id") or div.get("data-youtube-id")
            if vid:
                ids.append(vid)
        seen, ordered = set(), []
        for v in ids:
            if v and v not in seen:
                seen.add(v)
                ordered.append(v)
        if ordered:
            logger.info(f"Found {len(ordered)} unique YouTube videos.")
        return [{"id": v, "embed_url": f"https://www.youtube.com/embed/{v}",
                 "watch_url": f"https://www.youtube.com/watch?v={v}"} for v in ordered]

    def _extract_with_trafilatura(self, html: str, url: str) -> Optional[Dict[str, Any]]:
        """
        Generic extraction method using Trafilatura as the core engine.
        This was the original `extract` method.
        """
        logger.debug(f"Using generic (trafilatura) extractor for {url}")
        try:
            soup = BeautifulSoup(html, 'lxml')

            # 1) Tenta extrair metadados de JSON-LD primeiro, pois é a fonte mais confiável
            all_json_ld = _extract_json_ld(soup)
            news_article_schema = _find_news_article_in_json_ld(all_json_ld)

            # 4) Extrai imagem destacada com a nova lógica de priorização
            featured_image_url = self._pick_featured_image(soup, url)

            # 5) Extrai imagens do corpo do artigo
            body_images = collect_images_from_article(soup, base_url=url)

            # 6) vídeos
            videos = self._extract_youtube_videos(soup)

            # 7) metadados: Prioriza JSON-LD, com fallback para tags meta
            title = 'No Title Found'
            excerpt = ''
            if news_article_schema:
                logger.info(f"Usando metadados do JSON-LD para {url}")
                title = news_article_schema.get('headline') or news_article_schema.get('name') or title
                excerpt = news_article_schema.get('description') or excerpt
                if not featured_image_url:
                     featured_image_url = _coerce_url(news_article_schema.get('image'))
            else: # Fallback
                title = (og_title.get('content') if (og_title := soup.find('meta', property='og:title')) else None) or (soup.title.string if soup.title else title)
                excerpt = (meta_desc.get('content') if (meta_desc := soup.find('meta', attrs={'name': 'description'})) else None) or \
                          (og_desc.get('content') if (og_desc := soup.find('meta', property='og:description')) else '')

            # 2) Limpeza prévia pesada e normalização de imagens
            # A limpeza agora retorna uma string do corpo do artigo focado
            body_html_string = self._pre_clean_html(BeautifulSoup(html, 'lxml'), url)
            body_html_string = normalize_images_with_captions(body_html_string)

            # 3) normaliza data-img-url -> <figure> (agora dentro de normalize_images)
            # self._convert_data_img_to_figure(soup) # Esta lógica foi absorvida/melhorada

            # 8) extrair corpo com trafilatura
            content_html = trafilatura.extract(
                body_html_string,
                include_images=True,
                include_links=True,
                include_comments=False,
                include_tables=False,
                output_format='html'
            )
            if not content_html:
                logger.warning(f"Trafilatura returned empty content for {url}")
                return None

            # 9) pós-processar corpo
            article_soup = BeautifulSoup(content_html, 'lxml')
            self._remove_forbidden_blocks(article_soup)

            # 10) Seleciona imagens do corpo (excluindo a destacada)
            # A `collect_images_from_article` já aplica `is_valid_article_image`
            other_valid_images = [
                u for u in body_images if u != featured_image_url
            ]

            logger.info(f"Selected featured image: {featured_image_url}. Found {len(other_valid_images)} other valid images.")

            # Conteúdo final: só o conteúdo interno do <body>, se existir
            if article_soup.body:
                final_content_html = article_soup.body.decode_contents()
            else:
                final_content_html = str(article_soup)
            result = {
                "title": title.strip(),
                "content": final_content_html,
                "excerpt": (excerpt or "").strip(),
                "featured_image_url": featured_image_url,
                "images": other_valid_images,
                "videos": videos,
                "source_url": url,
                "schema_original": news_article_schema # Passa o schema extraído adiante
            }
            logger.info(f"Successfully extracted and cleaned content from {url}. Title: {result['title'][:50]}...")
            return result

        except Exception as e:
            logger.error(f"An unexpected error occurred during extraction for {url}: {e}", exc_info=True)
            return None

    def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Main extraction flow: fetches HTML, tries a site-specific extractor if available,
        and falls back to the generic trafilatura-based extractor.
        """
        html = self._fetch_html(url)
        if not html:
            return None

        domain = urlparse(url).netloc.lower()
        soup = BeautifulSoup(html, 'lxml')
        
        extracted_data = None

        # Router for site-specific extractors
        if 'infomoney.com.br' in domain:
            selectors = {
                'title': 'h1.asset-title, h1.entry-title',
                'content': 'div.article-content, div.entry-content',
                'junk': ['.advertisement', '.leia-mais', '.box-leia-mais', '.box-newsletter', '.article-related-box']
            }
            extracted_data = _extract_site_specific(soup, url, selectors)
        
        elif 'estadao.com.br' in domain:
            selectors = {
                'title': 'h1.n--noticia__title, h1.entry-title',
                'content': 'div.n--noticia__content.content, div.entry-content',
                'junk': ['.veja-tambem', '.publicidade', '.box-relacionadas', '.posts-relacionados']
            }
            extracted_data = _extract_site_specific(soup, url, selectors)

        # If a specific extractor ran and succeeded, return its data.
        if extracted_data:
            return extracted_data
        
        # Otherwise, fall back to the generic method.
        return self._extract_with_trafilatura(html, url)
