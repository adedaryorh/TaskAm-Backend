import uuid
import enum
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class UserRole(str, enum.Enum):
    MERCHANT = "MERCHANT"
    STUDENT = "STUDENT"
    ADMIN = "ADMIN"
    FARMER = "FARMER"
    SERVICE_PROVIDER = "SERVICE_PROVIDER"


class ServiceCategory(str, enum.Enum):
    TRANSPORT = "TRANSPORT"
    LABOUR = "LABOUR"
    TRACTOR_RENTAL = "TRACTOR_RENTAL"
    VETERINARY = "VETERINARY"
    IRRIGATION = "IRRIGATION"
    WAREHOUSING = "WAREHOUSING"
    SOIL_TESTING = "SOIL_TESTING"
    EXTENSION_SUPPORT = "EXTENSION_SUPPORT"
    OTHER = "OTHER"


class RequestSource(str, enum.Enum):
    TASKAM = "TASKAM"
    FARMSENSE_APP = "FARMSENSE_APP"
    WHATSAPP = "WHATSAPP"
    ADMIN = "ADMIN"


class TaskStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    AI_PARSED = "AI_PARSED"
    PENDING_MERCHANT_CONFIRMATION = "PENDING_MERCHANT_CONFIRMATION"
    PUBLISHED = "PUBLISHED"
    CLAIMED = "CLAIMED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


# Valid one-directional transitions, plus exits to CANCELLED / DISPUTED from any
# non-terminal state (enforced separately in the service layer).
TASK_STATE_TRANSITIONS = {
    TaskStatus.DRAFT: {TaskStatus.AI_PARSED, TaskStatus.CANCELLED},
    TaskStatus.AI_PARSED: {TaskStatus.PENDING_MERCHANT_CONFIRMATION, TaskStatus.CANCELLED},
    TaskStatus.PENDING_MERCHANT_CONFIRMATION: {TaskStatus.PUBLISHED, TaskStatus.CANCELLED},
    TaskStatus.PUBLISHED: {TaskStatus.CLAIMED, TaskStatus.CANCELLED},
    # Escrow: merchant funds the task right after a student claims it, before
    # any work starts. This matches the product flow (claim -> payment ->
    # delivery), not a pay-on-approval model.
    TaskStatus.CLAIMED: {TaskStatus.PUBLISHED, TaskStatus.FUNDED, TaskStatus.CANCELLED, TaskStatus.DISPUTED},
    TaskStatus.FUNDED: {TaskStatus.IN_PROGRESS, TaskStatus.DISPUTED},
    TaskStatus.IN_PROGRESS: {TaskStatus.SUBMITTED, TaskStatus.DISPUTED},
    TaskStatus.SUBMITTED: {TaskStatus.APPROVED, TaskStatus.DISPUTED},
    # APPROVED -> COMPLETED is the payout release step (funds move from
    # escrow to the student).
    TaskStatus.APPROVED: {TaskStatus.COMPLETED, TaskStatus.DISPUTED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
    # A dispute resolves one of two ways: refund the merchant (-> CANCELLED)
    # or release escrow to the student (-> COMPLETED). Both are decided by
    # an admin in app/services/dispute_service.py.
    TaskStatus.DISPUTED: {TaskStatus.CANCELLED, TaskStatus.COMPLETED},
}


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class ClaimStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class DisputeStatus(str, enum.Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_MERCHANT = "RESOLVED_MERCHANT"
    RESOLVED_STUDENT = "RESOLVED_STUDENT"
    CLOSED = "CLOSED"


class WebhookSource(str, enum.Enum):
    WHATSAPP = "WHATSAPP"
    OPAY = "OPAY"
    PAYSTACK = "PAYSTACK"
    LOGISTICS = "LOGISTICS"
