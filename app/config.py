import os
from dotenv import load_dotenv
from typing import Dict, List, Any

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

# --- Ordem de processamento dos feeds ---
PIPELINE_ORDER: List[str] = [
    'estadao_politica',
    'infomoney_politica',
    'estadao_economia',
    'infomoney_economia',
    'infomoney_business',
    'estadao_brasil',
    'infomoney_mercados',
    'infomoney_investir',
    'infomoney_mundo',
    'infomoney_carreira',
]

# --- Feeds RSS (padronizados, sem "synthetic_from") ---
RSS_FEEDS: Dict[str, Dict[str, Any]] = {
    'estadao_politica': {
        'urls': ['https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/'],
        'category': 'politica',
        'source_name': 'Estadão',
    },
    'infomoney_politica': {
        'urls': ['https://www.infomoney.com.br/politica/feed/'],
        'category': 'politica',
        'source_name': 'InfoMoney',
    },

    'estadao_economia': {
        'urls': ['https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/economia/'],
        'category': 'economia',
        'source_name': 'Estadão',
    },
    'infomoney_economia': {
        'urls': ['https://www.infomoney.com.br/economia/feed/'],
        'category': 'economia',
        'source_name': 'InfoMoney',
    },

    'estadao_brasil': {
        'urls': ['https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/brasil/'],
        'category': 'brasil',
        'source_name': 'Estadão',
    },
    'infomoney_mercados': {
        'urls': ['https://www.infomoney.com.br/mercados/feed/'],
        'category': 'mercados',
        'source_name': 'InfoMoney',
    },
    'infomoney_business': {
        'urls': ['https://www.infomoney.com.br/business/feed/'],
        'category': 'economia',
        'source_name': 'InfoMoney',
    },
    'infomoney_investir': {
        'urls': ['https://www.infomoney.com.br/onde-investir/feed/'],
        'category': 'onde-investir',
        'source_name': 'InfoMoney',
    },
    'infomoney_mundo': {
        'urls': ['https://www.infomoney.com.br/mundo/feed/'],
        'category': 'internacional',
        'source_name': 'InfoMoney',
    },
    'infomoney_carreira': {
        'urls': ['https://www.infomoney.com.br/carreira/feed/'],
        'category': 'carreira',
        'source_name': 'InfoMoney',
    },
}

# --- HTTP ---
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/91.0.4472.124 Safari/537.36'
)

# --- Configuração da IA ---
def _load_ai_keys() -> List[str]:
    """
    Lê todas as chaves GEMINI_* do ambiente e as retorna em uma lista única e ordenada.
    """
    keys = {}
    for key, value in os.environ.items():
        if value and key.startswith('GEMINI_'):
            keys[key] = value
    
    # Sort by key name for predictable order (e.g., GEMINI_ECONOMIA_1, GEMINI_POLITICA_1)
    sorted_key_names = sorted(keys.keys())
    
    return [keys[k] for k in sorted_key_names]

AI_API_KEYS = _load_ai_keys()

# Caminho para o prompt universal na raiz do projeto
PROMPT_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..',
    'universal_prompt.txt'
)

AI_MODELS = {
    'primary': os.getenv('AI_PRIMARY_MODEL', 'gemini-1.5-flash-latest'),
    'fallback': os.getenv('AI_FALLBACK_MODEL', 'gemini-1.5-flash-latest'),
}

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
    'politica': 21,
    'economia': 22,
    'brasil': 22,          # TODO: substituir pelo ID real da sua categoria "Brasil"
    'mercados': 26,
    'onde-investir': 29,
    'internacional': 30,
    'carreira': 202,
    # Categorias genéricas
    'Notícias': 1,
    'Dinheiro': 13,
}

# --- Agendador / Pipeline ---
SCHEDULE_CONFIG = {
    'check_interval_minutes': int(os.getenv('CHECK_INTERVAL_MINUTES', 15)),
    'max_articles_per_feed': int(os.getenv('MAX_ARTICLES_PER_FEED', 3)),
    'per_article_delay_seconds': int(os.getenv('PER_ARTICLE_DELAY_SECONDS', 8)),
    'per_feed_delay_seconds': int(os.getenv('PER_FEED_DELAY_SECONDS', 15)),
    'cleanup_after_hours': int(os.getenv('CLEANUP_AFTER_HOURS', 72)),
}

PIPELINE_CONFIG = {
    'images_mode': os.getenv('IMAGES_MODE', 'hotlink'),  # 'hotlink' ou 'download_upload'
    'attribution_policy': 'Fonte: {domain}',
    'publisher_name': 'VocMoney',
    'publisher_logo_url': os.getenv(
        'PUBLISHER_LOGO_URL',
        'https://exemplo.com/logo.png'  # TODO: atualizar para a URL real do logo
    ),
}
