"""Периоды отпусков и годовой календарь для руководителя."""
import calendar
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import AuditLog, User, Vacation
from .reports import MONTH_NAMES, WEEKDAY_NAMES, today


def parse_year(raw: str | None) -> int:
    try:
        year = int(raw or "")
        if 1 <= year <= 9999:
            return year
    except (ValueError, TypeError):
        pass
    return today().year


def year_vacations(db: Session, year: int) -> list[Vacation]:
    return list(db.scalars(
        select(Vacation)
        .options(selectinload(Vacation.user))
        .where(Vacation.start_date <= date(year, 12, 31),
               Vacation.end_date >= date(year, 1, 1))
        .order_by(Vacation.start_date, Vacation.id)
    ))


def color_index(user_id: int) -> int:
    return (user_id - 1) % 16


def year_calendar(year: int, vacations: list[Vacation]) -> tuple[list[dict], list[User]]:
    by_day: dict[date, list[User]] = {}
    people: dict[int, User] = {}
    first, last = date(year, 1, 1), date(year, 12, 31)
    for vacation in vacations:
        people[vacation.user_id] = vacation.user
        start = max(first, vacation.start_date)
        end = min(last, vacation.end_date)
        for offset in range((end - start).days + 1):
            by_day.setdefault(start + timedelta(days=offset), []).append(vacation.user)

    current_date = today()
    months = []
    for month in range(1, 13):
        weeks = []
        for numbers in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
            week = []
            for weekday, number in enumerate(numbers):
                if not number:
                    week.append(None)
                    continue
                day = date(year, month, number)
                employees = sorted(by_day.get(day, []), key=lambda user: user.full_name)
                week.append({
                    "date": day, "number": number, "weekend": weekday >= 5,
                    "today": day == current_date, "employees": employees,
                    "names": ", ".join(user.full_name for user in employees),
                })
            weeks.append(week)
        months.append({"name": MONTH_NAMES[month - 1], "weeks": weeks})
    return months, sorted(people.values(), key=lambda user: user.full_name)


def parse_vacation(db: Session, form: dict, existing: Vacation | None = None) -> tuple[dict, list[str]]:
    errors = []
    try:
        user_id = int(form.get("user_id") or "")
    except (ValueError, TypeError):
        user_id = None
    if user_id is None or db.get(User, user_id) is None:
        errors.append("Выберите сотрудника из списка.")

    dates = {}
    for field, label in (("start_date", "начала"), ("end_date", "окончания")):
        try:
            dates[field] = date.fromisoformat(str(form.get(field) or ""))
        except ValueError:
            errors.append(f"Укажите корректную дату {label} отпуска.")
    if len(dates) == 2:
        if dates["end_date"] < dates["start_date"]:
            errors.append("Окончание отпуска не может быть раньше начала.")
        elif user_id is not None:
            query = select(Vacation.id).where(
                Vacation.user_id == user_id,
                Vacation.start_date <= dates["end_date"],
                Vacation.end_date >= dates["start_date"],
            )
            if existing is not None:
                query = query.where(Vacation.id != existing.id)
            if db.scalar(query) is not None:
                errors.append("У сотрудника уже есть отпуск, пересекающийся с этими датами.")
    return {"user_id": user_id, **dates}, errors


def _values(vacation: Vacation) -> dict:
    return {"user_id": vacation.user_id,
            "start_date": vacation.start_date.isoformat(),
            "end_date": vacation.end_date.isoformat()}


def save_vacation(db: Session, values: dict, actor: User,
                  existing: Vacation | None = None) -> Vacation:
    before = _values(existing) if existing is not None else None
    vacation = existing if existing is not None else Vacation()
    for field, value in values.items():
        setattr(vacation, field, value)
    db.add(vacation)
    db.flush()
    db.add(AuditLog(actor_id=actor.id, entity="vacation", entity_id=vacation.id,
                    action="update" if before else "create",
                    payload={"before": before, "after": _values(vacation)}))
    db.commit()
    db.refresh(vacation)
    return vacation


def delete_vacation(db: Session, vacation: Vacation, actor: User) -> None:
    db.add(AuditLog(actor_id=actor.id, entity="vacation", entity_id=vacation.id,
                    action="delete", payload={"before": _values(vacation)}))
    db.delete(vacation)
    db.commit()
