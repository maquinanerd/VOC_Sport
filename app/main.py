import argparse
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List

from slugify import slugify

from rss_builder import build_rss_feed
from scraper import TIMEZONE, scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

SOURCES = {
    "estadao-politica": {
        "key": "estadao",
        "url": "https://www.estadao.com.br/politica/",
        "category": "Política",
        "source_name": "Estadão",
    },
    "estadao-economia": {
        "key": "estadao",
        "url": "https://www.estadao.com.br/economia/",
        "category": "Economia",
        "source_name": "Estadão",
    },
    "estadao-brasil": {
        "key": "estadao",
        "url": "https://www.estadao.com.br/brasil/",
        "category": "Brasil",
        "source_name": "Estadão",
    },
    "exame-economia": {
        "key": "exame",
        "url": "https://exame.com/economia/",
        "category": "Economia",
        "source_name": "Exame",
    },
    "exame-brasil": {
        "key": "exame",
        "url": "https://exame.com/brasil/",
        "category": "Política",
        "source_name": "Exame",
    },
}

FEED_DIR = "feeds"
CACHE_FILE = os.path.join(FEED_DIR, ".seen.json")


def load_cache() -> Dict:
    """Carrega o cache de GUIDs de um arquivo JSON."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logging.warning("Não foi possível carregar o cache. Um novo será criado.")
        return {}


def save_cache(cache: Dict):
    """Salva o cache de GUIDs em um arquivo JSON."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
    except IOError as e:
        logging.error(f"Falha ao salvar o cache: {e}")


def process_source(slug: str, config: Dict):
    """Processa uma única fonte: raspa, normaliza, constrói e salva o feed."""
    logging.info(f"Iniciando processamento para a fonte: {slug}")

    # 1. Raspar os artigos da página
    scraped_articles = scrape(config["key"], config["url"])
    if not scraped_articles:
        logging.warning(f"Nenhum artigo raspado para {slug}. Pulando.")
        return

    logging.info(f"Raspados {len(scraped_articles)} artigos de {slug}.")

    # 2. Carregar cache e normalizar itens
    cache = load_cache()
    for item in scraped_articles:
        item["guid"] = hashlib.sha1(item["link"].encode()).hexdigest()
        item["category"] = config["category"]
        item["source_slug"] = slug
        # Adiciona ao cache se for novo
        if item["guid"] not in cache:
            cache[item["guid"]] = item

    # 3. Coletar todos os itens conhecidos para esta fonte e ordenar
    all_known_items = [
        item for item in cache.values() if item.get("source_slug") == slug
    ]
    all_known_items.sort(key=lambda x: x["published"], reverse=True)

    # 4. Limitar aos 30 mais recentes para o feed
    final_feed_items = all_known_items[:30]

    # 5. Construir o feed RSS
    feed_info = {
        "title": f'{config["source_name"]} — {config["category"]} (RSS não-oficial)',
        "link": config["url"],
        "description": f'Feed gerado automaticamente a partir de {config["source_name"]} ({config["category"]}).',
    }
    rss_xml = build_rss_feed(final_feed_items, feed_info)

    # 6. Salvar o arquivo XML
    output_path = os.path.join(FEED_DIR, f"{slug}.xml")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(rss_xml)
        logging.info(f"Feed salvo com sucesso em: {output_path}")
    except IOError as e:
        logging.error(f"Falha ao salvar o arquivo de feed {output_path}: {e}")

    # 7. Salvar o cache atualizado
    save_cache(cache)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gera feeds RSS a partir de páginas de notícias."
    )
    parser.add_argument(
        "--only",
        type=str,
        help="Gera o feed apenas para o slug especificado (ex: estadao-politica).",
        choices=SOURCES.keys(),
    )
    args = parser.parse_args()

    os.makedirs(FEED_DIR, exist_ok=True)

    if args.only:
        if args.only in SOURCES:
            process_source(args.only, SOURCES[args.only])
        else:
            logging.error(f"Slug '{args.only}' não encontrado nas fontes configuradas.")
    else:
        logging.info("Processando todas as fontes configuradas...")
        for slug, config in SOURCES.items():
            process_source(slug, config)
            logging.info("Aguardando 2 segundos antes da próxima fonte...")
            time.sleep(2)

    logging.info("Processo concluído.")