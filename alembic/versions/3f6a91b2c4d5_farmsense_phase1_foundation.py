"""FarmSense Phase 1 integration foundation

Revision ID: 3f6a91b2c4d5
Revises: 1c42f7d8a9b0
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3f6a91b2c4d5"
down_revision = "1c42f7d8a9b0"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'FARMER'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'SERVICE_PROVIDER'")

    request_source = postgresql.ENUM("TASKAM", "FARMSENSE_APP", "WHATSAPP", "ADMIN", name="request_source")
    service_category = postgresql.ENUM(
        "TRANSPORT", "LABOUR", "TRACTOR_RENTAL", "VETERINARY", "IRRIGATION",
        "WAREHOUSING", "SOIL_TESTING", "EXTENSION_SUPPORT", "OTHER", name="service_category",
    )
    request_source.create(op.get_bind(), checkfirst=True)
    service_category.create(op.get_bind(), checkfirst=True)

    op.add_column("users", sa.Column("platform_user_id", sa.String(255), nullable=True))
    op.create_index("ix_users_platform_user_id", "users", ["platform_user_id"], unique=True)

    op.create_table(
        "provider_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_types", postgresql.JSONB(), nullable=False),
        sa.Column("service_categories", postgresql.JSONB(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("payout_bank_code", sa.String(32), nullable=True),
        sa.Column("payout_account_number", sa.String(32), nullable=True),
        sa.Column("payout_account_name", sa.String(255), nullable=True),
        sa.Column("payout_recipient_code", sa.String(255), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("user_id"),
    )

    op.alter_column("tasks", "merchant_id", existing_type=postgresql.UUID(), nullable=True)
    op.add_column("tasks", sa.Column("requester_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("tasks", sa.Column("request_source", request_source, nullable=False, server_default="TASKAM"))
    op.add_column("tasks", sa.Column("external_request_id", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("internal_request_hash", sa.String(64), nullable=True))
    op.add_column("tasks", sa.Column("service_category", service_category, nullable=True))
    op.add_column("tasks", sa.Column("farm_location", postgresql.JSONB(), nullable=True))
    op.add_column("tasks", sa.Column("agricultural_details", postgresql.JSONB(), nullable=True))
    op.add_column("tasks", sa.Column("requested_start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("logistics_handoff_reference", sa.String(64), nullable=True))
    op.create_foreign_key("fk_tasks_requester_user", "tasks", "users", ["requester_user_id"], ["id"])
    op.create_unique_constraint("uq_tasks_source_external_request", "tasks", ["request_source", "external_request_id"])
    op.create_unique_constraint("uq_tasks_logistics_handoff_reference", "tasks", ["logistics_handoff_reference"])
    op.execute("""
        UPDATE tasks SET requester_user_id = merchants.user_id
        FROM merchants WHERE tasks.merchant_id = merchants.id AND tasks.requester_user_id IS NULL
    """)

    op.add_column("task_claims", sa.Column("provider_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("""
        UPDATE task_claims SET provider_user_id = students.user_id
        FROM students WHERE task_claims.student_id = students.id
    """)
    op.alter_column("task_claims", "provider_user_id", nullable=False)
    op.alter_column("task_claims", "student_id", existing_type=postgresql.UUID(), nullable=True)
    op.create_foreign_key("fk_task_claims_provider_user", "task_claims", "users", ["provider_user_id"], ["id"])

    op.add_column("deliverables", sa.Column("provider_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("""
        UPDATE deliverables SET provider_user_id = students.user_id
        FROM students WHERE deliverables.student_id = students.id
    """)
    op.alter_column("deliverables", "provider_user_id", nullable=False)
    op.alter_column("deliverables", "student_id", existing_type=postgresql.UUID(), nullable=True)
    op.create_foreign_key("fk_deliverables_provider_user", "deliverables", "users", ["provider_user_id"], ["id"])

    op.create_table(
        "outbound_webhooks",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("destination_url", sa.String(1024), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]), sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("outbound_webhooks")
    op.drop_constraint("fk_deliverables_provider_user", "deliverables", type_="foreignkey")
    op.drop_column("deliverables", "provider_user_id")
    op.alter_column("deliverables", "student_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_constraint("fk_task_claims_provider_user", "task_claims", type_="foreignkey")
    op.drop_column("task_claims", "provider_user_id")
    op.alter_column("task_claims", "student_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_constraint("uq_tasks_logistics_handoff_reference", "tasks", type_="unique")
    op.drop_constraint("uq_tasks_source_external_request", "tasks", type_="unique")
    op.drop_constraint("fk_tasks_requester_user", "tasks", type_="foreignkey")
    for column in ("logistics_handoff_reference", "requested_start_at", "agricultural_details", "farm_location",
                   "service_category", "internal_request_hash", "external_request_id", "request_source", "requester_user_id"):
        op.drop_column("tasks", column)
    op.alter_column("tasks", "merchant_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_table("provider_profiles")
    op.drop_index("ix_users_platform_user_id", table_name="users")
    op.drop_column("users", "platform_user_id")
    postgresql.ENUM(name="service_category").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="request_source").drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum role values are intentionally retained on downgrade.
