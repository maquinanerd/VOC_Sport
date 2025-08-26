import os
from dotenv import load_dotenv
from typing import Dict, List, Any

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

PIPELINE_ORDER: List[str] = [
    # Ordem de processamento dos feeds de notícias
    'estadao_politica',
    'infomoney_politica',
    'estadao_economia',
    'infomoney_economia',
    'estadao_brasil',
    'infomoney_mercados',
    'infomoney_investir',
    'infomoney_mundo',
]

RSS_FEEDS: Dict[str, Dict[str, Any]] = {
    'estadao_politica': {
        'urls': ['https://www.estadao.com.br/rss/politica.xml'],
        'category': 'politica',
        'source_name': 'Estadão',
        'synthetic_from': {
            'list_url': 'https://www.estadao.com.br/politica/',
            'selectors': ['article h3 a', 'h3 a', 'article a'],
            'limit': 12,
        }
    },
    'infomoney_politica':   {'urls': ['https://www.infomoney.com.br/politica/feed/'], 'category': 'politica', 'source_name': 'InfoMoney'},
    'estadao_economia': {
        'urls': ['https://www.estadao.com.br/rss/economia.xml'],
        'category': 'economia',
        'source_name': 'Estadão',
        'synthetic_from': {
            'list_url': 'https://www.estadao.com.br/economia/',
            'selectors': ['article h3 a', 'h3 a', 'article a'],
            'limit': 12,
        }
    },
    'infomoney_economia':   {'urls': ['https://www.infomoney.com.br/economia/feed/'], 'category': 'economia', 'source_name': 'InfoMoney'},
    'estadao_brasil': {
        'urls': ['https://www.estadao.com.br/rss/brasil.xml'],
        'category': 'politica',
        'source_name': 'Estadão',
        'synthetic_from': {
            'list_url': 'https://www.estadao.com.br/brasil/',
            'selectors': ['article h3 a', 'h3 a', 'article a'],
            'limit': 12,
        }
    },
    'infomoney_mercados':   {'urls': ['https://www.infomoney.com.br/mercados/feed/'], 'category': 'mercados', 'source_name': 'InfoMoney'},
    'infomoney_investir':   {'urls': ['https://www.infomoney.com.br/onde-investir/feed/'], 'category': 'onde-investir', 'source_name': 'InfoMoney'},
    'infomoney_mundo':      {'urls': ['https://www.infomoney.com.br/mundo/feed/'], 'category': 'internacional', 'source_name': 'InfoMoney'},
}

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# --- Configuração da IA ---
def _load_ai_keys() -> Dict[str, List[str]]:
    """
    Helper to load Gemini API keys from environment variables.
    Categories are discovered dynamically from key names (e.g., GEMINI_ECONOMIA_1, GEMINI_ONDE_INVESTIR_1).
    As categorias devem corresponder às definidas em RSS_FEEDS (ex: 'politica', 'onde-investir').
    """
    keys_by_category: Dict[str, List[str]] = {}
    for key, value in os.environ.items():
        if value and key.startswith('GEMINI_'):
            # e.g., GEMINI_ONDE_INVESTIR_1 -> onde-investir
            parts = key.split('_')
            if len(parts) >= 3:  # Must have at least GEMINI, CATEGORY..., NUMBER
                # The category is everything between GEMINI_ and the last part (_1, _2, etc.)
                category_parts = parts[1:-1]
                category = "-".join(category_parts).lower().replace('__', '_') # Joins with hyphen, allows single underscore
                if category in keys_by_category:
                    keys_by_category[category].append(value)
                else:
                    keys_by_category[category] = [value]
    return keys_by_category

AI_CONFIG = _load_ai_keys()

# Caminho para o prompt universal na raiz do projeto
PROMPT_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'universal_prompt.txt')

AI_MODELS = {
    'primary': os.getenv('AI_PRIMARY_MODEL', 'gemini-1.5-flash-latest'),
    'fallback': os.getenv('AI_FALLBACK_MODEL', 'gemini-1.5-flash-latest'),
}

AI_GENERATION_CONFIG = {
    'temperature': 0.7,
    'top_p': 1.0,
    'max_output_tokens': 4096,
}

# --- Configuração do WordPress ---
WORDPRESS_CONFIG = {
    'url': os.getenv('WORDPRESS_URL'),
    'user': os.getenv('WORDPRESS_USER'),
    'password': os.getenv('WORDPRESS_PASSWORD')
}

WORDPRESS_CATEGORIES: Dict[str, int] = {
    # Mapeamento de categorias para IDs do WordPress
    'politica': 21,
    'economia': 22,
    'mercados': 26,
    'onde-investir': 29,
    'internacional': 30,
    # Categorias genéricas
    'Notícias': 1, 'Dinheiro': 13,
}

# --- Configuração do Agendador e Pipeline ---
SCHEDULE_CONFIG = {
    'check_interval_minutes': int(os.getenv('CHECK_INTERVAL_MINUTES', 15)),
    'max_articles_per_feed': int(os.getenv('MAX_ARTICLES_PER_FEED', 3)),
    'per_article_delay_seconds': int(os.getenv('PER_ARTICLE_DELAY_SECONDS', 8)),
    'per_feed_delay_seconds': int(os.getenv('PER_FEED_DELAY_SECONDS', 15)),
    'cleanup_after_hours': int(os.getenv('CLEANUP_AFTER_HOURS', 72))
}

PIPELINE_CONFIG = {
    'images_mode': os.getenv('IMAGES_MODE', 'hotlink'),  # 'hotlink' ou 'download_upload'
    'attribution_policy': 'Fonte: {domain}',
    'publisher_name': 'VocMoney',
    'publisher_logo_url': os.getenv('PUBLISHER_LOGO_URL', 'https://exemplo.com/logo.png') # TODO: Atualizar com a URL real do logo
}