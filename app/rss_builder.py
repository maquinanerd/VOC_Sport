import logging
from datetime import datetime
from typing import Dict, List

import pytz
from feedgen.feed import FeedGenerator

logger = logging.getLogger(__name__)


def build_rss_feed(feed_items: List[Dict], feed_info: Dict) -> str:
    """
    Constrói uma string de feed RSS/XML a partir de uma lista de itens.

    Args:
        feed_items: Lista de dicionários, cada um representando um artigo.
        feed_info: Dicionário com metadados do feed (title, link, description).

    Returns:
        Uma string contendo o feed RSS em formato XML.
    """
    fg = FeedGenerator()
    fg.title(feed_info["title"])
    fg.link(href=feed_info["link"], rel="alternate")
    fg.description(feed_info["description"])
    fg.language("pt-BR")
    fg.lastBuildDate(datetime.now(pytz.utc))

    # Ordena os itens pela data de publicação, do mais novo para o mais antigo
    sorted_items = sorted(feed_items, key=lambda x: x["published"], reverse=True)

    for item in sorted_items:
        try:
            fe = fg.add_entry()
            fe.title(item["title"])
            fe.link(href=item["link"])
            fe.guid(item["guid"], permalink=True)
            fe.description(item["description"][:240] + "...")
            fe.pubDate(item["published"].astimezone(pytz.utc))
            if item.get("category"):
                fe.category(term=item["category"])
        except Exception as e:
            logger.error(f"Erro ao adicionar item ao feed '{item.get('title')}': {e}")
            continue

    logger.info(f"Feed '{feed_info['title']}' construído com {len(fg.entry())} itens.")
    return fg.rss_str(pretty=True).decode("utf-8")