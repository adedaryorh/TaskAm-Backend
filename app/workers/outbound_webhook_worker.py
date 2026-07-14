import json
import logging
import signal
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import settings
from app.core.service_auth import signed_headers
from app.db.session import SessionLocal
from app.models.outbound_webhook import OutboundWebhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_shutdown = False


def _stop(signum, frame):
    global _shutdown
    _shutdown = True


def process_batch(limit: int = 50) -> int:
    db = SessionLocal()
    try:
        rows = db.query(OutboundWebhook).filter(
            OutboundWebhook.delivered.is_(False),
            OutboundWebhook.attempts < settings.outbound_webhook_max_attempts,
            (OutboundWebhook.next_attempt_at.is_(None) | (OutboundWebhook.next_attempt_at <= datetime.now(timezone.utc))),
        ).with_for_update(skip_locked=True).limit(limit).all()
        for row in rows:
            body = json.dumps(row.payload, sort_keys=True, separators=(",", ":")).encode()
            row.attempts += 1
            try:
                response = httpx.post(
                    row.destination_url,
                    content=body,
                    headers=signed_headers(settings.farmsense_outbound_secret, body),
                    timeout=15,
                )
                response.raise_for_status()
                row.delivered = True
                row.last_error = None
                row.next_attempt_at = None
            except Exception as exc:
                row.last_error = str(exc)
                row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 5 * (2 ** row.attempts)))
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("FarmSense webhook delivery batch failed")
        return 0
    finally:
        db.close()


def run():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not _shutdown:
        if process_batch() == 0:
            time.sleep(settings.outbound_webhook_poll_seconds)


if __name__ == "__main__":
    run()
