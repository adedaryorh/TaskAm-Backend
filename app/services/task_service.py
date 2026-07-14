import uuid

from sqlalchemy.orm import Session

from app.models.base import TaskStatus, TASK_STATE_TRANSITIONS, RequestSource
from app.models.task import Task
from app.models.user import Merchant
from app.services.audit_service import write_audit_log


class InvalidTaskTransition(Exception):
    pass


def transition_task(
    db: Session,
    task: Task,
    new_status: TaskStatus,
    actor_user_id: uuid.UUID | None = None,
) -> Task:
    """
    The single choke point for changing task.status. Validates the move
    against TASK_STATE_TRANSITIONS and writes an AuditLog row in the same
    transaction. Caller commits.
    """
    allowed = TASK_STATE_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise InvalidTaskTransition(f"Cannot move task {task.id} from {task.status} to {new_status}")

    before = {"status": task.status.value}
    task.status = new_status
    after = {"status": task.status.value}

    write_audit_log(
        db,
        entity_type="TASK",
        entity_id=task.id,
        action="STATUS_CHANGED",
        actor_user_id=actor_user_id,
        before_state=before,
        after_state=after,
    )
    from app.services.integration_service import enqueue_farmsense_status
    enqueue_farmsense_status(db, task)
    return task


def apply_ai_extraction(db: Session, task: Task, extraction, raw_response: dict) -> Task:
    """
    Applies a validated AITaskExtraction to a DRAFT task and advances it
    through AI_PARSED -> PENDING_MERCHANT_CONFIRMATION in one go, since no
    human action happens between those two states — the merchant's review
    is the next real step (handled separately via confirm_task).
    """
    task.title = extraction.title
    task.category = extraction.category
    task.requirements = extraction.requirements
    task.complexity = extraction.complexity
    task.suggested_payout = extraction.suggested_payout
    task.ai_raw_response = raw_response
    task.service_category = extraction.service_category
    task.farm_location = extraction.farm_location.model_dump(mode="json", exclude_none=True) if extraction.farm_location else None
    task.agricultural_details = extraction.agricultural_details.model_dump(mode="json", exclude_none=True)
    if extraction.service_category and extraction.service_category.value == "TRANSPORT" and not task.logistics_handoff_reference:
        from app.services.integration_service import logistics_reference
        task.logistics_handoff_reference = logistics_reference(task.id)

    transition_task(db, task, TaskStatus.AI_PARSED)
    transition_task(db, task, TaskStatus.PENDING_MERCHANT_CONFIRMATION)
    return task


def confirm_task(db: Session, task: Task, actor_user_id: uuid.UUID, final_payout: float | None = None) -> Task:
    if final_payout is not None:
        task.final_payout = final_payout
    else:
        task.final_payout = task.suggested_payout
    transition_task(db, task, TaskStatus.PUBLISHED, actor_user_id=actor_user_id)
    return task


def cancel_task(db: Session, task: Task, actor_user_id: uuid.UUID | None = None) -> Task:
    transition_task(db, task, TaskStatus.CANCELLED, actor_user_id=actor_user_id)
    return task


def create_draft_task_from_whatsapp(
    db: Session,
    merchant_id: uuid.UUID,
    source_whatsapp_message_id: str,
    requirements: str | None = None,
    source_audio_key: str | None = None,
) -> Task:
    task = Task(
        merchant_id=merchant_id,
        requester_user_id=db.get(Merchant, merchant_id).user_id,
        request_source=RequestSource.WHATSAPP,
        status=TaskStatus.DRAFT,
        requirements=requirements,
        source_whatsapp_message_id=source_whatsapp_message_id,
        source_audio_key=source_audio_key,
    )
    db.add(task)
    db.flush()

    write_audit_log(
        db,
        entity_type="TASK",
        entity_id=task.id,
        action="CREATED_FROM_WHATSAPP",
        actor_user_id=None,
        before_state=None,
        after_state={"status": task.status.value},
    )
    return task
