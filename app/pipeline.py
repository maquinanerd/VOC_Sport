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
    rewrite_img_srcs_with_wp,
    strip_credits_and_normalize_youtube,
    remove_broken_image_placeholders,
    strip_naked_internal_links,
)
from .html_utils import collapse_h2_headings
from .taxonomy.intelligence import CategoryManager
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


def run_pipeline_cycle():
    """Executes a full cycle of the content processing pipeline."""
    logger.info("Starting new pipeline cycle.")

    db = Database()
    feed_reader = FeedReader(user_agent=PIPELINE_CONFIG.get('publisher_name', 'Bot'))
    extractor = ContentExtractor()
    wp_client = WordPressClient(config=WORDPRESS_CONFIG, categories_map=WORDPRESS_CATEGORIES)
    ai_processor = AIProcessor()
    tax_cache = TaxonomyCache()
    category_manager = CategoryManager(wp_client=wp_client, cache=tax_cache)

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
                        content_html = merge_images_into_content(
                            content_html,
                            extracted_data.get('images', [])
                        )
                        
                        # 3.3: Upload ONLY the featured image if it's valid
                        featured_image_url = extracted_data.get('featured_image_url')

                        # If the primary featured image is invalid, search for a fallback.
                        if not (featured_image_url and is_valid_upload_candidate(featured_image_url)):
                            logger.warning(f"Initial featured image '{featured_image_url}' is not valid. Searching for a fallback.")
                            found_fallback = False
                            for img_url in extracted_data.get('images', []):
                                if is_valid_upload_candidate(img_url):
                                    featured_image_url = img_url  # Found a valid fallback
                                    logger.info(f"Found a valid fallback featured image: {featured_image_url}")
                                    found_fallback = True
                                    break
                            if not found_fallback:
                                featured_image_url = None # Ensure it's None if no valid image is found

                        urls_to_upload = [featured_image_url] if featured_image_url else []

                        uploaded_src_map = {}
                        uploaded_id_map = {}
                        logger.info(f"Attempting to upload {len(urls_to_upload)} image(s).")
                        for url in urls_to_upload:
                            media = wp_client.upload_media_from_url(url, title)
                            if media and media.get("source_url") and media.get("id"):
                                # Normalize URL to handle potential trailing slashes as keys
                                k = url.rstrip('/')
                                uploaded_src_map[k] = media["source_url"]
                                uploaded_id_map[k] = media["id"]
                        
                        # 3.4: Rewrite image `src` to point to WordPress
                        content_html = rewrite_img_srcs_with_wp(content_html, uploaded_src_map)

                        # 3.5: Add credits to figures (currently disabled)
                        # content_html = add_credit_to_figures(content_html, extracted_data['source_url'])

                        # Só player do YouTube (oEmbed) e sem “Crédito: …”
                        content_html = strip_credits_and_normalize_youtube(content_html)
                        
                        # Adicionar crédito da fonte no final do post
                        source_name = RSS_FEEDS.get(source_id, {}).get('source_name', urlparse(article_url_to_process).netloc)
                        credit_line = f'<p><strong>Fonte:</strong> <a href="{article_url_to_process}" target="_blank" rel="noopener noreferrer">{source_name}</a></p>'
                        content_html += f"\n{credit_line}"

                        # Step 4: Prepare payload for WordPress
                        # Dynamic category assignment
                        category_ids_to_assign = category_manager.assign_categories(
                            title=title,
                            content=content_html
                        )
                        # 4.1: Determine featured media ID to avoid re-upload
                        featured_media_id = None
                        if featured_url := extracted_data.get('featured_image_url'):
                            k = featured_url.rstrip('/')
                            featured_media_id = uploaded_id_map.get(k)
                        else:
                            logger.info("No suitable featured image found after filtering; proceeding without one.")
                        if not featured_media_id and uploaded_id_map:
                            featured_media_id = next(iter(uploaded_id_map.values()), None)

                        # 3.5: Set alt text for uploaded images
                        focus_kw = rewritten_data.get("focus_keyword", "")
                        # The AI is asked to provide a dict like: { "filename.jpg": "alt text" }
                        alt_map = rewritten_data.get("image_alt_texts", {})

                        if uploaded_id_map and (alt_map or focus_kw):
                            logger.info("Setting alt text for uploaded images.")
                            for original_url, media_id in uploaded_id_map.items():
                                # Extract filename from the original URL to match keys in alt_map
                                filename = urlparse(original_url).path.split('/')[-1]

                                # Try to get specific alt text from AI, fallback to a generic one
                                alt_text = alt_map.get(filename)
                                if not alt_text and focus_kw:
                                    alt_text = f"{focus_kw} — foto ilustrativa"

                                if alt_text:
                                    wp_client.set_media_alt_text(media_id, alt_text)

                        # Prepare Yoast meta, including canonical URL to original source
                        yoast_meta = rewritten_data.get('yoast_meta', {})
                        yoast_meta['_yoast_wpseo_canonical'] = article_url_to_process

                        # Add related keyphrases if present
                        related_kws = rewritten_data.get('related_keyphrases')
                        if isinstance(related_kws, list) and related_kws:
                            # Yoast stores this as a JSON string of objects: [{"keyword": "phrase"}, ...]
                            yoast_meta['_yoast_wpseo_keyphrases'] = json.dumps([{"keyword": kw} for kw in related_kws])

                        post_payload = {
                            'title': title,
                            'slug': rewritten_data.get('slug'),
                            'content': content_html,
                            'excerpt': rewritten_data.get('meta_description', ''),
                            'categories': category_ids_to_assign,
                            'tags': rewritten_data.get('tags', []),
                            'featured_media': featured_media_id,
                            'meta': yoast_meta,
                        }

                        wp_post_id = wp_client.create_post(post_payload)

                        if wp_post_id:
                            db.save_processed_post(article_db_id, wp_post_id)
                            logger.info(f"Successfully published post {wp_post_id} for article DB ID {article_db_id}")
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