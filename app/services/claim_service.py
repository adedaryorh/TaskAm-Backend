import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import TaskStatus, ClaimStatus
from app.models.task import Task
from app.models.task_claim import TaskClaim
from app.services.task_service import transition_task


def claim_task(
    db: Session, task_id: uuid.UUID, provider_user_id: uuid.UUID,
    student_id: uuid.UUID | None = None,
) -> TaskClaim:
    """
    The critical section: locks the task row with SELECT FOR UPDATE so two
    concurrent claim requests for the same task can't both succeed. Combined
    with the DB-level unique constraint on task_claims.task_id, this makes a
    double-claim impossible even under real concurrency (the lock prevents
    the race in the common case; the constraint is the backstop if the lock
    were ever bypassed).
    """
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task.status != TaskStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task is not available to claim (status={task.status.value})",
        )

    claim = TaskClaim(
        task_id=task.id, student_id=student_id,
        provider_user_id=provider_user_id, status=ClaimStatus.ACTIVE,
    )
    db.add(claim)

    try:
        transition_task(db, task, TaskStatus.CLAIMED, actor_user_id=provider_user_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task was already claimed")

    db.refresh(claim)

    from app.models.user import Merchant
    from app.services.notification_service import notify

    merchant = db.get(Merchant, task.merchant_id) if task.merchant_id else None
    requester_id = merchant.user_id if merchant else task.requester_user_id
    if requester_id:
        notify(
            db, user_id=requester_id, task_id=task.id, channel="WHATSAPP",
            event_type="TASK_CLAIMED",
            body=f'A service provider claimed "{task.title}". Fund the request to let work begin.',
        )
    db.commit()

    return claim


def release_claim(db: Session, task_id: uuid.UUID, provider_user_id: uuid.UUID) -> TaskClaim:
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    claim = db.query(TaskClaim).filter(
        TaskClaim.task_id == task.id,
        TaskClaim.provider_user_id == provider_user_id,
        TaskClaim.status == ClaimStatus.ACTIVE,
    ).first()
    if claim is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not hold the active claim")
    if task.status != TaskStatus.CLAIMED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A funded or started task cannot be released")
    claim.status = ClaimStatus.RELEASED
    transition_task(db, task, TaskStatus.PUBLISHED, actor_user_id=provider_user_id)
    db.commit()
    db.refresh(claim)
    return claim
