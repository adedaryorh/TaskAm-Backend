"""add PAYSTACK value to webhook_source enum

Revision ID: efaa893f5971
Revises: cafcc6b831f3
Create Date: 2026-07-14 05:36:07.455622

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'efaa893f5971'
down_revision: Union[str, None] = 'cafcc6b831f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres requires ADD VALUE to run outside a transaction block in
    # older versions; on PG12+ it's transaction-safe but still can't be
    # used in the same transaction as a query referencing the new value,
    # which is fine here since this migration only adds the value.
    op.execute("ALTER TYPE webhook_source ADD VALUE IF NOT EXISTS 'PAYSTACK'")


def downgrade() -> None:
    # Postgres does not support removing enum values directly. Downgrading
    # this would require recreating the type without 'PAYSTACK' and
    # remapping any rows using it — not implemented, matching common
    # practice for additive enum migrations.
    pass
