"""add firm is_active flag

Revision ID: c1e8f4a2b9d0
Revises: b7c4d8a9e2f1
Create Date: 2026-05-17 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c1e8f4a2b9d0"
down_revision = "b7c4d8a9e2f1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("firms") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )

    with op.batch_alter_table("firms") as batch_op:
        batch_op.alter_column("is_active", server_default=None)


def downgrade():
    with op.batch_alter_table("firms") as batch_op:
        batch_op.drop_column("is_active")
