"""canonical cross-platform IDs and integration contract

Revision ID: 4a7b82c3d5e6
Revises: 3f6a91b2c4d5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "4a7b82c3d5e6"
down_revision = "3f6a91b2c4d5"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE webhook_source ADD VALUE IF NOT EXISTS 'LOGISTICS'")
    op.add_column("tasks", sa.Column("integration_idempotency_key", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("farmsense_request_id", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("marketplace_request_id", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("logistics_delivery_id", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("logistics_quotes", postgresql.JSONB(), nullable=True))
    op.add_column("tasks", sa.Column("selected_logistics_quote_id", sa.String(255), nullable=True))
    op.execute("""
        UPDATE tasks
        SET farmsense_request_id = external_request_id,
            marketplace_request_id = id::text
        WHERE request_source = 'FARMSENSE_APP'
    """)
    op.create_unique_constraint(
        "uq_tasks_source_idempotency_key", "tasks", ["request_source", "integration_idempotency_key"]
    )
    op.create_index("ix_tasks_farmsense_request_id", "tasks", ["farmsense_request_id"])
    op.create_index("ix_tasks_marketplace_request_id", "tasks", ["marketplace_request_id"], unique=True)
    op.create_index("ix_tasks_logistics_delivery_id", "tasks", ["logistics_delivery_id"], unique=True)


def downgrade():
    op.drop_index("ix_tasks_logistics_delivery_id", table_name="tasks")
    op.drop_index("ix_tasks_marketplace_request_id", table_name="tasks")
    op.drop_index("ix_tasks_farmsense_request_id", table_name="tasks")
    op.drop_constraint("uq_tasks_source_idempotency_key", "tasks", type_="unique")
    for column in (
        "selected_logistics_quote_id", "logistics_quotes", "logistics_delivery_id",
        "marketplace_request_id", "farmsense_request_id", "integration_idempotency_key",
    ):
        op.drop_column("tasks", column)
    # PostgreSQL enum values are intentionally retained on downgrade.
