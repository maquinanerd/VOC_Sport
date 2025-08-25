# Overview

The RSS to WordPress Automation System is a production-ready Python application that automatically processes entertainment news from multiple RSS feeds, rewrites content using Google Gemini AI, and publishes SEO-optimized articles to WordPress. The system handles content from 9 entertainment sources across movies, TV series, and gaming categories, with built-in deduplication, media handling, and continuous scheduling capabilities.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Core Pipeline Architecture
The application follows a modular pipeline architecture that processes RSS feeds in a specific order defined in `PIPELINE_ORDER`. Each pipeline stage handles one content source and processes articles through multiple sequential steps: feed reading, content extraction, AI rewriting, media processing, and WordPress publishing.

## Modular Component Design
The system is organized into distinct modules:
- **Feed Processing** (`feeds.py`): RSS feed reading and normalization using feedparser
- **Content Extraction** (`extractor.py`): Full article extraction using trafilatura with BeautifulSoup fallback
- **AI Processing** (`ai_processor.py`): Content rewriting using Google Gemini API with failover support
- **Content Rewriting** (`rewriter.py`): HTML validation and content structuring
- **Media Handling** (`media.py`): Image and video processing with WordPress upload capabilities
- **WordPress Integration** (`wordpress.py`): REST API client for publishing content
- **Database Storage** (`store.py`): SQLite-based deduplication and tracking
- **Categorization** (`categorizer.py`): Automatic category mapping based on content type
- **Tag Extraction** (`tags.py`): Intelligent tag generation from content analysis

## Data Storage Strategy
The system uses SQLite for local data persistence, storing processed article IDs for deduplication and tracking publication status. Database includes tables for seen articles and processed posts to prevent duplicate processing.

## AI Content Processing
Uses Google Gemini API with a multi-key failover system organized by content category (movies, series, games). Content rewriting follows a universal prompt template loaded from an external file, ensuring consistent output formatting for SEO optimization.

## Scheduling and Automation
Built on APScheduler with blocking scheduler for continuous operation. Processes feeds in sequential order with configurable intervals and includes cleanup routines for old records and log files.

## Error Handling and Resilience
Implements comprehensive error handling with exponential backoff for API calls, graceful degradation when services are unavailable, and detailed logging with file rotation. System continues processing even when individual components fail.

## Content Optimization
Designed for Google News and Discover optimization with automatic SEO structuring, internal linking based on extracted tags, and HTML sanitization for WordPress compatibility.

# External Dependencies

## AI Services
- **Google Gemini API**: Primary content rewriting service with multiple API keys for failover
- **Universal Prompt Template**: External prompt configuration file for consistent AI responses

## Content Sources
- **RSS Feeds**: 9 entertainment news sources including ScreenRant, MovieWeb, Collider, CBR, GameRant, and TheGamer
- **Web Scraping**: trafilatura and BeautifulSoup for full article content extraction
- **readability library**: Fallback content extraction method

## Publishing Platform
- **WordPress REST API**: Content publishing with authentication via Basic Auth
- **WordPress Categories**: Configurable category mapping for content organization
- **Media Upload**: WordPress media library integration for image handling

## Data Processing Libraries
- **feedparser**: RSS feed parsing and normalization
- **PIL (Pillow)**: Image processing and validation
- **BeautifulSoup**: HTML parsing and content sanitization
- **python-slugify**: URL-safe tag generation

## Infrastructure
- **SQLite**: Local database for deduplication and tracking
- **APScheduler**: Job scheduling and automation
- **requests**: HTTP client with session management and retry logic
- **python-dateutil**: Date parsing and normalization

## Configuration Management
- **Environment Variables**: All sensitive configuration through os.getenv()
- **Logging**: Python logging with file rotation and console output
- **Signal Handling**: Graceful shutdown and cleanup procedures