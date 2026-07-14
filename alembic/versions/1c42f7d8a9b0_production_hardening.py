"""production hardening

Revision ID: 1c42f7d8a9b0
Revises: efaa893f5971
"""
from alembic import op
import sqlalchemy as sa

revision = "1c42f7d8a9b0"
down_revision = "efaa893f5971"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("students", sa.Column("payout_bank_code", sa.String(32), nullable=True))
    op.add_column("students", sa.Column("payout_account_number", sa.String(32), nullable=True))
    op.add_column("students", sa.Column("payout_account_name", sa.String(255), nullable=True))
    op.add_column("students", sa.Column("payout_recipient_code", sa.String(255), nullable=True))
    op.add_column("payments", sa.Column("settlement_reference", sa.String(255), nullable=True))
    op.add_column("payments", sa.Column("settlement_error", sa.Text(), nullable=True))
    op.drop_constraint("uq_task_claims_task_id_single_claim", "task_claims", type_="unique")
    op.create_index("uq_task_claims_active_task", "task_claims", ["task_id"], unique=True,
                    postgresql_where=sa.text("status = 'ACTIVE'"))


def downgrade():
    op.drop_index("uq_task_claims_active_task", table_name="task_claims")
    op.create_unique_constraint("uq_task_claims_task_id_single_claim", "task_claims", ["task_id"])
    op.drop_column("payments", "settlement_error")
    op.drop_column("payments", "settlement_reference")
    for column in ("payout_recipient_code", "payout_account_name", "payout_account_number", "payout_bank_code"):
        op.drop_column("students", column)
    for column in ("sent_at", "next_attempt_at", "attempts"):
        op.drop_column("notifications", column)
