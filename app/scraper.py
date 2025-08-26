import logging
import re
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

import pytz
import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; PythonNewsScraper/1.0; +https://github.com/)"
TIMEZONE = pytz.timezone("America/Sao_Paulo")


def parse_relative_date_pt(date_str: str) -> Optional[datetime]:
    """Converte datas relativas em português (ex: 'há 2 horas') para datetime."""
    now = datetime.now(TIMEZONE)
    date_str = date_str.lower().strip()

    if "agora" in date_str or "neste momento" in date_str:
        return now

    match = re.search(r"(\d+)\s+minuto", date_str)
    if match:
        return now - timedelta(minutes=int(match.group(1)))

    match = re.search(r"(\d+)\s+hora", date_str)
    if match:
        return now - timedelta(hours=int(match.group(1)))

    match = re.search(r"(\d+)\s+dia", date_str)
    if match:
        return now - timedelta(days=int(match.group(1)))

    logger.warning(f"Não foi possível parsear a data relativa: '{date_str}'")
    return None


def scrape_estadao(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Scraper para as páginas de editoria do Estadão."""
    articles = []
    # Seletor principal para a lista de notícias
    container = soup.select_one("section.ultimas-noticias-feed-posts div.posts")
    if not container:
        logger.warning("Container de notícias do Estadão não encontrado.")
        return []

    # Itera sobre cada "card" de notícia
    for card in container.find_all("div", class_="card", limit=40):
        link_tag = card.select_one("a")
        title_tag = card.select_one("h3.title")
        desc_tag = card.select_one("p.description")
        time_tag = card.select_one("div.info > span")

        if not (link_tag and title_tag):
            continue

        link = urljoin(base_url, link_tag.get("href", ""))
        title = title_tag.get_text(strip=True)
        description = desc_tag.get_text(strip=True) if desc_tag else title

        date_str = time_tag.get_text(strip=True) if time_tag else ""
        published_date = parse_relative_date_pt(date_str) or datetime.now(TIMEZONE)

        articles.append({
            "title": title,
            "link": link,
            "description": description,
            "published": published_date,
        })
    return articles


def scrape_exame(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Scraper para as páginas de editoria da Exame."""
    articles = []
    # Seletor para os cards de artigo
    cards = soup.select("article a[href^='/']")
    if not cards:
        logger.warning("Nenhum card de notícia da Exame encontrado.")
        return []

    for card in cards[:40]:
        title_tag = card.select_one("h2, h3")
        desc_tag = card.select_one("p")
        time_tag = card.find_next("time")

        if not (title_tag and card.get("href")):
            continue

        link = urljoin(base_url, card["href"])
        title = title_tag.get_text(strip=True)
        description = desc_tag.get_text(strip=True) if desc_tag else title

        if time_tag and time_tag.get("datetime"):
            from dateutil import parser
            try:
                published_date = parser.parse(time_tag["datetime"]).astimezone(TIMEZONE)
            except parser.ParserError:
                published_date = datetime.now(TIMEZONE)
        else:
            published_date = datetime.now(TIMEZONE)

        articles.append({
            "title": title,
            "link": link,
            "description": description,
            "published": published_date,
        })
    return articles


SCRAPERS: Dict[str, Callable[[BeautifulSoup, str], List[Dict]]] = {
    "estadao": scrape_estadao,
    "exame": scrape_exame,
}


def scrape(source_key: str, url: str) -> List[Dict]:
    """
    Função principal de scraping que busca o HTML e chama o scraper apropriado.

    Args:
        source_key: A chave do site (ex: 'estadao', 'exame').
        url: A URL da página a ser raspada.

    Returns:
        Uma lista de dicionários de artigos extraídos.
    """
    scraper_func = SCRAPERS.get(source_key)
    if not scraper_func:
        raise ValueError(f"Nenhum scraper encontrado para a fonte: {source_key}")

    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        return scraper_func(soup, url)
    except requests.RequestException as e:
        logger.error(f"Falha ao buscar a URL {url}: {e}")
        return []
    except Exception as e:
        logger.error(f"Erro inesperado no scraping de {url}: {e}", exc_info=True)
        return []