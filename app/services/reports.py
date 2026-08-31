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

UE_LIMIT = Decimal("9999.99")
UE_HOURS_PER_UNIT = Decimal("8")   # стандарт: одна УЕ — это восемь часов


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


def parse_id(raw: str | None) -> int | None:
    """Номер из строки запроса или формы. Пусто и мусор -> None."""
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def parse_user_id(raw: str | None) -> int | None:
    """Пустое значение фильтра ('все') и мусор -> None, то есть без фильтра."""
    return parse_id(raw)


def parse_ue(raw: str | None) -> tuple[Decimal | None, str | None]:
    """Пустое поле — УЕ ещё не проставлены. Возвращает (значение, ошибку)."""
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None, None
    try:
        value = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None, "УЕ указаны не числом."
    if value < 0:
        return None, "УЕ не могут быть меньше нуля."
    if value > UE_LIMIT:
        return None, f"УЕ не могут быть больше {UE_LIMIT:g}."
    return value, None


def parse_task_url(raw: str | None) -> tuple[str | None, str | None]:
    """Ссылка на задачу. Возвращает (значение, ошибку).

    Адрес уходит в href, поэтому пускаем только http и https: со схемой вроде
    javascript: ссылка стала бы способом выполнить чужой код в чужом браузере.
    Адрес без схемы дополняем https:// — так удобнее вставлять из адресной строки.
    """
    text = (raw or "").strip()
    if not text:
        return None, None
    if len(text) > 500:
        return None, "ссылка длиннее 500 символов."
    if "://" in text:
        scheme = text.split("://", 1)[0].lower()
        if scheme not in {"http", "https"}:
            return None, "ссылка должна начинаться с http:// или https://."
    elif text.lower().startswith(("javascript:", "data:", "vbscript:", "file:")):
        return None, "ссылка должна начинаться с http:// или https://."
    else:
        text = f"https://{text}"
    return text, None


def default_ue(hours: Decimal) -> Decimal:
    """Стандартный расчёт: УЕ = часы / 8. Введённое вручную значение важнее."""
    return (hours / UE_HOURS_PER_UNIT).quantize(Decimal("0.01"))


def can_edit(user: User, report_date: date) -> bool:
    """Свой отчёт правится внутри окна, руководитель правит без ограничений."""
    if report_date > today():
        return False
    if user.is_manager:
        return True
    return (today() - report_date).days <= settings.edit_window_days


