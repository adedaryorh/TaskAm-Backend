from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
import uuid

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.base import UserRole, TaskStatus, ServiceCategory
from app.models.task import Task
from app.models.user import Student, User
from app.schemas.task import TaskResponse, TaskClaimResponse
from app.services.claim_service import claim_task, release_claim

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get("/tasks", response_model=list[TaskResponse])
def browse_published_tasks(
    service_category: ServiceCategory | None = Query(None),
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    query = db.query(Task).filter(Task.status == TaskStatus.PUBLISHED)
    if service_category:
        query = query.filter(Task.service_category == service_category)
    return query.order_by(Task.created_at.desc()).all()


@router.post("/tasks/{task_id}/claim", response_model=TaskClaimResponse, status_code=201)
def claim_task_endpoint(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    if current_user.role == UserRole.STUDENT and student is None:
        # Shouldn't happen for a STUDENT-role user created via /auth/signup/student,
        # but guard anyway.
        from fastapi import HTTPException, status as http_status

        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Student profile not found")

    return claim_task(
        db, task_id=task_id, provider_user_id=current_user.id,
        student_id=student.id if student else None,
    )


@router.post("/tasks/{task_id}/release", response_model=TaskClaimResponse)
def release_task_endpoint(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    if current_user.role == UserRole.STUDENT and student is None:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Student profile not found")
    return release_claim(db, task_id, current_user.id)
