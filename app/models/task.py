import uuid
from datetime import datetime

from sqlalchemy import String, Text, Enum, ForeignKey, Numeric, Index, UniqueConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPKMixin, TaskStatus, ServiceCategory, RequestSource


class Task(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        UniqueConstraint("request_source", "external_request_id", name="uq_tasks_source_external_request"),
        UniqueConstraint("request_source", "integration_idempotency_key", name="uq_tasks_source_idempotency_key"),
    )

    merchant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True)
    requester_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    request_source: Mapped[RequestSource] = mapped_column(
        Enum(RequestSource, name="request_source"), nullable=False, default=RequestSource.TASKAM
    )
    external_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    internal_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integration_idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    farmsense_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    marketplace_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    logistics_delivery_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    logistics_quotes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    selected_logistics_quote_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_category: Mapped[ServiceCategory | None] = mapped_column(
        Enum(ServiceCategory, name="service_category"), nullable=True
    )
    farm_location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    agricultural_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requested_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logistics_handoff_reference: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    complexity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    suggested_payout: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    final_payout: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), nullable=False, default=TaskStatus.DRAFT
    )

    # Raw AI response kept for audit / debugging
    ai_raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Source WhatsApp message that created this task
    source_whatsapp_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Object storage key for the downloaded voice note audio, if the task
    # originated from a WhatsApp voice message rather than text.
    source_audio_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    claims: Mapped[list["TaskClaim"]] = relationship(back_populates="task")
    payment: Mapped["Payment"] = relationship(back_populates="task", uselist=False)
    deliverables: Mapped[list["Deliverable"]] = relationship(back_populates="task")
