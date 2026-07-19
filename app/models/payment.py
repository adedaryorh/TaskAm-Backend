import uuid

from sqlalchemy import String, Text, Enum, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPKMixin, PaymentStatus


class Payment(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "payments"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), unique=True, nullable=False)
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)

    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="NGN")

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="OPAY")  # OPAY | PAYSTACK
    provider_reference: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), nullable=False, default=PaymentStatus.PENDING
    )

    raw_webhook_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    settlement_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settlement_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="payment")
