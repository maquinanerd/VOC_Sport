import logging
import time
from datetime import datetime, timedelta
from itertools import cycle
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class KeyPool:
    """
    Manages a pool of API keys with rotation and exponential backoff cooldown.
    """

    def __init__(self, api_keys: List[str], max_cooldown_seconds: int = 300):
        """
        Initializes the KeyPool.

        Args:
            api_keys: A list of API keys to manage.
            max_cooldown_seconds: The maximum duration for a key to be in cooldown (default: 5 minutes).
        """
        if not api_keys:
            self._key_list: List[str] = []
            self._key_cycle = None
            self._key_status: Dict[str, Dict[str, Any]] = {}
            logger.warning("KeyPool initialized with an empty list of keys.")
        else:
            self._key_list = api_keys
            self._key_cycle = cycle(self._key_list)
            self._key_status = {
                key: {'cooldown_until': None, 'failures': 0}
                for key in self._key_list
            }
            logger.info(f"KeyPool ready with {len(self._key_list)} keys.")

        self.max_cooldown_seconds = max_cooldown_seconds

    def get_key(self) -> Optional[str]:
        """
        Gets the next available key from the pool, skipping any keys in cooldown.

        Returns:
            An available API key, or None if all keys are in cooldown.
        """
        if not self._key_cycle:
            return None

        for _ in range(len(self._key_list)):
            key = next(self._key_cycle)
            status = self._key_status[key]
            cooldown_until = status.get('cooldown_until')

            if cooldown_until and datetime.now() < cooldown_until:
                continue
            
            return key

        logger.warning("All API keys are currently in cooldown.")
        return None

    def report_failure(self, key: str, base_cooldown_seconds: int = 60):
        """Reports a failure for a key and puts it into exponential backoff cooldown."""
        if key not in self._key_status:
            return

        status = self._key_status[key]
        status['failures'] += 1

        backoff_factor = 2 ** (status['failures'] - 1)
        cooldown_duration = min(base_cooldown_seconds * backoff_factor, self.max_cooldown_seconds)
        cooldown_end = datetime.now() + timedelta(seconds=cooldown_duration)
        status['cooldown_until'] = cooldown_end

        logger.warning(f"Cooldown set for key ...{key[-4:]} for {cooldown_duration:.0f}s. Cooldown until: {cooldown_end.strftime('%Y-%m-%d %H:%M:%S')}")

    def report_success(self, key: str):
        """Reports a successful use of a key, resetting its failure count."""
        if key in self._key_status:
            status = self._key_status[key]
            if status['failures'] > 0:
                logger.info(f"Key ...{key[-4:]} is now active again after successful use.")
                status['failures'] = 0
                status['cooldown_until'] = None