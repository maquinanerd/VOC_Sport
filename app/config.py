import os
from dotenv import load_dotenv
from typing import Dict, List, Any

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

PIPELINE_ORDER = [
    # Ordem de processamento dos feeds
    'screenrant_movies',
    'screenrant_tv',
    'collider_movies',
    'collider_tv',
    'movieweb_movies',
    'cbr_movies',
    'cbr_tv',
    'gamerant_games',
    'thegamer_games',
]

RSS_FEEDS = {
    'screenrant_movies': {'urls': ['https://screenrant.com/feed/movies/'], 'category': 'movies'},
    'screenrant_tv':     {'urls': ['https://screenrant.com/feed/tv/'],    'category': 'series'},
    'movieweb_movies':   {'urls': ['https://movieweb.com/feed/'],               'category': 'movies'},
    'collider_movies':   {'urls': ['https://collider.com/feed/category/movie-news/'], 'category': 'movies'},
    'collider_tv':       {'urls': ['https://collider.com/feed/category/tv-news/'],    'category': 'series'},
    'cbr_movies':        {'urls': ['https://comicbook.com/category/movies/feed/'], 'category': 'movies'},
    'cbr_tv':            {'urls': ['https://comicbook.com/category/tv-shows/feed/'],         'category': 'series'},
    'gamerant_games':    {'urls': ['https://gamerant.com/feed/gaming/'],        'category': 'games'},
    'thegamer_games':    {'urls': ['https://www.thegamer.com/feed/category/game-news/'], 'category': 'games'}
}

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# --- Configuração da IA ---
def _load_ai_keys() -> Dict[str, List[str]]:
    """Helper to load Gemini API keys from environment variables."""
    keys_by_category: Dict[str, List[str]] = {'movies': [], 'series': [], 'games': []}
    for key, value in os.environ.items():
        if value and key.startswith('GEMINI_'):
            # e.g., GEMINI_MOVIES_1 -> movies
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

WORDPRESS_CATEGORIES = {
    'Notícias': 20, 'Filmes': 24, 'Séries': 21, 'Games': 73,
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
    'attribution_policy': 'Via {domain}',
    'publisher_name': 'Máquina Nerd',
    'publisher_logo_url': 'https://www.maquinanerd.com.br/wp-content/uploads/2023/11/logo-maquina-nerd-400px.png'   
}