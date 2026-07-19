import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.base import TaskStatus, PaymentStatus, ClaimStatus
from app.models.deliverable import Deliverable
from app.models.payment import Payment
from app.models.task import Task
from app.models.task_claim import TaskClaim
from app.services.notification_service import notify
from app.services.storage_service import generate_presigned_put_url
from app.services.task_service import transition_task


def get_active_claim_or_403(db: Session, task: Task, provider_user_id: uuid.UUID) -> TaskClaim:
    claim = db.query(TaskClaim).filter(TaskClaim.task_id == task.id, TaskClaim.status == ClaimStatus.ACTIVE).first()
    if claim is None or claim.provider_user_id != provider_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You did not claim this task")
    return claim


def start_work(db: Session, task: Task, provider_user_id: uuid.UUID) -> Task:
    get_active_claim_or_403(db, task, provider_user_id)
    transition_task(db, task, TaskStatus.IN_PROGRESS, actor_user_id=provider_user_id)
    db.commit()
    return task


def request_presigned_upload(task: Task, provider_user_id: uuid.UUID, content_type: str, file_type: str) -> dict:
    from app.core.config import settings

    if task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task must be IN_PROGRESS to upload deliverables (status={task.status.value})",
        )
    key = f"deliverables/{task.id}/{uuid.uuid4()}"
    url = generate_presigned_put_url(key, content_type)
    return {"upload_url": url, "storage_key": key, "expires_in": settings.presigned_url_expiry}


def register_deliverable(
    db: Session,
    task: Task,
    provider_user_id: uuid.UUID,
    student_id: uuid.UUID | None,
    storage_key: str | None,
    file_type: str | None,
    external_link: str | None,
    note: str | None,
) -> Deliverable:
    get_active_claim_or_403(db, task, provider_user_id)

    if task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task must be IN_PROGRESS to submit deliverables (status={task.status.value})",
        )
    if not storage_key and not external_link:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide a storage_key or external_link")
    # Keys are minted by request_presigned_upload under this task's prefix;
    # anything else could point at another task's (or arbitrary) objects.
    if storage_key and not storage_key.startswith(f"deliverables/{task.id}/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="storage_key does not belong to this task")

    deliverable = Deliverable(
        task_id=task.id,
        student_id=student_id,
        provider_user_id=provider_user_id,
        storage_key=storage_key or "",
        file_type=file_type,
        external_link=external_link,
        note=note,
    )
    db.add(deliverable)
    db.commit()
    db.refresh(deliverable)
    return deliverable


def submit_task(db: Session, task: Task, provider_user_id: uuid.UUID) -> Task:
    get_active_claim_or_403(db, task, provider_user_id)

    has_deliverable = db.query(Deliverable).filter(Deliverable.task_id == task.id).first() is not None
    if not has_deliverable:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submit at least one deliverable first")

    transition_task(db, task, TaskStatus.SUBMITTED, actor_user_id=provider_user_id)
    db.commit()

    from app.models.user import Merchant

    merchant = db.get(Merchant, task.merchant_id) if task.merchant_id else None
    requester_id = merchant.user_id if merchant else task.requester_user_id
    if requester_id:
        notify(
            db, user_id=requester_id, task_id=task.id, channel="WHATSAPP",
            event_type="TASK_SUBMITTED",
            body=f'"{task.title}" has been submitted for your review. Reply to approve it in the app.',
        )
    db.commit()
    return task


def approve_task(db: Session, task: Task, merchant_id: uuid.UUID) -> Task:
    if task.merchant_id != merchant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your task")

    from app.services.payment_service import release_payment
    release_payment(db, task)
    transition_task(db, task, TaskStatus.APPROVED, actor_user_id=None)
    transition_task(db, task, TaskStatus.COMPLETED, actor_user_id=None)

    db.commit()

    claim = db.query(TaskClaim).filter(TaskClaim.task_id == task.id, TaskClaim.status == ClaimStatus.COMPLETED).first()
    if claim is not None:
        notify(
            db,
            user_id=claim.provider_user_id,
            task_id=task.id,
            channel="WHATSAPP",
            event_type="TASK_PAID",
            body=f'"{task.title}" was approved and payment has been released. Nice work!',
        )
        db.commit()

    return task
