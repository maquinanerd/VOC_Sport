import argparse
import logging
import time
import sys
import schedule

from app.pipeline import run_pipeline_cycle
from app.store import Database
from app.config import SCHEDULE_CONFIG

# Configura o logging para exibir informações no terminal e salvar em um arquivo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log", mode='a', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

def initialize_database():
    """Inicializa o banco de dados e garante que as tabelas sejam criadas."""
    logger.info("Verificando o esquema do banco de dados...")
    try:
        db = Database()
        db.close()
        logger.info("Verificação do banco de dados concluída com sucesso.")
    except Exception as e:
        logger.critical(f"Falha ao inicializar o banco de dados: {e}", exc_info=True)
        sys.exit(1)

def main():
    """Função principal para executar o pipeline de conteúdo."""
    parser = argparse.ArgumentParser(description="Executa o pipeline de conteúdo VocMoney.")
    parser.add_argument(
        '--once',
        action='store_true',
        help="Executa o ciclo do pipeline uma vez e sai."
    )
    args = parser.parse_args()

    initialize_database()

    if args.once:
        logger.info("Executando um único ciclo do pipeline (--once).")
        try:
            run_pipeline_cycle()
        except Exception as e:
            logger.critical(f"Erro crítico durante a execução do ciclo único: {e}", exc_info=True)
        finally:
            logger.info("Ciclo único finalizado.")
    else:
        interval = SCHEDULE_CONFIG.get('check_interval_minutes', 15)
        logger.info(f"Agendador iniciado. O pipeline será executado a cada {interval} minutos.")
        schedule.every(interval).minutes.do(run_pipeline_cycle)
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Agendador interrompido pelo usuário.")
                break
            except Exception as e:
                logger.error(f"Ocorreu um erro inesperado no loop do agendador: {e}", exc_info=True)
                time.sleep(60) # Aguarda um minuto antes de tentar novamente
if __name__ == "__main__":
    main()

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
