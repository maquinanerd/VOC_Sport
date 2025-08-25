#!/usr/bin/env python3
"""
Custom exception classes for the RSS-to-WordPress automation app.
"""

class AIProcessorError(Exception):
    """
    Custom exception for errors related to the AI content processor.
    This can be raised for issues like invalid configuration, prompt loading
    failures, or problems parsing the AI's response.
    """
    pass


class AllKeysFailedError(AIProcessorError):
    """
    Raised when all available API keys for a specific category have been tried
    and have failed, preventing further AI processing for that category.
    """
    pass


class WordPressPublisherError(Exception):
    """Custom exception for errors related to publishing content to WordPress."""
    pass


class ArticleProcessingError(Exception):
    """
    Generic error for failures during the article processing pipeline,
    such as content extraction or data validation issues.
    """
    pass