import logging
import trafilatura
from bs4 import BeautifulSoup
import requests
from typing import Dict, Optional, Any, Set
from urllib.parse import urljoin, urlparse, parse_qs
import json
import re

from .config import USER_AGENT

logger = logging.getLogger(__name__)

YOUTUBE_DOMAINS = (
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be",
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

JUNK_IMAGE_PATTERNS = ("placeholder", "sprite", "icon", "emoji", ".svg")

# Blocos a ignorar (relacionados/sidebars/galerias etc.)
_BAD_SECTION_RX = re.compile(
    r"(related|trending|more|sidebar|aside|recommend|recommended|"
    r"gallery|carousel|slideshow|video|playlist|social|share|"
    r"footer|header|nav|subscribe|newsletter|ad|advert|sponsor|"
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


def is_small(u: str) -> bool:
    """Heurística para descartar thumbs e imagens irrelevantes."""
    if not u:
        return True
    low = u.lower()

    # lixo comum
    if any(pat in low for pat in ("placeholder","sprite","icon","emoji",".svg")):
        return True

    # posters/avatares genéricos do Collider
    if "colliderimages.com" in low and ("/sharedimages/" in low or "poster" in low):
        return True

    # thumbs de card (fit=crop 420x300 etc.)
    try:
        params = parse_qs(urlparse(u).query)
        w = int((params.get("w",["0"])[0] or "0"))
        h = int((params.get("h",["0"])[0] or "0"))
        fit = (params.get("fit",[""])[0] or "").lower()
        if fit == "crop" and ((w and w <= 600) or (h and h <= 400)):
            return True
        if (w and w < 320) or (h and h < 200):
            return True
    except Exception:
        pass
    return False


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
    candidates = soup.select(
        "[itemprop='articleBody'], .article-body, .article-content, "
        ".entry-content, .post-content, article .content, article"
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
        if is_small(abs_u):
            return
        urls.append(abs_u.rstrip("/"))

    # 1) <img> tags
    for img in root.find_all("img"):
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


class ContentExtractor:
    """Extrai e limpa conteúdo para o pipeline."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=20.0, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch HTML from {url}: {e}")
            return None

    def _pre_clean_html(self, soup: BeautifulSoup):
        """Remove widgets/ads/blocos óbvios ANTES da extração."""
        selectors_to_remove = [
            # metadados/ratings
            '[class*="srdb"]', '[class*="rating"]', '.review', '.score', '.meter',
            # blocos ruins por padrão
            'header', 'footer', 'nav', 'aside',
            # areas relacionadas/trending/comentários
            '[class*="related"]', '[id*="related"]',
            '[class*="trending"]', '[id*="trending"]',
            '[class*="sidebar"]',  '[id*="sidebar"]',
            '[class*="recommend"]','[class*="recommended"]',
            '[class*="screen-hub"]','[class*="screenhub"]',
            '[class*="most-popular"]','[id*="most-popular"]',
            '[class*="popular"]','[id*="popular"]',
            '[class*="newsletter"]','[id*="newsletter"]',
            '[class*="ad-"]','[id*="ad-"]','[class*="advert"]','[id*="advert"]',
            '.comments', '#comments'
        ]
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

    def _extract_featured_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extrai imagem destacada (og/twitter/json-ld/primeira <img> de article)."""
        if og := soup.find('meta', property='og:image'):
            if og.get('content'):
                logger.info("Found featured image via 'og:image'.")
                return urljoin(base_url, og['content'])

        if tw := soup.find('meta', attrs={'name': 'twitter:image'}):
            if tw.get('content'):
                logger.info("Found featured image via 'twitter:image'.")
                return urljoin(base_url, tw['content'])

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    if item.get('@type') in ('NewsArticle', 'Article') and 'image' in item:
                        image_info = item['image']
                        if isinstance(image_info, dict) and image_info.get('url'):
                            return urljoin(base_url, image_info['url'])
                        if isinstance(image_info, list) and image_info:
                            first = image_info[0]
                            return urljoin(base_url, first.get('url') if isinstance(first, dict) else first)
                        if isinstance(image_info, str):
                            return urljoin(base_url, image_info)
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        if article_tag := soup.find('article'):
            first_img = article_tag.find('img')
            if first_img and first_img.get('src'):
                logger.info("Using first <img> in <article> as featured image.")
                return urljoin(base_url, first_img['src'])

        logger.warning("Could not find a suitable featured image.")
        return None

    def _extract_youtube_id(self, src: str) -> Optional[str]:
        if not src:
            return None
        try:
            u = urlparse(src)
            if u.netloc not in YOUTUBE_DOMAINS and not any(u.netloc.endswith(d) for d in YOUTUBE_DOMAINS):
                return None
            if u.path.startswith("/embed/") or u.path.startswith("/shorts/"):
                return u.path.split("/")[2].split("?")[0]
            if u.netloc.endswith("youtu.be"):
                return u.path.lstrip("/")
            if u.path == "/watch":
                q = parse_qs(u.query)
                return q.get("v", [None])[0]
        except (IndexError, TypeError):
            logger.warning(f"Could not parse YouTube ID from src: {src}")
        return None

    def _extract_youtube_videos(self, soup: BeautifulSoup) -> list[dict]:
        ids = []
        for iframe in soup.find_all("iframe"):
            vid = self._extract_youtube_id(iframe.get("src", ""))
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

    def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """Fluxo principal: busca, limpa, extrai conteúdo + imagens/vídeos."""
        html = self._fetch_html(url)
        if not html:
            return None

        try:
            soup = BeautifulSoup(html, 'lxml')

            # 1) limpeza prévia pesada
            self._pre_clean_html(soup)

            # 2) normaliza data-img-url -> <figure>
            self._convert_data_img_to_figure(soup)

            # 3) imagens do HTML limpo (somente corpo)
            pre_images = collect_images_from_article(soup, base_url=url)

            # 4) destacada
            featured_image_url = self._extract_featured_image(soup, url)

            # 5) vídeos
            videos = self._extract_youtube_videos(soup)

            # 6) metadados
            title = soup.title.string if soup.title else 'No Title Found'
            if og_title := soup.find('meta', property='og:title'):
                if og_title.get('content'):
                    title = og_title['content']
            excerpt = ''
            if meta_desc := soup.find('meta', attrs={'name': 'description'}):
                excerpt = meta_desc.get('content') or ''
            elif og_desc := soup.find('meta', property='og:description'):
                excerpt = og_desc.get('content') or ''

            # 7) extrair corpo com trafilatura
            cleaned_html_str = str(soup)
            content_html = trafilatura.extract(
                cleaned_html_str,
                include_images=True,
                include_links=True,
                include_comments=False,
                include_tables=False,
                output_format='html'
            )
            if not content_html:
                logger.warning(f"Trafilatura returned empty content for {url}")
                return None

            # 8) pós-processar corpo
            article_soup = BeautifulSoup(content_html, 'lxml')
            self._remove_forbidden_blocks(article_soup)

            # 9) imagens pós-trafilatura (ainda restritas ao corpo retornado)
            post_images = collect_images_from_article(article_soup, base_url=url)

            # 10) merge dedup
            seen, all_image_urls = set(), []
            for u in pre_images + post_images:
                if u not in seen:
                    seen.add(u)
                    all_image_urls.append(u)

            logger.info(f"Collected {len(all_image_urls)} images from article (pre+post).")

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
                "images": all_image_urls,
                "videos": videos,
                "source_url": url,
            }
            logger.info(f"Successfully extracted and cleaned content from {url}. Title: {result['title'][:50]}...")
            return result

        except Exception as e:
            logger.error(f"An unexpected error occurred during extraction for {url}: {e}", exc_info=True)
            return None
