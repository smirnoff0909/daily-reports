"""УЕ у строки отчёта

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("report_items", sa.Column("ue", sa.Numeric(precision=6, scale=2), nullable=True))
    op.create_check_constraint(
        "ck_items_ue", "report_items", "ue >= 0 and ue <= 9999.99"
    )


def downgrade() -> None:
    op.drop_constraint("ck_items_ue", "report_items", type_="check")
    op.drop_column("report_items", "ue")