def parse_items(
    titles: list[str],
    hours: list[str],
    comments: list[str],
    ues: list[str] | None = None,
    urls: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Разбирает строки формы. Возвращает (строки, ошибки)."""
    items: list[dict] = []
    errors: list[str] = []

    for index, raw_title in enumerate(titles):
        title = raw_title.strip()
        raw_hours = hours[index].strip() if index < len(hours) else ""
        comment = comments[index].strip() if index < len(comments) else ""
        raw_ue = ues[index].strip() if ues and index < len(ues) else ""
        raw_url = urls[index].strip() if urls and index < len(urls) else ""

        if not title and not raw_hours and not raw_ue and not raw_url:
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

        ue, ue_error = parse_ue(raw_ue)
        if ue_error:
            errors.append(f"{line}: {ue_error}")
            continue

        if ue is None:
            ue = default_ue(value)   # поле оставили пустым — считаем по стандарту

        task_url, url_error = parse_task_url(raw_url)
        if url_error:
            errors.append(f"{line}: {url_error}")
            continue

        items.append(
            {
                "position": len(items),
                "task_title": title,
                "hours": value,
                "ue": ue,
                "task_url": task_url,
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
                        "ue": None if item["ue"] is None else str(item["ue"]),
                        "task_url": item["task_url"],
                        "comment": item["comment"],
                    }
                    for item in items
                ],
                "total_hours": str(sum((i["hours"] for i in items), Decimal("0"))),
                "total_ue": str(
                    sum((i["ue"] or Decimal("0") for i in items), Decimal("0"))
                ),
            },
        )
    )
    db.commit()
    db.refresh(report)
    return report


def set_month_ue(
    db: Session, owner: User, values: dict[int, str], actor: User
) -> tuple[int, list[str]]:
    """Правка УЕ из месяца: окно редактирования здесь не действует.

    Значения проверяются целиком, и если хоть одно неверно — не пишем ничего.
    Пустое поле снимает ранее проставленные УЕ. Возвращает (сколько изменено, ошибки).
    """
    if not values:
        return 0, []

    items = list(
        db.scalars(
            select(ReportItem)
            .options(selectinload(ReportItem.report))
            .where(ReportItem.id.in_(values.keys()))
        )
    )
    by_id = {item.id: item for item in items}
    if len(by_id) != len(values):
        return 0, ["Часть задач уже не существует — обновите страницу."]

    errors: list[str] = []
    planned: dict[int, Decimal | None] = {}
    for item_id, raw in values.items():
        item = by_id[item_id]
        if item.report.user_id != owner.id:
            raise PermissionError("Чужие задачи править нельзя.")
        ue, error = parse_ue(raw)
        if error:
            errors.append(f"«{item.task_title}»: {error}")
            continue
        if ue != item.ue:
            planned[item_id] = ue

    if errors:
        return 0, errors
    if not planned:
        return 0, []

    touched: dict[int, list[dict]] = {}
    for item_id, ue in planned.items():
        item = by_id[item_id]
        touched.setdefault(item.report_id, []).append(
            {
                "task_title": item.task_title,
                "ue_before": None if item.ue is None else str(item.ue),
                "ue": None if ue is None else str(ue),
            }
        )
        item.ue = ue

    db.flush()
    for report_id, changes in touched.items():
        report = db.get(Report, report_id)
        db.add(
            AuditLog(
                actor_id=actor.id,
                entity="report",
                entity_id=report_id,
                action="ue",
                payload={
                    "report_date": report.report_date.isoformat(),
                    "owner_id": owner.id,
                    "items": changes,
                    "total_ue": str(report.total_ue),
                },
            )
        )
    db.commit()
    return len(planned), []


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


def month_weeks(days: list[dict]) -> list[dict]:
    """Дни месяца, разложенные по неделям с понедельника. Будущие дни не показываем."""
    weeks: list[dict] = []
    for day in days:
        if day["is_future"]:
            continue
        if not weeks or day["date"].weekday() == 0:
            weeks.append(
                {"days": [], "hours": Decimal("0"), "ue": Decimal("0"), "current": False}
            )
        week = weeks[-1]
        week["days"].append(day)
        if day["report"] is not None:
            week["hours"] += day["report"].total_hours
            week["ue"] += day["report"].total_ue
        if day["date"] == today():
            week["current"] = True

    for number, week in enumerate(weeks, start=1):
        week["number"] = number
        week["first"] = week["days"][0]["date"]
        week["last"] = week["days"][-1]["date"]
        week["filled"] = sum(1 for day in week["days"] if day["report"] is not None)
        week["missing"] = sum(1 for day in week["days"] if day["is_missing"])
    return weeks


def month_by_employee(db: Session, first: date, employees: list[User]) -> list[dict]:
    """Сотрудники месяца: итоги и дни с задачами внутри.

    Активные сотрудники попадают в список даже без отчётов — так видно, кто не сдал.
    """
    rows: dict[int, dict] = {
        employee.id: {
            "user": employee,
            "days": [],
            "hours": Decimal("0"),
            "ue": Decimal("0"),
            "tasks": 0,
        }
        for employee in employees
    }
    for report in month_reports(db, first):
        row = rows.get(report.user_id)
        if row is None:  # отчёты отключённого сотрудника тоже показываем
            row = rows[report.user_id] = {
                "user": report.user,
                "days": [],
                "hours": Decimal("0"),
                "ue": Decimal("0"),
                "tasks": 0,
            }
        row["days"].append(report)
        row["hours"] += report.total_hours
        row["ue"] += report.total_ue
        row["tasks"] += len(report.items)

    for row in rows.values():
        row["days"].sort(key=lambda report: report.report_date)
    return sorted(rows.values(), key=lambda row: row["user"].full_name)


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


def active_engineers(db: Session) -> list[User]:
    """Кого ждём в сводке. Руководитель отчёты не заполняет, пустой строки по нему не нужно."""
    return [user for user in active_users(db) if not user.is_manager]


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
