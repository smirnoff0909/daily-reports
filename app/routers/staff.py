from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, manager_only
from ..models import User
from ..services import users as svc
from ..templating import templates

router = APIRouter()


def _card_page(request: Request, user: User, saved: str | None = None,
               errors: list[str] | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "role_names": svc.ROLE_NAMES,
            "min_password": svc.MIN_PASSWORD,
            "saved": saved,
            "errors": errors or [],
        },
        status_code=status_code,
    )


@router.get("/profile")
def profile(
    request: Request,
    saved: str | None = None,
    user: User = Depends(current_user),
):
    return _card_page(request, user, saved=saved)


@router.post("/profile/password")
def change_password(
    request: Request,
    current: str = Form(""),
    password: str = Form(""),
    repeat: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    errors = svc.change_own_password(db, user, current, password, repeat)
    if errors:
        return _card_page(request, user, errors=errors, status_code=400)
    return RedirectResponse("/profile?saved=password", status_code=303)


@router.get("/staff")
def staff_list(
    request: Request,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "staff_list.html",
        {
            "user": manager,
            "staff": svc.staff(db),
            "role_names": svc.ROLE_NAMES,
        },
    )


def _staff_card(request: Request, manager: User, subject: User | None, values: dict,
                errors: list[str] | None = None, saved: str | None = None,
                status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "staff_card.html",
        {
            "user": manager,
            "subject": subject,
            "values": values,
            "role_names": svc.ROLE_NAMES,
            "min_password": svc.MIN_PASSWORD,
            "errors": errors or [],
            "saved": saved,
        },
        status_code=status_code,
    )


@router.get("/staff/new")
def new_staff(
    request: Request,
    manager: User = Depends(manager_only),
):
    return _staff_card(request, manager, None, {"role": "engineer"})


@router.post("/staff/new")
async def create_staff(
    request: Request,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    values, errors = svc.parse_card(form, with_login=True)
    password = str(form.get("password") or "")
    errors += svc.check_password(password, str(form.get("repeat") or ""))
    if not errors and svc.login_taken(db, values["login"]):
        errors.append("Такой логин уже занят.")

    if errors:
        return _staff_card(request, manager, None, form, errors=errors, status_code=400)

    created = svc.create_user(db, values, password, actor=manager)
    return RedirectResponse(f"/staff/{created.id}?saved=create", status_code=303)


def _subject(db: Session, user_id: int) -> User:
    subject = svc.get_user(db, user_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден.")
    return subject


@router.get("/staff/{user_id}")
def staff_card(
    request: Request,
    user_id: int,
    saved: str | None = None,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    subject = _subject(db, user_id)
    return _staff_card(request, manager, subject, _values_of(subject), saved=saved)


def _values_of(subject: User) -> dict:
    return {
        "full_name": subject.full_name,
        "login": subject.login,
        "position": subject.position or "",
        "subdepartment": subject.subdepartment or "",
        "role": subject.role,
    }


@router.post("/staff/{user_id}")
async def save_staff_card(
    request: Request,
    user_id: int,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    subject = _subject(db, user_id)
    form = dict(await request.form())
    values, errors = svc.parse_card(form, with_login=False)
    if subject.id == manager.id and values["role"] != "manager":
        errors.append("Нельзя снять с себя роль руководителя.")
    if errors:
        return _staff_card(request, manager, subject, form, errors=errors, status_code=400)

    svc.update_card(db, subject, values, actor=manager)
    return RedirectResponse(f"/staff/{subject.id}?saved=card", status_code=303)


@router.post("/staff/{user_id}/password")
async def set_staff_password(
    request: Request,
    user_id: int,
    password: str = Form(""),
    repeat: str = Form(""),
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    subject = _subject(db, user_id)
    errors = svc.check_password(password, repeat)
    if errors:
        return _staff_card(
            request, manager, subject, _values_of(subject), errors=errors, status_code=400
        )

    svc.set_password(db, subject, password, actor=manager)
    return RedirectResponse(f"/staff/{subject.id}?saved=password", status_code=303)


@router.post("/staff/{user_id}/active")
def toggle_staff(
    user_id: int,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    subject = _subject(db, user_id)
    if subject.id == manager.id:
        raise HTTPException(status_code=400, detail="Себя отключать нельзя.")
    svc.set_active(db, subject, not subject.is_active, actor=manager)
    return RedirectResponse(f"/staff/{subject.id}?saved=active", status_code=303)
