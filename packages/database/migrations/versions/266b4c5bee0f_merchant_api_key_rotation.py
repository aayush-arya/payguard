"""merchant api key rotation

Revision ID: 266b4c5bee0f
Revises: 57b34aed3928
Create Date: 2026-08-18 21:27:28.753661

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "266b4c5bee0f"
down_revision: str | None = "57b34aed3928"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column("previous_api_key_hash", sa.String(), nullable=True))
    op.add_column(
        "merchants", sa.Column("previous_api_key_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint("uq_merchants_previous_api_key_hash", "merchants", ["previous_api_key_hash"])


def downgrade() -> None:
    op.drop_constraint("uq_merchants_previous_api_key_hash", "merchants", type_="unique")
    op.drop_column("merchants", "previous_api_key_expires_at")
    op.drop_column("merchants", "previous_api_key_hash")
