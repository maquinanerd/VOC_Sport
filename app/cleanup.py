import logging
import time
from datetime import datetime, timedelta

from .store import Database

logger = logging.getLogger(__name__)


class CleanupManager:
    """Handles periodic cleanup of old database records."""

    def __init__(self, cleanup_after_hours: int):
        """
        Initializes the CleanupManager.

        Args:
            cleanup_after_hours: The age in hours after which records should be deleted.
        """
        self.db = Database()
        self.cleanup_delta = timedelta(hours=cleanup_after_hours)

    def run_cleanup(self):
        """Deletes records from the database older than the configured delta."""
        cutoff_time = datetime.now() - self.cleanup_delta
        logger.info(f"Starting cleanup of records older than {cutoff_time.isoformat()}")
        try:
            # This assumes the Database class has a method to perform the cleanup.
            deleted_count = self.db.cleanup_old_entries(cutoff_time)
            logger.info(f"Cleanup complete. Deleted {deleted_count} old records.")
        except Exception as e:
            logger.error(f"An error occurred during cleanup: {e}", exc_info=True)