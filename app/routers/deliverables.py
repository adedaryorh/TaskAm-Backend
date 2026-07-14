import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.base import UserRole
from app.models.task import Task
from app.models.user import Student, Merchant, User
from app.schemas.deliverable import (
    PresignUploadRequest,
    PresignUploadResponse,
    DeliverableCreateRequest,
    DeliverableResponse,
)
from app.schemas.task import TaskResponse
from app.services import deliverable_service
from fastapi import HTTPException, status as http_status

router = APIRouter(prefix="/tasks", tags=["deliverables"])


def _require_task(db: Session, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _provider_identity(db: Session, user: User) -> tuple[uuid.UUID, uuid.UUID | None]:
    student = db.query(Student).filter(Student.user_id == user.id).first()
    if user.role == UserRole.STUDENT and student is None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Student profile not found")
    return user.id, student.id if student else None


@router.post("/{task_id}/start", response_model=TaskResponse)
def start_work(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    task = _require_task(db, task_id)
    return deliverable_service.start_work(db, task, _provider_identity(db, current_user)[0])


@router.post("/{task_id}/deliverables/presign", response_model=PresignUploadResponse)
def presign_upload(
    task_id: uuid.UUID,
    payload: PresignUploadRequest,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    task = _require_task(db, task_id)
    provider_user_id, _ = _provider_identity(db, current_user)
    deliverable_service.get_active_claim_or_403(db, task, provider_user_id)
    return deliverable_service.request_presigned_upload(task, provider_user_id, payload.content_type, payload.file_type)


@router.post("/{task_id}/deliverables", response_model=DeliverableResponse, status_code=201)
def register_deliverable(
    task_id: uuid.UUID,
    payload: DeliverableCreateRequest,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    task = _require_task(db, task_id)
    provider_user_id, student_id = _provider_identity(db, current_user)
    return deliverable_service.register_deliverable(
        db, task, provider_user_id, student_id, payload.storage_key, payload.file_type, payload.external_link, payload.note
    )


@router.post("/{task_id}/submit", response_model=TaskResponse)
def submit_task(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    task = _require_task(db, task_id)
    return deliverable_service.submit_task(db, task, _provider_identity(db, current_user)[0])


@router.post("/{task_id}/approve", response_model=TaskResponse)
def approve_task(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.MERCHANT)),
    db: Session = Depends(get_db),
):
    task = _require_task(db, task_id)
    merchant = db.query(Merchant).filter(Merchant.user_id == current_user.id).first()
    if merchant is None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Merchant profile not found")
    return deliverable_service.approve_task(db, task, merchant.id)
