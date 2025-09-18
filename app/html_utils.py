# app/html_utils.py
import re
import logging
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# =========================
# YouTube helpers/normalizer
# =========================

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"
}

def _yt_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host not in YOUTUBE_HOSTS:
            return None
        # /embed/ID
        if u.path.startswith("/embed/"):
            return u.path.split("/")[2].split("?")[0]
        # /shorts/ID
        if u.path.startswith("/shorts/"):
            return u.path.split("/")[2].split("?")[0]
        # youtu.be/ID
        if host.endswith("youtu.be"):
            return u.path.lstrip("/").split("?")[0]
        # /watch?v=ID
        if u.path == "/watch":
            q = parse_qs(u.query)
            return (q.get("v") or [None])[0]
    except Exception:
        pass
    return None


def strip_credits_and_normalize_youtube(html: str) -> str:
    """
    - Remove linhas de crédito (figcaption/p/span iniciando com Crédito/Credito/Fonte)
    - Converte iframes do YouTube em <p> com URL watch (WordPress oEmbed)
    - Remove iframes não-YouTube, vazios ou com placeholders (ex.: URL_DO_EMBED_AQUI)
    - Remove <p> vazios após a limpeza e desfaz <figure> que só envolvem embed
    """
    if not html:
        return html

    soup = BeautifulSoup(html, "lxml")

    # 1) Remover “Crédito:”, “Credito:”, “Fonte:”
    for node in soup.find_all(["figcaption", "p", "span"]):
        t = (node.get_text() or "").strip().lower()
        if t.startswith(("crédito:", "credito:", "fonte:")):
            node.decompose()

    # 2) Tratar iframes
    for iframe in list(soup.find_all("iframe")):
        src = (iframe.get("src") or "").strip()
        # placeholder ou vazio? remover
        if (not src) or ("URL_DO_EMBED_AQUI" in src):
            iframe.decompose()
            continue
        # YouTube -> URL watch
        vid = _yt_id_from_url(src)
        if vid:
            p = soup.new_tag("p")
            p.string = f"https://www.youtube.com/watch?v={vid}"
            iframe.replace_with(p)
        else:
            # não-YouTube -> remove
            iframe.decompose()

    # 3) Limpar <figure> que só envolvem o embed ou ficaram vazias
    for fig in list(soup.find_all("figure")):
        if fig.find("img"):
            continue
        children_tags = [c for c in fig.contents if getattr(c, "name", None)]
        only_p = (len(children_tags) == 1 and getattr(children_tags[0], "name", None) == "p")
        p = children_tags[0] if only_p else None
        p_text = (p.get_text().strip() if p else "")
        if only_p and ("youtube.com/watch" in p_text or "youtu.be/" in p_text):
            fig.replace_with(p)
        elif not fig.get_text(strip=True):
            fig.unwrap()

    # 4) Remover <p> vazios (sem texto e sem elementos)
    for p in list(soup.find_all("p")):
        if not p.get_text(strip=True) and not p.find(True):
            p.decompose()

    return soup.body.decode_contents() if soup.body else str(soup)


def hard_filter_forbidden_html(html: str) -> str:
    """
    Sanitiza HTML:
      - remove: script, style, noscript, form, input, button, select, option,
                textarea, object, embed, svg, canvas, link, meta
      - iframes: permite só YouTube (vira oEmbed); remove vazios/placeholder
      - remove atributos on* e href/src com javascript:
      - remove <p> vazios após limpeza
    """
    if not html:
        return html

    soup = BeautifulSoup(html, "lxml")

    REMOVE_TAGS = {
        "script","style","noscript","form","input","button","select","option",
        "textarea","object","embed","svg","canvas","link","meta"
    }
    for tag_name in REMOVE_TAGS:
        for t in soup.find_all(tag_name):
            t.decompose()

    # iframes
    for iframe in list(soup.find_all("iframe")):
        src = (iframe.get("src") or "").strip()
        if (not src) or ("URL_DO_EMBED_AQUI" in src):
            iframe.decompose()
            continue
        vid = _yt_id_from_url(src)
        if vid:
            p = soup.new_tag("p")
            p.string = f"https://www.youtube.com/watch?v={vid}"
            iframe.replace_with(p)
        else:
            iframe.decompose()

    # atributos perigosos
    for el in soup.find_all(True):
        for attr in list(el.attrs.keys()):
            if attr.lower().startswith("on"):
                del el.attrs[attr]
        for attr in ("href", "src"):
            if el.has_attr(attr):
                val = (el.get(attr) or "").strip()
                if val.lower().startswith("javascript:"):
                    del el.attrs[attr]

    # <p> vazios
    for p in list(soup.find_all("p")):
        if not p.get_text(strip=True) and not p.find(True):
            p.decompose()

    return soup.body.decode_contents() if soup.body else str(soup)


