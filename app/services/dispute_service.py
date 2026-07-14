import uuid

from fastapi import HTTPException, status

from sqlalchemy.orm import Session

from app.models.base import TaskStatus, DisputeStatus, PaymentStatus
from app.models.dispute import Dispute
from app.models.payment import Payment
from app.models.task import Task
from app.models.task_claim import TaskClaim
from app.services.notification_service import notify
from app.services.task_service import transition_task, InvalidTaskTransition


def raise_dispute(db: Session, task: Task, raised_by_user_id: uuid.UUID, reason: str) -> Dispute:
    try:
        transition_task(db, task, TaskStatus.DISPUTED, actor_user_id=raised_by_user_id)
    except InvalidTaskTransition as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    dispute = Dispute(
        task_id=task.id,
        raised_by_user_id=raised_by_user_id,
        reason=reason,
        status=DisputeStatus.OPEN,
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)
    return dispute


def resolve_dispute(db: Session, dispute: Dispute, admin_id: uuid.UUID, resolution: str, note: str | None) -> Dispute:
    if dispute.status not in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dispute already resolved")

    task = db.get(Task, dispute.task_id)
    payment = db.query(Payment).filter(Payment.task_id == task.id).first()

    if resolution == "RESOLVED_MERCHANT":
        # Refund the merchant; task does not complete.
        from app.services.payment_service import refund_payment
        refund_payment(db, task)
        dispute.status = DisputeStatus.RESOLVED_MERCHANT
        transition_task(db, task, TaskStatus.CANCELLED, actor_user_id=admin_id)

    elif resolution == "RESOLVED_STUDENT":
        # Release escrow to the student as if the work were approved.
        from app.services.payment_service import release_payment
        release_payment(db, task)
        dispute.status = DisputeStatus.RESOLVED_STUDENT
        transition_task(db, task, TaskStatus.COMPLETED, actor_user_id=admin_id)

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="resolution must be RESOLVED_MERCHANT or RESOLVED_STUDENT")

    dispute.resolution_note = note
    dispute.resolved_by_admin_id = admin_id
    db.commit()
    db.refresh(dispute)

    # Notify both parties.
    from app.models.user import Merchant

    merchant = db.get(Merchant, task.merchant_id) if task.merchant_id else None
    requester_id = merchant.user_id if merchant else task.requester_user_id
    claim = db.query(TaskClaim).filter(TaskClaim.task_id == task.id, TaskClaim.status.in_(["ACTIVE", "COMPLETED"])).first()

    outcome_text = "in the merchant's favor (refunded)" if resolution == "RESOLVED_MERCHANT" else "in the student's favor (paid out)"
    if requester_id:
        notify(
            db, user_id=requester_id, task_id=task.id, channel="WHATSAPP",
            event_type="DISPUTE_RESOLVED",
            body=f'Dispute on "{task.title}" was resolved {outcome_text}.',
        )
    if claim is not None:
        notify(
            db,
            user_id=claim.provider_user_id,
            task_id=task.id,
            channel="WHATSAPP",
            event_type="DISPUTE_RESOLVED",
            body=f'Dispute on "{task.title}" was resolved {outcome_text}.',
        )
    db.commit()

    return dispute
