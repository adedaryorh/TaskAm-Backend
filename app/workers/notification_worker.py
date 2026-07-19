"""Retries failed notification deliveries with exponential backoff."""
import logging
import signal
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.notification import Notification
from app.services.notification_service import dispatch_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_shutdown = False

# How long a claimed row is invisible to other workers. Must exceed the
# slowest single delivery (WhatsApp/SMTP timeouts are 15s).
_CLAIM_LEASE_SECONDS = 60


def _stop(signum, frame):
    global _shutdown
    _shutdown = True


def process_batch(limit: int = 100) -> int:
    db = SessionLocal()
    try:
        # Claim rows with a short lease and commit immediately so row locks
        # are never held across network I/O. A crashed worker's rows simply
        # become eligible again when the lease expires.
        now = datetime.now(timezone.utc)
        rows = (
            db.query(Notification)
            .filter(
                Notification.sent.is_(False),
                Notification.attempts < settings.notification_max_attempts,
                (Notification.next_attempt_at.is_(None) | (Notification.next_attempt_at <= now)),
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for row in rows:
            row.next_attempt_at = now + timedelta(seconds=_CLAIM_LEASE_SECONDS)
        db.commit()

        # Deliver lock-free; commit per row so one slow/failed send doesn't
        # roll back the durable outcome of the others.
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
