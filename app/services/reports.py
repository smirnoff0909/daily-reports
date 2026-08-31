from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import AuditLog, Report, ReportItem, User

MONTH_NAMES = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]
WEEKDAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def today() -> date:
    return datetime.now(settings.tz).date()


def parse_month(raw: str | None) -> date:
    """'2026-08' -> date(2026, 8, 1). Некорректное значение -> текущий месяц."""
    if raw:
        try:
            year, month = raw.split("-")
            return date(int(year), int(month), 1)
        except (ValueError, TypeError):
            pass
    return today().replace(day=1)


def month_bounds(first: date) -> tuple[date, date]:
    last_day = calendar.monthrange(first.year, first.month)[1]
    return first, first.replace(day=last_day)


def month_label(first: date) -> str:
    return f"{MONTH_NAMES[first.month - 1]} {first.year}"


def shift_month(first: date, delta: int) -> date:
    index = first.year * 12 + (first.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def parse_date(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return today()


def can_edit(user: User, report_date: date) -> bool:
    """Свой отчёт правится внутри окна, руководитель правит без ограничений."""
    if report_date > today():
        return False
    if user.is_manager:
        return True
    return (today() - report_date).days <= settings.edit_window_days


def parse_items(
    titles: list[str], hours: list[str], comments: list[str]
) -> tuple[list[dict], list[str]]:
    """Разбирает строки формы. Возвращает (строки, ошибки)."""
    items: list[dict] = []
    errors: list[str] = []

    for index, raw_title in enumerate(titles):
        title = raw_title.strip()
        raw_hours = hours[index].strip() if index < len(hours) else ""
        comment = comments[index].strip() if index < len(comments) else ""

        if not title and not raw_hours:
            continue

        line = f"Строка {len(items) + 1}"
        if len(title) < 3:
            errors.append(f"{line}: название задачи короче трёх символов.")
            continue
        if len(title) > 200:
            errors.append(f"{line}: название задачи длиннее 200 символов.")
            continue

        try:
            value = Decimal(raw_hours.replace(",", ".")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            errors.append(f"{line}: часы указаны не числом.")
            continue
        if value <= 0:
            errors.append(f"{line}: часы должны быть больше нуля.")
            continue
        if value > Decimal("24"):
            errors.append(f"{line}: за одну задачу нельзя списать больше 24 часов.")
            continue

        items.append(
            {
                "position": len(items),
                "task_title": title,
                "hours": value,
                "comment": comment or None,
            }
        )

    if not items and not errors:
        errors.append("Добавьте хотя бы одну задачу.")

    total = sum((item["hours"] for item in items), Decimal("0"))
    if total > Decimal(str(settings.hours_hard_limit)):
        errors.append(
            f"Итого за день {total} ч — больше допустимых "
            f"{settings.hours_hard_limit:g} ч."
        )

    return items, errors


def hours_warning(items: list[dict]) -> str | None:
    total = sum((item["hours"] for item in items), Decimal("0"))
    if total > Decimal(str(settings.hours_soft_limit)):
        return f"За день набралось {total} ч. Проверьте, всё ли верно."
    return None


def get_report(db: Session, user_id: int, report_date: date) -> Report | None:
    return db.scalars(
        select(Report)
        .options(selectinload(Report.items))
        .where(Report.user_id == user_id, Report.report_date == report_date)
    ).first()


def save_report(
    db: Session, owner: User, report_date: date, items: list[dict], actor: User
) -> Report:
    report = get_report(db, owner.id, report_date)
    action = "update" if report else "create"
    if report is None:
        report = Report(user_id=owner.id, report_date=report_date)
        db.add(report)

    report.items.clear()
    db.flush()
    for item in items:
        report.items.append(ReportItem(**item))

    db.flush()
    db.add(
        AuditLog(
            actor_id=actor.id,
            entity="report",
            entity_id=report.id,
            action=action,
            payload={
                "report_date": report_date.isoformat(),
                "owner_id": owner.id,
                "items": [
                    {
                        "task_title": item["task_title"],
                        "hours": str(item["hours"]),
                        "comment": item["comment"],
                    }
                    for item in items
                ],
                "total_hours": str(sum((i["hours"] for i in items), Decimal("0"))),
            },
        )
    )
    db.commit()
    db.refresh(report)
    return report


def month_reports(
    db: Session, first: date, user_id: int | None = None
) -> list[Report]:
    start, end = month_bounds(first)
    query = (
        select(Report)
        .options(selectinload(Report.items), selectinload(Report.user))
        .where(Report.report_date >= start, Report.report_date <= end)
        .order_by(Report.report_date.desc(), Report.user_id)
    )
    if user_id:
        query = query.where(Report.user_id == user_id)
    return list(db.scalars(query))


def month_days(first: date, reports: list[Report]) -> list[dict]:
    """Дни месяца до сегодняшнего включительно + отметка пропусков."""
    start, end = month_bounds(first)
    by_date = {report.report_date: report for report in reports}
    limit = min(end, today())
    days: list[dict] = []
    current = start
    while current <= end:
        report = by_date.get(current)
        days.append(
            {
                "date": current,
                "weekday": WEEKDAY_NAMES[current.weekday()],
                "is_weekend": current.weekday() >= 5,
                "report": report,
                "is_missing": report is None
                and current <= limit
                and current.weekday() < 5,
                "is_future": current > today(),
            }
        )
        current = current.fromordinal(current.toordinal() + 1)
    return days


def totals_by_user(reports: list[Report]) -> list[dict]:
    buckets: dict[int, dict] = {}
    for report in reports:
        bucket = buckets.setdefault(
            report.user_id,
            {"user": report.user, "hours": Decimal("0"), "days": 0, "tasks": 0},
        )
        bucket["hours"] += report.total_hours
        bucket["days"] += 1
        bucket["tasks"] += len(report.items)
    return sorted(buckets.values(), key=lambda row: row["user"].full_name)


def active_users(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User).where(User.is_active.is_(True)).order_by(User.full_name)
        )
    )


def report_history(db: Session, report_id: int) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .options(selectinload(AuditLog.actor))
            .where(AuditLog.entity == "report", AuditLog.entity_id == report_id)
            .order_by(AuditLog.created_at.desc())
        )
    )
