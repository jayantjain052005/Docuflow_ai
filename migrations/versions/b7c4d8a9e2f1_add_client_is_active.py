"""add client is_active flag

Revision ID: b7c4d8a9e2f1
Revises: 02da0c52583a
Create Date: 2026-05-15 16:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c4d8a9e2f1"
down_revision = "02da0c52583a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )

    with op.batch_alter_table("clients") as batch_op:
        batch_op.alter_column("is_active", server_default=None)


def downgrade():
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_column("is_active")
