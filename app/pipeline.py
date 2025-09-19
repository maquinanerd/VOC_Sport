import logging
import time
import random
import json
import re
from collections import OrderedDict
from urllib.parse import urlparse, urljoin
from typing import Dict, Any, Optional

from .config import (
    PIPELINE_ORDER,
    RSS_FEEDS,
    SCHEDULE_CONFIG,
    WORDPRESS_CONFIG,
    WORDPRESS_CATEGORIES,
    PIPELINE_CONFIG,
)
from .store import Database
from .store import TaxonomyCache 
from .feeds import FeedReader
from .extractor import ContentExtractor
from .ai_processor import AIProcessor
from .wordpress import WordPressClient
from .store import Database # Ensure Database is imported
from .html_utils import (
    merge_images_into_content,
    add_credit_to_figures,
    rewrite_img_srcs_with_wp, # Será usado para gerar blocos Gutenberg
    strip_credits_and_normalize_youtube,
    remove_broken_image_placeholders,
    strip_naked_internal_links,
)
from .html_utils import collapse_h2_headings
from .intelligence import ensure_categories, AI_DRIVEN_CATEGORIES
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def _get_article_url(article_data: Dict[str, Any]) -> Optional[str]:
    """
    Extracts a valid URL from article data, prioritizing 'url', then 'link', then 'id' (guid).
    """
    url = article_data.get("url") or article_data.get("link") or article_data.get("id")
    if not url:
        return None
    try:
        p = urlparse(url)
        if p.scheme in ("http", "https"):
            return url
    except Exception:
        return None
    return None

DOMAIN_DENYLIST = (
    "uol.com.br",
    "imguol.com.br",
    "conteudo.imguol.com.br",
)

def is_blocked_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
        return any(d in host for d in DOMAIN_DENYLIST)
    except Exception:
        return False


BAD_HOSTS = {"sb.scorecardresearch.com", "securepubads.g.doubleclick.net"}
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

def is_valid_upload_candidate(url: str) -> bool:
    """
    Validates if a URL is a good candidate for uploading.
    Filters out trackers, avatars, and tiny images.
    """
    if not url:
        return False
    try:
        lower_url = url.lower()
        p = urlparse(lower_url)
        
        if not p.scheme.startswith("http"):
            return False
        if p.netloc in BAD_HOSTS:
            return False
        if not p.path.endswith(IMG_EXTS):
            return False
        
        # descarta imagens de avatar/author
        if "author" in lower_url or "avatar" in lower_url:
            return False
            
        # descarta imagens minúsculas (largura/altura <= 100 no querystring)
        dims = re.findall(r'[?&](?:w|width|h|height)=(\d+)', lower_url)
        if any(int(d) <= 100 for d in dims):
            return False
            
        return True
    except Exception:
        return False

# --- Regras de URL por fonte para filtrar conteúdo indesejado ---
SOURCE_URL_RULES = {
    # Só aceitar UOL com /esporte/ no path
    "lance_futebol": {
        "allow_domains": ["lance.com.br", "ge.globo.com", "uol.com.br"],
        "path_must_include": {
            "uol.com.br": ["/esporte/"],
        }
    },
    "globo_futebol": {
        "allow_domains": ["ge.globo.com", "g1.globo.com"],
        "path_must_include": {
            "ge.globo.com": ["/futebol/"],
        }
    },
}

def is_allowed_by_source_rules(source_key: str, url: str) -> bool:
    try:
        rules = SOURCE_URL_RULES.get(source_key)
        if not rules:
            return True # Se não há regras, permite
        p_url = urlparse(url)
        netloc = p_url.netloc.lower()
        path = p_url.path.lower()

        if rules.get("allow_domains") and not any(d in netloc for d in rules["allow_domains"]):
            return False

        for dom, substrs in rules.get("path_must_include", {}).items():
            if dom in netloc and not any(s in path for s in substrs):
                return False
        return True
    except Exception:
        return True # Em caso de erro na verificação, não bloqueia

