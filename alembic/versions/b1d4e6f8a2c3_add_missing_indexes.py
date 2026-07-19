"""Add missing FK and worker-poll indexes

Postgres does not auto-index foreign keys; the worker poll predicates on
notifications/outbound_webhooks were seq-scanned every few seconds.

Revision ID: b1d4e6f8a2c3
Revises: 4a7b82c3d5e6
Create Date: 2026-07-19
"""
from alembic import op

revision = "b1d4e6f8a2c3"
down_revision = "4a7b82c3d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tasks_merchant_id", "tasks", ["merchant_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_task_claims_provider_user_id", "task_claims", ["provider_user_id"])
    op.create_index("ix_task_claims_task_id", "task_claims", ["task_id"])
    op.create_index("ix_deliverables_task_id", "deliverables", ["task_id"])
    op.create_index("ix_disputes_task_id", "disputes", ["task_id"])
    op.create_index("ix_disputes_status", "disputes", ["status"])
    # Partial indexes matching the worker poll queries exactly.
    op.create_index(
        "ix_notifications_pending",
        "notifications",
        ["next_attempt_at"],
        postgresql_where="sent = false",
    )
    op.create_index(
        "ix_outbound_webhooks_pending",
        "outbound_webhooks",
        ["next_attempt_at"],
        postgresql_where="delivered = false",
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_webhooks_pending", table_name="outbound_webhooks")
    op.drop_index("ix_notifications_pending", table_name="notifications")
    op.drop_index("ix_disputes_status", table_name="disputes")
    op.drop_index("ix_disputes_task_id", table_name="disputes")
    op.drop_index("ix_deliverables_task_id", table_name="deliverables")
    op.drop_index("ix_task_claims_task_id", table_name="task_claims")
    op.drop_index("ix_task_claims_provider_user_id", table_name="task_claims")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_merchant_id", table_name="tasks")
