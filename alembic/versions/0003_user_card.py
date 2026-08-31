"""Должность и подотдел в карточке сотрудника

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("position", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("subdepartment", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "subdepartment")
    op.drop_column("users", "position")
