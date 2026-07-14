import uuid

from sqlalchemy import Enum, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPKMixin, ClaimStatus


class TaskClaim(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "task_claims"
    # Enforces "one active claim per task" at the DB level in addition to the
    # SELECT FOR UPDATE lock taken in the service layer.
    __table_args__ = (
        Index("uq_task_claims_active_task", "task_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=True)
    provider_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status"), nullable=False, default=ClaimStatus.ACTIVE
    )

    task: Mapped["Task"] = relationship(back_populates="claims")
