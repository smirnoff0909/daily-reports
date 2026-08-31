"""Ссылка на задачу в строке отчёта

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_items", sa.Column("task_url", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("report_items", "task_url")
