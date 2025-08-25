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
