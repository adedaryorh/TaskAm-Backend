import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_roles, get_current_user
from app.db.session import get_db
from app.models.base import UserRole
from app.models.task import Task
from app.models.user import Merchant, User
from app.schemas.task import TaskResponse
from app.services.task_service import confirm_task, cancel_task, InvalidTaskTransition

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_owned_task(db: Session, task_id: uuid.UUID, user: User) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if user.role == UserRole.ADMIN:
        return task

    merchant = db.query(Merchant).filter(Merchant.user_id == user.id).first()
    if merchant is None or task.merchant_id != merchant.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your task")
    return task


@router.get("/mine", response_model=list[TaskResponse])
def list_my_tasks(
    current_user: User = Depends(require_roles(UserRole.MERCHANT)),
    db: Session = Depends(get_db),
):
    merchant = db.query(Merchant).filter(Merchant.user_id == current_user.id).first()
    if merchant is None:
        return []
    return db.query(Task).filter(Task.merchant_id == merchant.id).order_by(Task.created_at.desc()).all()


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_task(db, task_id, current_user)


@router.post("/{task_id}/confirm", response_model=TaskResponse)
def confirm_task_endpoint(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.MERCHANT)),
    db: Session = Depends(get_db),
):
    task = _get_owned_task(db, task_id, current_user)
    try:
        confirm_task(db, task, actor_user_id=current_user.id)
        db.commit()
    except InvalidTaskTransition as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    db.refresh(task)
    return task


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task_endpoint(
    task_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.MERCHANT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    task = _get_owned_task(db, task_id, current_user)
    try:
        cancel_task(db, task, actor_user_id=current_user.id)
        db.commit()
    except InvalidTaskTransition as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    db.refresh(task)
    return task
