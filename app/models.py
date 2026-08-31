from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

PK = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('engineer','manager')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    login: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[str | None] = mapped_column(String(120))
    subdepartment: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="engineer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    reports: Mapped[list["Report"]] = relationship(back_populates="user")

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"

    @property
    def short_name(self) -> str:
        parts = self.full_name.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1][0]}."
        return self.full_name


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("user_id", "report_date", name="uq_reports_user_date"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="reports")
    items: Mapped[list["ReportItem"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ReportItem.position",
    )

    @property
    def total_hours(self) -> Decimal:
        return sum((item.hours for item in self.items), Decimal("0"))

    @property
    def total_ue(self) -> Decimal:
        """УЕ проставлены не везде — незаполненные считаем нулём."""
        return sum((item.ue or Decimal("0") for item in self.items), Decimal("0"))


class ReportItem(Base):
    __tablename__ = "report_items"
    __table_args__ = (
        CheckConstraint("hours > 0 and hours <= 24", name="ck_items_hours"),
        CheckConstraint("ue >= 0 and ue <= 9999.99", name="ck_items_ue"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_title: Mapped[str] = mapped_column(String(200), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    ue: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    task_url: Mapped[str | None] = mapped_column(String(500))
    comment: Mapped[str | None] = mapped_column(Text)

    report: Mapped[Report] = relationship(back_populates="items")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    actor: Mapped[User] = relationship()
