import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.base import UserRole, TaskStatus
from app.models.task import Task
from app.models.user import Student, User
from app.schemas.admin import StudentAdminResponse, AuditLogResponse
from app.schemas.task import TaskResponse

router = APIRouter(prefix="/admin", tags=["admin"])

_admin_only = require_roles(UserRole.ADMIN)


@router.get("/students/pending", response_model=list[StudentAdminResponse])
def list_pending_students(current_user: User = Depends(_admin_only), db: Session = Depends(get_db)):
    rows = (
        db.query(Student, User)
        .join(User, Student.user_id == User.id)
        .filter(Student.is_verified.is_(False))
        .all()
    )
    return [
        StudentAdminResponse(
            id=s.id, user_id=u.id, school=s.school, is_verified=s.is_verified,
            full_name=u.full_name, phone_number=u.phone_number,
        )
        for s, u in rows
    ]


@router.post("/students/{student_id}/verify", response_model=StudentAdminResponse)
def verify_student(student_id: uuid.UUID, current_user: User = Depends(_admin_only), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    student.is_verified = True
    db.commit()
    db.refresh(student)
    user = db.get(User, student.user_id)
    return StudentAdminResponse(
        id=student.id, user_id=user.id, school=student.school, is_verified=student.is_verified,
        full_name=user.full_name, phone_number=user.phone_number,
    )


@router.get("/tasks", response_model=list[TaskResponse])
def list_all_tasks(
    task_status: TaskStatus | None = Query(None, alias="status"),
    current_user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
):
    q = db.query(Task)
    if task_status is not None:
        q = q.filter(Task.status == task_status)
    return q.order_by(Task.created_at.desc()).limit(200).all()


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def query_audit_logs(
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    current_user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if entity_type is not None:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(AuditLog.entity_id == entity_id)
    return q.order_by(AuditLog.created_at.desc()).limit(200).all()
