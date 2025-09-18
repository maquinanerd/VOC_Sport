import re
import unicodedata
from typing import List, Dict, Tuple, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .wordpress import WordPressClient

logger = logging.getLogger(__name__)

# --- BEGIN: CATEGORY ENGINE (do not duplicate) ---

AI_DRIVEN_CATEGORIES = True
MAX_CATEGORIES = 3
AUTO_CREATE_CATEGORIES = True   # ← troque para False se quiser aprovar manualmente
CATEGORY_PARENTS = {            # slugs dos pais já existentes no WP
    "editorias": "editorias",   # ex.: pai “Editorias”
    "times": "times",           # ex.: pai “Times”
    "competicoes": "competicoes" # ex.: pai “Competições”
}
CATEGORY_DENYLIST = {
    "final", "semifinal", "semi-final", "quartas-de-final",
    "quartas", "oitavas-de-final", "oitavas", "fase-de-grupos", "rodada"
}

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()

def slugify(name: str) -> str:
    s = _norm(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def validate_ai_categories(ai_list: List[Dict], content_html: str) -> List[Tuple[str,str,str]]:
    """
    Retorna lista [(slug, nome, grupo)] já filtrada/ordenada por prioridade.
    """
    if not ai_list: return []
    text = _norm(re.sub("<[^>]+>", " ", content_html or ""))

    # ordenar por prioridade
    prio = {"editorias": 0, "times": 1, "competicoes": 2}
    ai_sorted = sorted(ai_list, key=lambda x: prio.get((x or {}).get("grupo",""), 99))

    picked, seen = [], set()
    for item in ai_sorted:
        nome = (item.get("nome") or "").strip()
        grupo = (item.get("grupo") or "").strip()
        evid = (item.get("evidence") or "").strip()

        if not nome or grupo not in CATEGORY_PARENTS:
            continue
        if slugify(nome) in CATEGORY_DENYLIST:
            continue
        # evidência tem que existir no texto
        if evid and _norm(evid) not in text:
            logger.warning(f"Category '{nome}' discarded. Evidence '{evid}' not in text.")
            continue

        slug = slugify(nome)
        if slug in seen: 
            continue
        seen.add(slug)
        picked.append((slug, nome, grupo))
        if len(picked) >= MAX_CATEGORIES:
            break
    return picked

def ensure_categories(slug_nome_grupo: List[Tuple[str,str,str]], wp_client: 'WordPressClient') -> List[int]:
    """
    Resolve IDs; cria categoria se não existir e AUTO_CREATE_CATEGORIES=True.
    """
    if not slug_nome_grupo:
        return []
    slugs_to_resolve = []
    for slug, nome, grupo in slug_nome_grupo:
        if wp_client.get_category_by_slug(slug):   # já existe
            slugs_to_resolve.append(slug)
            continue
        if AUTO_CREATE_CATEGORIES:
            parent_slug = CATEGORY_PARENTS.get(grupo)
            created_cat = wp_client.create_category(name=nome, slug=slug, parent_slug=parent_slug)
            if created_cat:
                slugs_to_resolve.append(slug)
        # se não criar, simplesmente ignora
    
    # This function is not provided, but it should resolve a list of slugs to a list of IDs.
    # I will implement it in wordpress.py
    return wp_client.resolve_categories_by_slugs(slugs_to_resolve)
# --- END: CATEGORY ENGINE ---