"""Выбор бинго в строке отчёта

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("report_items", sa.Column("bingo", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("report_items", "bingo")