# =========================
# Imagens: merge e rewrite
# =========================

def _norm_key(u: str) -> str:
    """Normaliza URL para comparação/chave de dicionário."""
    if not u:
        return ""
    return (u.strip().rstrip("/")).lower()


def _replace_in_srcset(srcset: str, mapping: Dict[str, str]) -> str:
    """
    Substitui URLs dentro de um atributo srcset usando o mapping (url_original -> nova_url).
    Mantém os sufixos (ex.: '320w').
    """
    if not srcset:
        return srcset
    parts = []
    for chunk in srcset.split(","):
        item = chunk.strip()
        if not item:
            continue
        tokens = item.split()
        url = tokens[0]
        rest = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        new_url = mapping.get(_norm_key(url), url)
        parts.append((new_url + (" " + rest if rest else "")).strip())
    return ", ".join(parts)


# --- New Lance-specific helpers ---
LANCE_KILL_TEXTS = [
    r'\bRelacionad[oa]s?\b', r'\bFique por dentro\b', r'\bMais notícias\b',
    r'\bÚltimas notícias\b', r'\bLeia também\b', r'\bVeja também\b',
    r'\bVer mais notícias\b', r'\bTudo sobre\b', r'\bSiga o Lance!\b'
]
LANCE_KILL_SELECTORS = [
    # containers de navegação/rodapé/sidebars/carrosséis
    'nav', 'aside', 'footer',
    '[class*="swiper"]', '[class*="carousel"]', '[class*="carrossel"]',
    '[class*="related"]', '[class*="relacionad"]',
    '[class*="mais-noticias"]', '[data-qa*="related"]', '[aria-label*="Relacionad"]'
]

def _is_lance(url: str) -> bool:
    return 'lance.com.br' in (url or '')

def remove_lance_widgets(soup: BeautifulSoup) -> None:
    # 1) remove por seletor
    for sel in LANCE_KILL_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # 2) remove por texto-sentinela
    rx = re.compile('|'.join(LANCE_KILL_TEXTS), flags=re.I)
    # Iterate over a copy of the list, as we are modifying the tree
    for txt in list(soup.find_all(string=rx)):
        from bs4 import Tag
        # Defensive check for parent attribute, as reported in logs
        if not hasattr(txt, 'parent') or not txt.parent:
            continue
        node = txt.parent

        kill = node
        for _ in range(5):
            if not kill or not isinstance(kill, Tag) or kill.name in ('body', 'main', 'article'):
                break
            if len(kill.find_all('a')) >= 3 or len(kill.find_all('img')) >= 2:
                kill.decompose()
                break
            kill = kill.parent

def strip_lance_cdn(url: str) -> str:
    if not url:
        return url
    return re.sub(
        r'^(https://lncimg\.lance\.com\.br)/cdn-cgi/image/[^/]+/(uploads/.*)$',
        r'\1/\2',
        url
    )

