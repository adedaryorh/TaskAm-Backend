import uuid

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def write_audit_log(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> AuditLog:
    """
    Adds an AuditLog row to the given session WITHOUT committing. The caller
    is responsible for committing as part of its own transaction, so the
    audit entry and the state change it describes are atomic together.
    """
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        before_state=before_state,
        after_state=after_state,
    )
    db.add(entry)
    return entry
