from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import hash_password, needs_rehash, verify_password
from ..templating import templates

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    if request.session.get("uid"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalars(select(User).where(User.login == login.strip())).first()
    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Логин или пароль не подходят.", "login": login},
            status_code=401,
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()

    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
