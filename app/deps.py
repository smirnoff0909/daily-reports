from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


class AuthRequired(Exception):
    """Сессии нет или она устарела — отправляем на вход."""


class Forbidden(Exception):
    """Роли не хватает для этой страницы."""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("uid")
    if not user_id:
        raise AuthRequired()
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise AuthRequired()
    return user


def manager_only(user: User = Depends(current_user)) -> User:
    if not user.is_manager:
        raise Forbidden()
    return user
