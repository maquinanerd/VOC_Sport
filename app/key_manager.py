#!/usr/bin/env python3
"""
Manages API keys for different categories, handling rotation, cooldowns, and failures.
"""
import logging
import time
from typing import Dict, List, Optional, Tuple

from .config import AI_API_KEYS

logger = logging.getLogger(__name__)

class KeyManager:
    """
    A stateful manager for API keys.

    It handles key rotation, cooldowns for keys that hit quota limits,
    and permanent deactivation of invalid keys.
    """

    def __init__(self, cooldown_seconds: int = 3600):
        """
        Initializes the KeyManager.

        Args:
            cooldown_seconds (int): The default time in seconds a key will be on cooldown
                                    after a quota failure.
        """
        if not AI_API_KEYS:
            raise ValueError("AI_API_KEYS configuration is empty. Please check your .env file.")

        self.keys_by_category: Dict[str, List[str]] = AI_API_KEYS
        self.cooldown_seconds = cooldown_seconds

        # State for each key: (cooldown_until_timestamp, is_permanently_failed)
        self.key_states: Dict[str, Dict[int, Tuple[float, bool]]] = {
            category: {
                i: (0, False) for i in range(len(keys))
            } for category, keys in self.keys_by_category.items()
        }

        # Last used key index for round-robin
        self.last_used_index: Dict[str, int] = {
            category: -1 for category in self.keys_by_category
        }
        logger.info(f"KeyManager initialized for categories: {list(self.keys_by_category.keys())}")

    def get_next_available_key(self, category: str) -> Optional[Tuple[int, str]]:
        """
        Gets the next available and valid API key for a given category using round-robin.

        Args:
            category (str): The category for which to get a key (e.g., 'futebol').

        Returns:
            A tuple of (key_index, api_key) or None if no keys are available.
        """
        category_keys = self.keys_by_category.get(category)
        if not category_keys:
            logger.error(f"No API keys configured for category: '{category}'")
            return None

        num_keys = len(category_keys)
        start_index = (self.last_used_index.get(category, -1) + 1) % num_keys

        for i in range(num_keys):
            current_index = (start_index + i) % num_keys
            cooldown_until, is_permanent_fail = self.key_states[category][current_index]

            if is_permanent_fail:
                continue  # Skip permanently failed keys

            if time.time() > cooldown_until:
                self.last_used_index[category] = current_index
                logger.info(f"Selected key index {current_index} for category '{category}'.")
                return current_index, category_keys[current_index]

        logger.warning(f"All keys for category '{category}' are on cooldown or have failed.")
        return None

    def report_failure(self, category: str, key_index: int, is_permanent: bool = False):
        """
        Reports a failure for a specific key, putting it on cooldown or marking it as permanently failed.

        Args:
            category (str): The category of the key.
            key_index (int): The index of the failed key.
            is_permanent (bool): If True, the key will be permanently disabled.
        """
        if category not in self.key_states or key_index not in self.key_states[category]:
            return

        if is_permanent:
            self.key_states[category][key_index] = (float('inf'), True)
            logger.error(f"Key index {key_index} for category '{category}' marked as permanently failed.")
        else:
            cooldown_end = time.time() + self.cooldown_seconds
            self.key_states[category][key_index] = (cooldown_end, False)
            logger.warning(
                f"Key index {key_index} for category '{category}' put on cooldown for {self.cooldown_seconds} seconds."
            )

    def report_success(self, category: str, key_index: int):
        """
        Reports a successful usage of a key, resetting its cooldown status.
        """
        if category not in self.key_states or key_index not in self.key_states[category]:
            return

        _cooldown, is_permanent = self.key_states[category][key_index]
        if not is_permanent:
            self.key_states[category][key_index] = (0, False)