import os
from dotenv import load_dotenv
from typing import Dict, List, Any

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

PIPELINE_ORDER: List[str] = [
    # Ordem de processamento dos feeds de economia e política
    'g1_economia',
    'valor_investe',
    'infomoney_mercados',
    'exame_economia',
    'uol_economia',
    'poder360',
]

RSS_FEEDS: Dict[str, Dict[str, Any]] = {
    'g1_economia':        {'urls': ['https://g1.globo.com/rss/g1/economia/'], 'category': 'economia'},
    'valor_investe':      {'urls': ['https://valorinveste.globo.com/rss/valor-investe'], 'category': 'investimentos'},
    'infomoney_mercados': {'urls': ['https://www.infomoney.com.br/mercados/feed/'], 'category': 'investimentos'},
    'exame_economia':     {'urls': ['https://exame.com/economia/feed/'], 'category': 'economia'},
    'uol_economia':       {'urls': ['http://rss.uol.com.br/feed/economia.xml'], 'category': 'economia'},
    'poder360':           {'urls': ['https://www.poder360.com.br/feed/'], 'category': 'politica'},
}

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# --- Configuração da IA ---
def _load_ai_keys() -> Dict[str, List[str]]:
    """
    Helper to load Gemini API keys from environment variables.
    Categories are discovered dynamically from key names (e.g., GEMINI_ECONOMIA_1).
    """
    keys_by_category: Dict[str, List[str]] = {}
    for key, value in os.environ.items():
        if value and key.startswith('GEMINI_'):
            # e.g., GEMINI_ECONOMIA_1 -> economia
            parts = key.split('_')
            if len(parts) >= 2:
                category = parts[1].lower()
                if category in keys_by_category:
                    keys_by_category[category].append(value)
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
    'Notícias': 1, 'Economia': 10, 'Política': 11, 'Investimentos': 12, 'Dinheiro': 13,
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