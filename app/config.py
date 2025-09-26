import os
from dotenv import load_dotenv
from typing import Dict, List, Any
from collections import defaultdict
from urllib.parse import urlparse

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

# --- Ordem de processamento dos feeds ---
PIPELINE_ORDER: List[str] = [
    'lance_futebol',
    'globo_futebol',
    'globo_futebol_internacional',
]

# --- Feeds RSS ---
# As URLs são carregadas das variáveis de ambiente (FEED_1, FEED_2, etc.)
RSS_FEEDS: Dict[str, Dict[str, Any]] = {
    'lance_futebol': {
        'urls': ['https://aprenderpoker.site/feeds/lance/futebol/rss'],
        'category': 'futebol',
        'source_name': 'Lance!',
    },
    'globo_futebol': {
        'urls': [os.getenv('FEED_2', '')],
        'category': 'futebol',
        'source_name': 'Globo Esporte',
    },
    'globo_futebol_internacional': {
        'urls': [os.getenv('FEED_3', '')],
        'category': 'futebol',
        'source_name': 'Globo Esporte (Internacional)',
    },
}

# --- HTTP ---
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/91.0.4472.124 Safari/537.36'
)

# --- Configuração da IA ---
def _load_ai_keys() -> Dict[str, List[str]]:
    """
    Lê todas as chaves GEMINI_* do ambiente e as agrupa por categoria.
    Ex: GEMINI_FUTEBOL_1 -> {'futebol': ['key1', ...]}
    """
    keys_by_category = defaultdict(dict)
    for key, value in os.environ.items():
        if value and key.startswith('GEMINI_'):
            parts = key.split('_')
            if len(parts) >= 3 and parts[0] == 'GEMINI':
                category = parts[1].lower()
                keys_by_category[category][key] = value

    # Sort keys within each category and return just the values
    sorted_keys = {}
    for category, keys_dict in keys_by_category.items():
        sorted_key_names = sorted(keys_dict.keys())
        sorted_keys[category] = [keys_dict[k] for k in sorted_key_names]

    return sorted_keys

# AI_API_KEYS é um dicionário que mapeia categorias (ex: 'futebol') para uma lista de chaves.
AI_API_KEYS = _load_ai_keys()

# Caminho para o prompt universal na raiz do projeto
PROMPT_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..',
    'universal_prompt.txt'
)

AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash")

AI_GENERATION_CONFIG = {
    'temperature': 0.7,
    'top_p': 1.0,
    'max_output_tokens': 4096,
}

# --- WordPress ---
WORDPRESS_CONFIG = {
    'url': os.getenv('WORDPRESS_URL'),
    'user': os.getenv('WORDPRESS_USER'),
    'password': os.getenv('WORDPRESS_PASSWORD'),
}

# IDs das categorias no WordPress (ajuste os IDs conforme o seu WP)
WORDPRESS_CATEGORIES: Dict[str, int] = {
    'futebol': 1,  # TODO: Atualizar com o ID correto da categoria "Futebol" no WordPress
    # Categorias genéricas
    'Notícias': 1, # Geralmente ID 1 é "Uncategorized", mas pode ser usado como fallback
}

# --- Agendador / Pipeline ---
SCHEDULE_CONFIG = {
    'check_interval_minutes': int(os.getenv('CHECK_INTERVAL_MINUTES', 5)),
    'max_articles_per_feed': int(os.getenv('MAX_ARTICLES_PER_FEED', 10)),
    'per_article_delay_seconds': int(os.getenv('PER_ARTICLE_DELAY_SECONDS', 8)),
    'per_feed_delay_seconds': int(os.getenv('PER_FEED_DELAY_SECONDS', 15)),
    'cleanup_after_hours': int(os.getenv('CLEANUP_AFTER_HOURS', 72)),
}

def _get_domain_from_wp_url(wp_url: str) -> str:
    """Extrai o domínio base (ex: thesport.news/br) da URL do WordPress."""
    if not wp_url:
        return "example.com"  # Fallback
    try:
        # Ex: https://thesport.news/br/wp-json/wp/v2/ -> thesport.news/br
        p = urlparse(wp_url)
        # Pega o netloc (ex: thesport.news) e a parte do path antes de /wp-json/ (ex: /br)
        base_path = p.path.split('/wp-json/')[0]
        domain = p.netloc + base_path.rstrip('/')
        return domain
    except Exception:
        return "example.com"

PIPELINE_CONFIG = {
    'domain': _get_domain_from_wp_url(os.getenv('WORDPRESS_URL')),
    'images_mode': os.getenv('IMAGES_MODE', 'hotlink'),  # 'hotlink' ou 'download_upload'
    'attribution_policy': 'Fonte: {domain}',
    'publisher_name': 'The Sport',
    'publisher_logo_url': os.getenv(
        'PUBLISHER_LOGO_URL',
        'https://thesport.news/br/wp-content/uploads/2024/05/logo-corneta-fc-512.png' # TODO: Verificar se este caminho de logo é válido
    ),
}
