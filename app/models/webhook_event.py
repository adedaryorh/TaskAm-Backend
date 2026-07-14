from sqlalchemy import String, Enum, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPKMixin, WebhookSource


class WebhookEvent(Base, UUIDPKMixin, TimestampMixin):
    """
    Every inbound WhatsApp / OPay event is written here first, keyed on the
    provider's own message/event ID, BEFORE any business logic runs. This is
    what enforces webhook idempotency: a unique constraint on
    (source, external_id) means a duplicate delivery raises an integrity
    error that the handler catches and treats as "already processed."
    """

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_webhook_events_source_external_id"),)

    source: Mapped[WebhookSource] = mapped_column(Enum(WebhookSource, name="webhook_source"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
