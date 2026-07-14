import uuid

from sqlalchemy import String, Boolean, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPKMixin, UserRole


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    platform_user_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)

    merchant: Mapped["Merchant"] = relationship(back_populates="user", uselist=False)
    student: Mapped["Student"] = relationship(back_populates="user", uselist=False)
    provider_profile: Mapped["ProviderProfile"] = relationship(back_populates="user", uselist=False)


class Merchant(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "merchants"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="merchant")


class Student(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "students"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[float | None] = mapped_column(nullable=True)
    payout_bank_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payout_account_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payout_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payout_recipient_code: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="student")


class ProviderProfile(Base, UUIDPKMixin, TimestampMixin):
    """Agricultural provider capabilities; legacy students remain valid providers."""
    __tablename__ = "provider_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    provider_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    service_categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payout_bank_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payout_account_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payout_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payout_recipient_code: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="provider_profile")