def run_pipeline_cycle():
    """Executes a full cycle of the content processing pipeline."""
    logger.info("Starting new pipeline cycle.")

    db = Database()
    feed_reader = FeedReader(user_agent=PIPELINE_CONFIG.get('publisher_name', 'Bot'))
    extractor = ContentExtractor()
    wp_client = WordPressClient(config=WORDPRESS_CONFIG, categories_map=WORDPRESS_CATEGORIES)
    ai_processor = AIProcessor()
    tax_cache = TaxonomyCache()
    processed_articles_in_cycle = 0

    try:
        for i, source_id in enumerate(PIPELINE_ORDER):
            # Check circuit breaker before processing
            consecutive_failures = db.get_consecutive_failures(source_id)
            if consecutive_failures >= 3:
                logger.warning(f"Circuit open for feed {source_id} ({consecutive_failures} fails) → skipping this round.")
                # Reset for the next cycle as per prompt "zere o contador na próxima"
                db.reset_consecutive_failures(source_id)
                continue

            feed_config = RSS_FEEDS.get(source_id)
            if not feed_config:
                logger.warning(f"No configuration found for feed source: {source_id}")
                continue

            category = feed_config['category']
            logger.info(f"Processing feed: {source_id} (Category: {category})")

            try:
                feed_items = feed_reader.read_feeds(feed_config, source_id)
                new_articles = db.filter_new_articles(source_id, feed_items)

                if not new_articles:
                    logger.info(f"No new articles found for {source_id}.")
                    continue

                logger.info(f"Found {len(new_articles)} new articles for {source_id}")

                for article_data in new_articles[:SCHEDULE_CONFIG.get('max_articles_per_feed', 3)]:
                    article_db_id = article_data['db_id']
                    try:
                        article_url_to_process = _get_article_url(article_data)
                        if not article_url_to_process:
                            logger.warning(f"Skipping article {article_data.get('id')} - missing/invalid URL.")
                            db.update_article_status(article_db_id, 'FAILED', reason="Missing/invalid URL")
                            continue

                        if is_blocked_url(article_url_to_process):
                            logger.info(f"Skipping blocked domain: {article_url_to_process}")
                            db.update_article_status(article_db_id, 'SKIPPED', reason="Blocked domain")
                            continue

                        if not is_allowed_by_source_rules(source_id, article_url_to_process):
                            logger.info(f"Skipping URL by source rules: {article_url_to_process}")
                            db.update_article_status(article_db_id, 'SKIPPED', reason="Filtered by source rules")
                            continue

                        logger.info(f"Processing article: {article_data.get('title', 'N/A')} (DB ID: {article_db_id}) from {source_id}")
                        db.update_article_status(article_db_id, 'PROCESSING')
                        
                        extracted_data = extractor.extract(article_url_to_process)
                        if not extracted_data or not extracted_data.get('content'):
                            logger.warning(f"Failed to extract content from {article_data['url']}")
                            db.update_article_status(article_db_id, 'FAILED', reason="Extraction failed")
                            continue

                        # Step 2: Rewrite content with AI
                        rewritten_data, failure_reason = ai_processor.rewrite_content(
                            title=extracted_data.get('title'),
                            content_html=extracted_data.get('content'),
                            source_url=article_url_to_process,
                            category=category,
                            videos=extracted_data.get('videos', []),
                            images=extracted_data.get('images', []),
                            tags=[],  # Tags are generated by the AI in this flow
                            source_name=feed_config.get('source_name', ''),
                            domain=wp_client.get_domain(),
                            schema_original=extracted_data.get('schema_original')
                        )

                        if not rewritten_data:
                            reason = failure_reason or "AI processing failed"
                            # Check for the specific case where the key pool for the category is exhausted
                            if "pool is exhausted" in reason:
                                logger.warning(
                                    f"{feed_config['category']} pool exhausted → marking article FAILED → moving on."
                                )
                            else:
                                logger.warning(f"Article '{article_data.get('title', 'N/A')}' marked as FAILED (Reason: {reason}). Continuing to next article.")
                            db.update_article_status(article_db_id, 'FAILED', reason=reason)
                            continue

                        # Step 3: Validate AI output and prepare content
                        title = rewritten_data.get("titulo_final", "").strip()
                        content_html = rewritten_data.get("conteudo_final", "").strip()

                        if not title or not content_html:
                            logger.error(f"AI output for {article_url_to_process} missing required fields (titulo_final/conteudo_final).")
                            db.update_article_status(article_db_id, 'FAILED', reason="AI output missing required fields")
                            continue

                        # Step 3.1: HTML Processing and Cleanup
                        # Defensive cleanup of common AI errors (e.g., leftover placeholders)
                        content_html = remove_broken_image_placeholders(content_html)
                        content_html = strip_naked_internal_links(content_html)
                        content_html = collapse_h2_headings(content_html, keep_first=1)

                        # 3.2: Ensure images from original article exist in content, injecting if AI removed them
                        # A lista de imagens agora contém dicts com src, alt, caption
                        all_images_data = extracted_data.get('images', [])
                        content_html = merge_images_into_content(
                            content_html,
                            all_images_data,
                            {}, # O mapa de upload ainda não existe, será preenchido depois
                        )
                        
                        # 3.3: Consolidate, filter, and upload all images
                        featured_image_url = extracted_data.get('featured_image_url')
                        body_images_data = extracted_data.get('images', [])

                        # Create a unique, ordered list of all images to process.
                        # A imagem de destaque é a primeira, dando-lhe prioridade.
                        # Usamos um dict para deduplicar pela URL, mantendo o dict completo.
                        all_images_to_process_map = OrderedDict()
                        if featured_image_url:
                            # Encontra os dados da imagem de destaque na lista de imagens do corpo
                            featured_data = next((img for img in body_images_data if img.get('src') == featured_image_url), None)
                            if featured_data:
                                all_images_to_process_map[featured_image_url] = featured_data
                            else: # Se não estiver lá, cria uma entrada básica
                                all_images_to_process_map[featured_image_url] = {'src': featured_image_url, 'alt': '', 'caption': ''}
                        
                        for img_data in body_images_data:
                            if img_data.get('src') and img_data['src'] not in all_images_to_process_map:
                                all_images_to_process_map[img_data['src']] = img_data

                        # Filter out invalid candidates before attempting upload
                        images_to_upload = [
                            img_data for img_data in all_images_to_process_map.values() 
                            if img_data.get('src') and not is_blocked_url(img_data['src']) and is_valid_upload_candidate(img_data['src'])
                        ]

                        uploaded_media_data = {}
                        if images_to_upload:
                            logger.info(f"Attempting to upload {len(images_to_upload)} image(s).")
                            for img_data in images_to_upload:
                                original_url = img_data['src']
                                media = wp_client.upload_media_from_url(original_url, title)
                                if media and media.get("source_url") and media.get("id"):
                                    media_id = media["id"]
                                    # Atualiza alt, caption e description no WordPress
                                    wp_client.update_media_details(media_id, alt_text=img_data.get('alt'), caption=img_data.get('caption'), description=img_data.get('caption'))
                                    
                                    # Armazena todos os dados para a reescrita do bloco Gutenberg
                                    k = original_url.rstrip('/')
                                    uploaded_media_data[k] = {**img_data, 'id': media_id, 'source_url': media["source_url"]}
                        
                        # 3.4: Rewrite image tags into Gutenberg blocks
                        content_html = rewrite_img_srcs_with_wp(content_html, uploaded_media_data)

                        # 3.5: Add credits to figures (currently disabled)
                        # content_html = add_credit_to_figures(content_html, extracted_data['source_url'])

                        # Step 4: Prepare payload for WordPress
                        # 4.1: AI-driven category and tag assignment
                        category_ids_to_assign = []
                        if AI_DRIVEN_CATEGORIES and rewritten_data.get("__slug_nome_grupo"):
                            category_ids_to_assign = ensure_categories(rewritten_data["__slug_nome_grupo"], wp_client)
                        
                        # Fallback to default category if none assigned
                        if not category_ids_to_assign:
                            category_ids_to_assign = [WORDPRESS_CATEGORIES.get('futebol', 1)]

                        # TAGS: Replicate names from validated categories + AI suggestions
                        tags_from_cats = [name for (_slug, name, _grp) in rewritten_data.get("__slug_nome_grupo", [])]
                        tags_ai = rewritten_data.get("tags_sugeridas") or []
                        tags_final = list(dict.fromkeys(tags_from_cats + tags_ai))[:5]
                        tags_to_assign = wp_client.resolve_tags_by_name(tags_final, create_if_missing=False)

                        # 4.2: Determine featured media ID
                        featured_media_id = None
                        if featured_image_url:
                            # Encontra a imagem de destaque nos dados já enviados
                            norm_key = featured_image_url.rstrip('/')
                            if norm_key in uploaded_media_data:
                                featured_media_id = uploaded_media_data[norm_key].get('id')
                            else: # Fallback para a primeira imagem enviada, se a de destaque falhou
                                featured_media_id = next((data['id'] for data in uploaded_media_data.values() if data.get('id')), None)
                        
                        if not featured_media_id:
                             logger.info("No suitable featured image found after uploading; proceeding without one.")

                        # Adicionar crédito da fonte no final do post
                        source_name = RSS_FEEDS.get(source_id, {}).get('source_name', urlparse(article_url_to_process).netloc)
                        credit_line = f'<p><strong>Fonte:</strong> <a href="{article_url_to_process}" target="_blank" rel="noopener noreferrer">{source_name}</a></p>'
                        content_html += f"\n{credit_line}"
                        # 4.3: Set alt text for uploaded images
                        focus_kw = rewritten_data.get("__yoast_focus_kw", "")
                        alt_map = rewritten_data.get("image_alt_texts", {})
                        
                        # A definição de alt/caption agora é feita logo após o upload.
                        # Esta seção pode ser removida ou mantida como um fallback extra.
                        if uploaded_media_data and (alt_map or focus_kw or tags_to_assign):
                            logger.info("Setting alt text for uploaded images.")
                            for original_url, media_data in uploaded_media_data.items():
                                filename = urlparse(original_url).path.split('/')[-1] # Chave para o mapa de alt_texts da IA

                                # Try to get specific alt text from AI, fallback to a generic one
                                alt_text = alt_map.get(filename) or media_data.get('alt')
                                if not alt_text and focus_kw: alt_text = f"{focus_kw} - {tags_final[0] if tags_final else 'foto ilustrativa'}"
                                if alt_text: # Apenas atualiza se tivermos um novo alt_text
                                    wp_client.update_media_details(media_data['id'], alt_text=alt_text)

                        # Prepare post meta, including canonical URL to original source
                        yoast_meta = {}
                        yoast_meta['_yoast_wpseo_canonical'] = article_url_to_process

                        post_payload = {
                            'title': title,
                            'slug': rewritten_data.get('slug'),
                            'content': content_html,
                            'excerpt': rewritten_data.get('meta_description', ''),
                            'categories': category_ids_to_assign,
                            'tags': tags_to_assign,
                            'featured_media': featured_media_id,
                            'meta': yoast_meta,
                        }

                        wp_post_id = wp_client.create_post(post_payload)

                        if wp_post_id:
                            db.save_processed_post(article_db_id, wp_post_id)
                            logger.info(f"Successfully published post {wp_post_id} for article DB ID {article_db_id}")
                            
                            # --- BEGIN: UPDATE YOAST AFTER PUBLISH (do not duplicate) ---
                            wp_client.update_yoast_meta(
                                post_id=wp_post_id,
                                focus_kw=rewritten_data.get("__yoast_focus_kw",""),
                                related_kws=rewritten_data.get("__yoast_related_kws",[]),
                                meta_desc=rewritten_data.get("__yoast_metadesc",""),
                            )
                            # --- END: UPDATE YOAST AFTER PUBLISH ---
                            processed_articles_in_cycle += 1
                        else:
                            logger.error(f"Failed to publish post for {article_url_to_process}")
                            db.update_article_status(article_db_id, 'FAILED', reason="WordPress publishing failed")

                        # Per-article delay to respect API rate limits and avoid being predictable
                        base_delay = SCHEDULE_CONFIG.get('per_article_delay_seconds', 8)
                        # Add jitter to be less predictable (e.g., for 8s, sleep between 6s and 10s)
                        delay = max(1.0, random.uniform(base_delay - 2, base_delay + 2))
                        logger.info(f"Sleeping for {delay:.1f}s (per-article delay).")
                        time.sleep(delay)

                    except Exception as e:
                        logger.error(f"Error processing article {article_url_to_process or article_data.get('title', 'N/A')}: {e}", exc_info=True)
                        db.update_article_status(article_db_id, 'FAILED', reason=str(e))

                # If we reach here without a feed-level exception, the processing was successful
                db.reset_consecutive_failures(source_id)

            except Exception as e:
                logger.error(f"Error processing feed {source_id}: {e}", exc_info=True)
                db.increment_consecutive_failures(source_id)

            # Per-feed delay before processing the next source
            if i < len(PIPELINE_ORDER) - 1:
                next_feed = PIPELINE_ORDER[i + 1]
                delay = SCHEDULE_CONFIG.get('per_feed_delay_seconds', 15)
                logger.info(f"Finished feed '{source_id}'. Sleeping for {delay}s before next feed: {next_feed}")
                time.sleep(delay)

    finally:
        logger.info(f"Pipeline cycle completed. Processed {processed_articles_in_cycle} articles.")
        db.close()
        wp_client.close()