import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.base import UserRole, DisputeStatus
from app.models.dispute import Dispute
from app.models.task import Task
from app.models.user import User, Merchant, Student
from app.schemas.dispute import DisputeCreateRequest, DisputeResolveRequest, DisputeResponse
from app.services.dispute_service import raise_dispute, resolve_dispute

router = APIRouter(tags=["disputes"])


def _require_task(db: Session, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _assert_party_to_task(db: Session, task: Task, user: User) -> None:
    if user.role == UserRole.MERCHANT:
        merchant = db.query(Merchant).filter(Merchant.user_id == user.id).first()
        if merchant is None or task.merchant_id != merchant.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a party to this task")
    elif user.role in (UserRole.STUDENT, UserRole.SERVICE_PROVIDER):
        from app.models.task_claim import TaskClaim

        claim = db.query(TaskClaim).filter(TaskClaim.task_id == task.id, TaskClaim.status.in_(["ACTIVE", "COMPLETED"])).first()
        if claim is None or claim.provider_user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a party to this task")


@router.post("/tasks/{task_id}/disputes", response_model=DisputeResponse, status_code=201)
def create_dispute(
    task_id: uuid.UUID,
    payload: DisputeCreateRequest,
    current_user: User = Depends(require_roles(UserRole.MERCHANT, UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    task = _require_task(db, task_id)
    _assert_party_to_task(db, task, current_user)
    return raise_dispute(db, task, raised_by_user_id=current_user.id, reason=payload.reason)


@router.get("/admin/disputes", response_model=list[DisputeResponse])
def list_open_disputes(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    return (
        db.query(Dispute)
        .filter(Dispute.status.in_([DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW]))
        .order_by(Dispute.created_at.asc())
        .all()
    )


@router.post("/admin/disputes/{dispute_id}/resolve", response_model=DisputeResponse)
def resolve_dispute_endpoint(
    dispute_id: uuid.UUID,
    payload: DisputeResolveRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    dispute = db.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    return resolve_dispute(db, dispute, admin_id=current_user.id, resolution=payload.resolution, note=payload.resolution_note)
