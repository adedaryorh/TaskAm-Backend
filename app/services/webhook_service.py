from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import WebhookSource
from app.models.webhook_event import WebhookEvent


def record_webhook_event(db: Session, source: WebhookSource, external_id: str, raw_payload: dict) -> bool:
    """
    Writes the inbound event to webhook_events BEFORE any business logic
    runs. Returns True if this is a new event (safe to process), False if
    it's a duplicate delivery (already recorded — skip processing).

    This must be called in its own short transaction so the dedupe check
    commits immediately, independent of whatever processing happens next.
    """
    event = WebhookEvent(source=source, external_id=external_id, raw_payload=raw_payload)
    db.add(event)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        existing = db.query(WebhookEvent).filter(
            WebhookEvent.source == source, WebhookEvent.external_id == external_id
        ).with_for_update().first()
        # Failed processing is retryable on the provider's next delivery.
        if existing is not None and not existing.processed and existing.processing_error:
            existing.processing_error = None
            db.commit()
            return True
        return False


def finish_webhook_event(db: Session, source: WebhookSource, external_id: str, error: Exception | None = None) -> None:
    event = db.query(WebhookEvent).filter(
        WebhookEvent.source == source, WebhookEvent.external_id == external_id
    ).first()
    if event is None:
        return
    event.processed = error is None
    event.processing_error = None if error is None else str(error)[:1024]
    db.commit()
