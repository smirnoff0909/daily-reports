"""Учётные записи: карточка сотрудника и пароли.

Роутеры сюда только передают то, что пришло из формы, и получают
готовые значения и список ошибок обычным русским текстом.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, User
from ..security import hash_password, verify_password

MIN_PASSWORD = 4
LOGIN_RE = re.compile(r"^[a-z0-9._-]{3,100}$")
ROLE_NAMES = {"engineer": "инженер", "manager": "руководитель"}


def staff(db: Session) -> list[User]:
    """Все, включая отключённых: их видно в кабинете руководителя."""
    return list(db.scalars(select(User).order_by(User.is_active.desc(), User.full_name)))


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def parse_card(form: dict, *, with_login: bool) -> tuple[dict, list[str]]:
    """Разбирает поля карточки. Возвращает (значения, ошибки)."""
    errors: list[str] = []
    full_name = (form.get("full_name") or "").strip()
    position = (form.get("position") or "").strip()
    subdepartment = (form.get("subdepartment") or "").strip()
    role = (form.get("role") or "engineer").strip()
    login = (form.get("login") or "").strip().lower()

    if len(full_name) < 3:
        errors.append("Фамилия и имя короче трёх символов.")
    if len(full_name) > 200:
        errors.append("ФИО длиннее 200 символов.")
    if len(position) > 120:
        errors.append("Должность длиннее 120 символов.")
    if len(subdepartment) > 120:
        errors.append("Подотдел длиннее 120 символов.")
    if role not in ROLE_NAMES:
        errors.append("Неизвестная роль.")
    if with_login and not LOGIN_RE.match(login):
        errors.append(
            "Логин: от трёх символов, латиница в нижнем регистре, цифры, точка, дефис."
        )

    values = {
        "full_name": full_name,
        "position": position or None,
        "subdepartment": subdepartment or None,
        "role": role,
    }
    if with_login:
        values["login"] = login
    return values, errors


def check_password(password: str, repeat: str) -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_PASSWORD:
        errors.append(f"Пароль короче {MIN_PASSWORD} символов.")
    if password != repeat:
        errors.append("Пароли не совпали.")
    return errors


def login_taken(db: Session, login: str, exclude_id: int | None = None) -> bool:
    query = select(User).where(User.login == login)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return db.scalars(query).first() is not None


def _audit(db: Session, actor: User, subject: User, action: str, payload: dict) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id,
            entity="user",
            entity_id=subject.id,
            action=action,
            payload=payload,
        )
    )


def create_user(db: Session, values: dict, password: str, actor: User) -> User:
    user = User(**values, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    _audit(db, actor, user, "create", {"login": user.login, "role": user.role})
    db.commit()
    db.refresh(user)
    return user


def update_card(db: Session, user: User, values: dict, actor: User) -> None:
    before = {
        "full_name": user.full_name,
        "position": user.position,
        "subdepartment": user.subdepartment,
        "role": user.role,
    }
    for field, value in values.items():
        setattr(user, field, value)
    _audit(db, actor, user, "card", {"before": before, "after": values})
    db.commit()


def set_password(db: Session, user: User, password: str, actor: User) -> None:
    user.password_hash = hash_password(password)
    _audit(db, actor, user, "password", {"login": user.login})
    db.commit()


def set_active(db: Session, user: User, is_active: bool, actor: User) -> None:
    """Сотрудников не удаляем, иначе разъедутся прошлые отчёты."""
    user.is_active = is_active
    _audit(db, actor, user, "enable" if is_active else "disable", {"login": user.login})
    db.commit()


def change_own_password(
    db: Session, user: User, current: str, password: str, repeat: str
) -> list[str]:
    if not verify_password(user.password_hash, current):
        return ["Текущий пароль не подошёл."]
    errors = check_password(password, repeat)
    if errors:
        return errors
    user.password_hash = hash_password(password)
    _audit(db, user, user, "password", {"login": user.login})
    db.commit()
    return []
