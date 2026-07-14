"""Retries failed notification deliveries with exponential backoff."""
import logging
import signal
import time
from datetime import datetime, timezone

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.notification import Notification
from app.services.notification_service import dispatch_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_shutdown = False


def _stop(signum, frame):
    global _shutdown
    _shutdown = True


def process_batch(limit: int = 100) -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(Notification)
            .filter(
                Notification.sent.is_(False),
                Notification.attempts < settings.notification_max_attempts,
                (Notification.next_attempt_at.is_(None) | (Notification.next_attempt_at <= datetime.now(timezone.utc))),
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for row in rows:
            dispatch_notification(db, row)
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("Notification retry batch failed")
        return 0
    finally:
        db.close()


def run() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not _shutdown:
        if process_batch() == 0:
            time.sleep(settings.notification_poll_seconds)


if __name__ == "__main__":
    run()