def merge_images_into_content(content_html: str, image_urls: List[str], max_images: int = 6) -> str:
    """
    Garante imagens no corpo:
      - mantém as que já existem
      - injeta até `max_images` novas (que não estejam no HTML)
      - não adiciona créditos/legendas
      - insere após o primeiro parágrafo; se não houver, ao final
    """
    if not content_html:
        content_html = ""
    soup = BeautifulSoup(content_html, "lxml")

    # conjunto de URLs já presentes
    present: set[str] = set()
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if src:
            present.add(_norm_key(src))
        # considerar srcset como presença também
        if img.get("srcset"):
            for chunk in img["srcset"].split(","):
                u = chunk.strip().split()[0]
                if u:
                    present.add(_norm_key(u))

    to_add: List[str] = []
    for u in (image_urls or []):
        key = _norm_key(u)
        if not key or key in present:
            continue
        to_add.append(u)
        if len(to_add) >= max_images:
            break

    if to_add:
        # ponto de inserção: após o primeiro <p>; senão, ao final do body/raiz
        insertion_point = soup.find("p")
        parent = insertion_point.parent if insertion_point and insertion_point.parent else (soup.body or soup)

        for u in to_add:
            fig = soup.new_tag("figure")
            img = soup.new_tag("img", src=u)
            fig.append(img)
            if insertion_point:
                insertion_point.insert_after(fig)
                insertion_point = fig  # próximo entra depois do que inserimos
            else:
                parent.append(fig)

    return soup.body.decode_contents() if soup.body else str(soup)


def rewrite_img_srcs_with_wp(content_html: str, uploaded_src_map: Dict[str, str]) -> str:
    """
    Reaponta <img> e srcset para as URLs do WordPress já enviadas.
    - uploaded_src_map: {url_original (normalizada) -> new_source_url_no_wp}
    """
    if not content_html or not uploaded_src_map:
        return content_html

    # normalizar chaves do mapping
    norm_map: Dict[str, str] = {_norm_key(k): v for k, v in uploaded_src_map.items() if k and v}

    soup = BeautifulSoup(content_html, "lxml")
    for img in soup.find_all("img"):
        # src
        src = (img.get("src") or "").strip()
        key = _norm_key(src)
        if key in norm_map:
            img["src"] = norm_map[key]

        # srcset
        if img.get("srcset"):
            img["srcset"] = _replace_in_srcset(img["srcset"], norm_map)

        # data-* (evita rehydration quebrado)
        for a in ("data-src", "data-original", "data-lazy-src", "data-image", "data-img-url"):
            if img.has_attr(a):
                k2 = _norm_key(img.get(a) or "")
                if k2 in norm_map:
                    img[a] = norm_map[k2]

    return soup.body.decode_contents() if soup.body else str(soup)

# --- Stub para compatibilidade com pipeline: não adiciona crédito nenhum ---
from typing import Optional

def add_credit_to_figures(html: str, source_url: Optional[str] = None) -> str:
    """
    Compat: função mantida apenas para evitar ImportError.
    Não faz nada e retorna o HTML intacto (sem créditos).
    """
    logger.info("add_credit_to_figures desabilitada: retornando HTML sem alterações.")
    return html

# =========================
# Post-AI Defensive Cleanup
# =========================

def remove_broken_image_placeholders(html: str) -> str:
    """
    Removes text-based image placeholders that the AI might mistakenly add,
    like '[Imagem Destacada]' on its own line, without affecting real content.
    """
    if not html or "Imagem" not in html:
        return html
    # This regex targets lines that ONLY contain the placeholder.
    # `^` and `$` anchor to the start and end of a line due to MULTILINE flag.
    # It avoids touching legitimate text that happens to contain the word "Imagem".
    return re.sub(
        r'^\s*(\[?Imagem[^\n<]*\]?)\s*$',
        '',
        html,
        flags=re.IGNORECASE | re.MULTILINE
    )


def strip_naked_internal_links(html: str) -> str:
    """
    Removes paragraphs that contain nothing but a bare URL to an internal
    tag or category page, a common AI formatting error.
    """
    if not html or ("/tag/" not in html and "/categoria/" not in html):
        return html
    # This regex looks for a <p> tag containing only a URL to /tag/ or /categoria/.
    return re.sub(
        r'<p>\s*https?://[^<>\s]+/(?:tag|categoria)/[a-z0-9\-_/]+/?\s*</p>',
        '',
        html,
        flags=re.IGNORECASE
    )

