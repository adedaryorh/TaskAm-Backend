import secrets
import uuid
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.base import RequestSource, ServiceCategory, TaskStatus, UserRole
from app.models.outbound_webhook import OutboundWebhook
from app.models.task import Task
from app.models.user import User
from app.schemas.integration import InternalServiceRequestCreate
from app.services.audit_service import write_audit_log


def logistics_reference(task_id: uuid.UUID) -> str:
    return f"TAM-LOG-{task_id.hex[:12].upper()}"


NORMALIZED_TASK_STATUS = {
    TaskStatus.DRAFT: "requested",
    TaskStatus.AI_PARSED: "requested",
    TaskStatus.PENDING_MERCHANT_CONFIRMATION: "quoted",
    TaskStatus.PUBLISHED: "confirmed",
    TaskStatus.CLAIMED: "provider_assigned",
    TaskStatus.FUNDED: "booked",
    TaskStatus.IN_PROGRESS: "in_transit",
    TaskStatus.SUBMITTED: "delivered",
    TaskStatus.APPROVED: "delivered",
    TaskStatus.COMPLETED: "delivered",
    TaskStatus.CANCELLED: "cancelled",
    TaskStatus.DISPUTED: "disputed",
}


def normalized_task_status(status_value: TaskStatus) -> str:
    return NORMALIZED_TASK_STATUS[status_value]


def request_fingerprint(payload: InternalServiceRequestCreate) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _return_idempotent(existing: Task, fingerprint: str) -> tuple[Task, bool]:
    if existing.internal_request_hash and existing.internal_request_hash != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different request payload",
        )
    return existing, False


def enqueue_farmsense_status(
    db: Session, task: Task, event_type: str = "service_request.status_changed",
    normalized_status_override: str | None = None, extra_data: dict | None = None,
) -> None:
    if task.request_source != RequestSource.FARMSENSE_APP or not settings.farmsense_status_webhook_url:
        return
    requester = db.get(User, task.requester_user_id) if task.requester_user_id else None
    db.add(OutboundWebhook(
        task_id=task.id,
        event_type=event_type,
        destination_url=settings.farmsense_status_webhook_url,
        payload={
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "taskam",
            "platform_user_id": requester.platform_user_id if requester else None,
            "farmsense_request_id": task.farmsense_request_id,
            "marketplace_request_id": task.marketplace_request_id,
            "logistics_delivery_id": task.logistics_delivery_id,
            "data": {
                "status": normalized_status_override or normalized_task_status(task.status),
                "internal_status": task.status.value,
                "service_category": task.service_category.value if task.service_category else None,
                "logistics_handoff_reference": task.logistics_handoff_reference,
                **(extra_data or {}),
            },
        },
    ))


def enqueue_farmsense_envelope(db: Session, task: Task, envelope: dict) -> None:
    if not settings.farmsense_status_webhook_url:
        return
    db.add(OutboundWebhook(
        task_id=task.id,
        event_type=envelope["event_type"],
        destination_url=settings.farmsense_status_webhook_url,
        payload=envelope,
    ))


def _get_or_create_requester(db: Session, payload: InternalServiceRequestCreate) -> User:
    requester = payload.requester
    user = db.query(User).filter(User.platform_user_id == requester.platform_user_id).first()
    if user:
        return user
    user = db.query(User).filter(User.phone_number == requester.phone_number).first()
    if user:
        if user.platform_user_id and user.platform_user_id != requester.platform_user_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number belongs to another platform identity")
        user.platform_user_id = requester.platform_user_id
        if not user.email and requester.email:
            user.email = requester.email
        return user
    user = User(
        platform_user_id=requester.platform_user_id,
        phone_number=requester.phone_number,
        email=requester.email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        full_name=requester.full_name,
        role=UserRole.FARMER,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def create_internal_request(db: Session, payload: InternalServiceRequestCreate, idempotency_key: str) -> tuple[Task, bool]:
    fingerprint = request_fingerprint(payload)
    existing = db.query(Task).filter(
        Task.request_source == RequestSource.FARMSENSE_APP,
        Task.integration_idempotency_key == idempotency_key,
    ).first()
    if existing:
        return _return_idempotent(existing, fingerprint)

    requester = _get_or_create_requester(db, payload)
    task = Task(
        requester_user_id=requester.id,
        request_source=RequestSource.FARMSENSE_APP,
        external_request_id=payload.farmsense_request_id,
        farmsense_request_id=payload.farmsense_request_id,
        marketplace_request_id=str(uuid.uuid4()),
        internal_request_hash=fingerprint,
        integration_idempotency_key=idempotency_key,
        service_category=payload.service_category,
        category=payload.service_category.value,
        title=payload.title,
        requirements=payload.requirements,
        farm_location=payload.farm_location.model_dump(mode="json", exclude_none=True) if payload.farm_location else None,
        agricultural_details=payload.agricultural_details.model_dump(mode="json", exclude_none=True),
        requested_start_at=payload.requested_start_at,
        suggested_payout=payload.budget_ngn,
        final_payout=payload.budget_ngn if payload.publish_immediately else None,
        status=TaskStatus.PUBLISHED if payload.publish_immediately else TaskStatus.DRAFT,
    )
    db.add(task)
    try:
        db.flush()
        if payload.service_category == ServiceCategory.TRANSPORT:
            task.logistics_handoff_reference = logistics_reference(task.id)
        write_audit_log(
            db, entity_type="TASK", entity_id=task.id, action="CREATED_FROM_FARMSENSE",
            after_state={"status": task.status.value, "farmsense_request_id": payload.farmsense_request_id},
        )
        enqueue_farmsense_status(db, task, "service_request.created")
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Task).filter(
            Task.request_source == RequestSource.FARMSENSE_APP,
            Task.integration_idempotency_key == idempotency_key,
        ).first()
        if existing:
            return _return_idempotent(existing, fingerprint)
        raise
    db.refresh(task)
    return task, True
