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
# aliases/sinônimos (amplie conforme usar)
TEAM_ALIASES = {
    "palmeiras": ["palmeiras","verdão","verdao"],
    "river-plate": ["river plate","river"],
    "corinthians": ["corinthians", "timão", "timao"],
    "flamengo": ["flamengo", "mengão", "mengao"],
    "sao-paulo": ["são paulo", "sao paulo", "tricolor paulista"],
}
COMP_SYNONYMS = {
    "libertadores": ["libertadores","copa libertadores","taça libertadores","taca libertadores"],
    "sul-americana": ["sul-americana","sul americana","copa sul-americana","copa sul americana"],
    "brasileirao": ["brasileirão","brasileirao","serie a","série a", "campeonato brasileiro"],
    "copa-do-brasil": ["copa do brasil"],
}

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()

def slugify(name: str) -> str:
    s = _norm(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def _contains_any(text_norm: str, phrases: List[str]) -> bool:
    """Verifica se alguma das frases (normalizadas) está no texto (normalizado)."""
    phrases = [p for p in (phrases or []) if p]
    return any(_norm(p) in text_norm for p in phrases)

def _aliases_for(slug: str, nome: str, grupo: str) -> List[str]:
    """Retorna uma lista de nomes e apelidos para uma categoria."""
    if grupo == "competicoes":
        return COMP_SYNONYMS.get(slug, []) + [nome]
    if grupo == "times":
        return TEAM_ALIASES.get(slug, []) + [nome]
    return [nome]

def validate_ai_categories(ai_list: List[Dict], content_html: str, title_text: str) -> List[Tuple[str,str,str]]:
    """
    Aceita categoria se:
      - evidence aparecer no TÍTULO ou CORPO (normalizado), OU
      - nome/aliases/sinônimos aparecerem no TÍTULO ou CORPO.
    Ordena por prioridade (editorias > times > competicoes) e limita a MAX_CATEGORIES.
    """
    if not ai_list: return []
    body_norm  = _norm(re.sub("<[^>]+>"," ", content_html or ""))
    title_norm = _norm(title_text or "")
    text_norm  = f"{title_norm} {body_norm}"

    prio = {"editorias": 0, "times": 1, "competicoes": 2}
    picked, seen = [], set()

    ai_sorted = sorted(ai_list, key=lambda x: prio.get((x or {}).get("grupo",""), 99))

    for item in ai_sorted:
        nome = (item.get("nome") or "").strip()
        grupo = (item.get("grupo") or "").strip()
        evid = (item.get("evidence") or "").strip()

        if not nome or grupo not in CATEGORY_PARENTS:
            continue
        
        slug = slugify(nome)
        if slug in CATEGORY_DENYLIST or slug in seen:
            continue

        evid_ok = bool(evid) and _contains_any(text_norm, [evid])
        name_ok = _contains_any(text_norm, _aliases_for(slug, nome, grupo))

        if not (evid_ok or name_ok):
            logger.debug("Category '%s' discarded. Evidence/alias not found in title or body.", nome)
            continue

        seen.add(slug)
        picked.append((slug, nome, grupo))
        logger.info("Accepted category '%s' via %s", nome, "evidence" if evid_ok else "name/alias")
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