def _first_from_srcset(srcset: str) -> str:
    """Pega a primeira URL de um atributo srcset."""
    if not srcset:
        return ""
    first = srcset.split(",")[0].strip()
    return first.split(" ")[0].strip()

def _best_img_src(tag) -> str:
    """Extrai a melhor URL de imagem de uma tag, testando múltiplos atributos."""
    if not tag or not hasattr(tag, "get"):
        return ""
    # Ordem de preferência para lazy-load e fontes padrão
    for attr in ("data-src", "data-lazy-src", "data-original", "src"):
        val = (tag.get(attr) or "").strip()
        if val:
            return val
    # Fallback para srcset
    srcset = (tag.get("data-srcset") or tag.get("srcset") or "").strip()
    if srcset:
        return _first_from_srcset(srcset)
    return ""

TWEET_URL_RE = re.compile(r"https?://(twitter|x)\.com/.+?/status/\d+", re.I)

def convert_twitter_embeds_to_oembed(root: BeautifulSoup):
    """
    Converte `blockquote.twitter-tweet` em parágrafos com a URL do tweet,
    permitindo que o oEmbed do WordPress funcione.
    """
    # 1) blockquote.twitter-tweet -> <p>URL</p>
    for bq in root.select("blockquote.twitter-tweet"):
        link = bq.find("a", href=TWEET_URL_RE)
        if not link:
            link = next((a for a in bq.find_all("a") if TWEET_URL_RE.search(a.get("href",""))), None)
        
        if link and link.get("href"):
            url = link.get("href")
            # Cria um novo <p> e substitui o blockquote
            # Use .soup to access the BeautifulSoup instance from a Tag or from itself.
            new_p = root.soup.new_tag("p")
            new_p.string = url
            parent = bq.parent
            if parent:
                bq.replace_with(new_p)


