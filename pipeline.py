import logging
from datetime import datetime, timedelta

from app.config import PIPELINE_ORDER, RSS_FEEDS, SCHEDULE_CONFIG
from app.store import Database
from app.feeds import FeedReader
from app.extractor import ContentExtractor
from app.rewriter import Rewriter
from app.tags import TagGenerator
from app.categorizer import WordPressCategorizer
from app.wordpress import WordPressPublisher
from app.media import MediaHandler
from app.ai_processor import AIProcessor, AllKeysOnCooldownError
from app.key_manager import KeyManager

logger = logging.getLogger(__name__)

def run_pipeline_cycle():
    """
    Executa um ciclo completo do pipeline para um único feed,
    seguindo a ordem de round-robin.
    """
    db = None
    try:
        db = Database()
        
        # 1. Determinar qual feed processar (Round-Robin)
        last_index_str = db.get_pipeline_state('last_processed_feed_index')
        last_index = int(last_index_str) if last_index_str is not None else -1
        
        next_index = (last_index + 1) % len(PIPELINE_ORDER)
        feed_id = PIPELINE_ORDER[next_index]
        feed_config = RSS_FEEDS[feed_id]
        
        logger.info(f"Iniciando ciclo do pipeline para o feed: {feed_id}")

        # Inicializa os componentes do pipeline
        feed_reader = FeedReader(db)
        extractor = ContentExtractor()
        key_manager = KeyManager(db)
        ai_processor = AIProcessor()
        rewriter = Rewriter()
        tag_generator = TagGenerator()
        categorizer = WordPressCategorizer()
        media_handler = MediaHandler()
        publisher = WordPressPublisher(db)

        # 2. Ler o feed e encontrar novos artigos
        new_articles = feed_reader.fetch_and_filter(feed_id, feed_config['urls'])
        
        if not new_articles:
            logger.info(f"Nenhum artigo novo encontrado para {feed_id}.")
            db.set_pipeline_state('last_processed_feed_index', str(next_index))
            return

        logger.info(f"Encontrados {len(new_articles)} novos artigos para {feed_id}.")

        # 3. Processar um número limitado de artigos por ciclo
        articles_to_process = new_articles[:SCHEDULE_CONFIG['max_articles_per_feed']]
        deferred_count = 0

        for article in articles_to_process:
            try:
                logger.info(f"Processando artigo: {article.title} de {feed_id}")

                # 4. Extrair conteúdo
                extracted_data = extractor.extract(article.link)
                if not extracted_data or not extracted_data.get('content'):
                    logger.warning(f"Falha ao extrair conteúdo de {article.link}")
                    continue

                # 5. Gerar Tags
                tags = tag_generator.generate(extracted_data['content'])
                tags_text = ", ".join(tags)

                # 6. Reescrever com IA
                # A chamada foi corrigida para corresponder à assinatura do método
                # e para passar a categoria explicitamente para o prompt.
                rewritten_data, failure_reason = ai_processor.rewrite_content(
                    title=article.title,
                    content_html=extracted_data['content'],
                    source_url=article.link,
                    category=feed_config['category'],
                    tags=tags,
                    domain=publisher.domain,
                    source_name=feed_config.get('source_name', ''),
                    images=extracted_data.get('images', []),
                    videos=extracted_data.get('videos', [])