def normalize_images_with_captions(html: str, *, source_url: str = "") -> str:
    """
    Ensures images are wrapped in <figure> and attempts to find and standardize
    a <figcaption> with a caption and credit.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    is_lance_source = _is_lance(source_url)
    if is_lance_source:
        remove_lance_widgets(soup)

    BAD_HOSTS = ("video.glbimg.com", "s01.video.glbimg.com", "s02.video.glbimg.com", "s01.video.globo.com")
    CAPTION_SELECTORS = [
        "figcaption",
        ".content-media__legend", ".content-media__caption", ".foto__legenda", ".foto-legenda",
        ".media-caption", ".credits", ".credito", ".legenda"
    ]

    seen_images = set()
    # Itera sobre potenciais contêineres de imagem para ser mais robusto
    for container in list(soup.select('figure, picture, img')):
        try:
            if is_lance_source:
                if container.find_parent(['nav','aside','footer']):
                    container.decompose()
                    continue
                if any(c for c in (container.get('class') or []) if re.search(r'(card|carousel|relacionad|mais-noticia|swiper)', c, re.I)):
                    container.decompose()
                    continue
                if re.search(r'(Relacionad|Fique por dentro|Mais notícias|Veja mais notícias)', container.get_text(' ', strip=True), re.I):
                    container.decompose()
                    continue

            # Lógica robusta para extrair o src da imagem
            img = container if container.name == 'img' else container.find("img")
            if not img or not isinstance(img, Tag):
                continue

            if is_lance_source and img.find_parent(['nav','aside','footer']):
                container.decompose()
                continue

            src = _best_img_src(img)

            if not src: # Fallback para <picture> sem <img> ou background-image
                source_tag = container.find("source")
                src = _best_img_src(source_tag)

            # Deduplicação de imagens (ignora transformações de CDN)
            if src:
                if is_lance_source:
                    src = strip_lance_cdn(src)
                    if 'lncimg.lance.com.br' in src and '/uploads/' not in src:
                        container.decompose()
                        continue

                if re.search(r'/(assets|attachments|favicon|logo|icon|sprite)/', src):
                    container.decompose()
                    continue

                img['src'] = src

                key = src
                if '/uploads/' in src:
                    key = src.split('/uploads/', 1)[-1]
                
                if key in seen_images:
                    container.decompose()
                    continue
                seen_images.add(key)
            
            # Filtros anti-lixo (logos, ícones, etc.)
            bad_parts = ("Ultimas-noticias.png", "/icons/", "/favicon", "/sprites", "/ads/")
            if any(p in src for p in bad_parts):
                # Decompose the container if it's a junk image
                container.decompose()
                continue

            if not src and container.get("style") and "background-image" in container.get("style"):
                style = container.get("style", "")
                m = re.search(r"url\(([^)]+)\)", style)
                if m:
                    src = m.group(1).strip('"\'')

            if not src:
                logger.debug("Skipping image container without a valid src/srcset.")
                continue

            if any(h in src for h in BAD_HOSTS):
                container.decompose()
                continue

            # Garante que temos uma tag <img> para trabalhar
            if not img:
                img = soup.new_tag("img", src=src)
                container.append(img)

            # Garante que a imagem esteja dentro de uma <figure>
            figure = container if container.name == 'figure' else container.find_parent('figure')
            if not figure:
                figure = soup.new_tag("figure")
                container.replace_with(figure)
                figure.append(container)

            # Lógica de extração de legenda e crédito (mantida)
            caption_text = ""
            # 1. Tenta figcaption
            if fig_cap := figure.find("figcaption"):
                caption_text = re.sub(r"\s+", " ", fig_cap.get_text(" ", strip=True))
            
            # 2. Tenta alt/aria-label da imagem
            if not caption_text and img:
                caption_text = (img.get("alt") or img.get("aria-label") or "").strip()

            # 3. Tenta irmão com classe/texto de legenda/crédito
            if not caption_text:
                sib_check_node = figure or container
                if sib := sib_check_node.find_next_sibling(["p", "span"]):
                    stext = " ".join(sib.get("class", [])).lower() + " " + sib.get_text(" ", strip=True).lower()
                    if "legenda" in stext or "crédito" in stext or "credito" in stext:
                        caption_text = re.sub(r"\s+", " ", sib.get_text(" ", strip=True))
                        sib.decompose() # Remove o irmão, pois a legenda foi absorvida

            # 4. Fallback obrigatório
            if not caption_text:
                caption_text = "Foto: Lance!"

            credit_match = re.search(r"(.*?)(—\s*(?:Foto|Crédito):.*)", caption_text, flags=re.I) # Separa crédito
            if credit_match:
                caption_text = credit_match.group(1).strip()
                credit_text = credit_match.group(2).strip()
            else:
                credit_match = re.search(r"((?:Foto|Crédito):.*)", caption_text, flags=re.I)
                if credit_match:
                    credit_text = credit_match.group(1).strip()
                    caption_text = caption_text.replace(credit_text, "").strip()

            # Garante que a tag img tenha o alt text preenchido
            if img:
                img['alt'] = caption_text.strip()

            # Reconstrói o figcaption para garantir padronização
            for old_cap in figure.find_all("figcaption"): old_cap.decompose()
            figcap = soup.new_tag("figcaption")
            figcap.string = caption_text.strip()
            figure.append(figcap)

        except Exception as e:
            logger.warning(f"Error normalizing an image container: {e}. Skipping.", exc_info=False)
            continue

    return str(soup)

def collapse_h2_headings(html: str, keep_first: int = 1) -> str:
    """Converts all <h2> tags after the first 'keep_first' into <p><strong>...</strong></p>."""
    if not html: return html
    soup = BeautifulSoup(html, "lxml")
    for idx, h2 in enumerate(soup.find_all("h2")):
        if idx >= keep_first:
            p_tag = soup.new_tag("p")
            strong_tag = soup.new_tag("strong")
            strong_tag.string = h2.get_text(" ", strip=True)
            p_tag.append(strong_tag)
            h2.replace_with(p_tag)
    return str(soup)
