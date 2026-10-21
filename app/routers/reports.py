import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user, manager_only
from ..models import Report, User
from ..services import reports as svc
from ..services.export import build_workbook, export_filename
from ..templating import templates

router = APIRouter()


def _nav(user: User, first: date) -> dict:
    return {
        "user": user,
        "month": f"{first:%Y-%m}",
        "month_label": svc.month_label(first),
        "prev_month": f"{svc.shift_month(first, -1):%Y-%m}",
        "next_month": f"{svc.shift_month(first, 1):%Y-%m}",
    }


@router.get("/")
def home(user: User = Depends(current_user)):
    """Руководитель отчёты только смотрит, поэтому его главная — сводка."""
    return RedirectResponse(
        "/reports" if user.is_manager else "/reports/new", status_code=303
    )


@router.get("/reports/new")
def new_report(
    request: Request,
    date_param: str | None = Query(None, alias="date"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.is_manager:
        return RedirectResponse("/reports", status_code=303)

    report_date = svc.parse_date(date_param)
    report = svc.get_report(db, user.id, report_date)
    rows = (
        [
            {
                "task_title": item.task_title,
                "hours": item.hours,
                "ue": item.ue,
                "task_url": item.task_url,
                "bingo": json.dumps(item.bingo) if item.bingo else "",
                "comment": item.comment,
            }
            for item in report.items
        ]
        if report
        else []
    )
    next_date = report_date + timedelta(days=1)
    return templates.TemplateResponse(
        request,
        "report_form.html",
        {
            "user": user,
            "report_date": report_date,
            "prev_date": report_date - timedelta(days=1),
            "next_date": next_date if next_date <= svc.today() else None,
            "today": svc.today(),
            "rows": rows,
            "editable": svc.can_edit(user, report_date),
            "existing": report is not None,
            "task_suggestions": svc.month_task_titles(db, user.id, report_date),
            "bingo": svc.BINGO_FACTORS,
            "errors": [],
            "warning": None,
        },
    )


@router.post("/reports")
async def save_report(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.is_manager:
        return RedirectResponse("/reports", status_code=303)

    form = await request.form()
    report_date = svc.parse_date(form.get("report_date"))

    if not svc.can_edit(user, report_date):
        raise HTTPException(status_code=403, detail="Этот день уже закрыт для правок.")

    items, errors = svc.parse_items(
        [str(value) for value in form.getlist("task_title")],
        [str(value) for value in form.getlist("hours")],
        [str(value) for value in form.getlist("comment")],
        [str(value) for value in form.getlist("ue")],
        [str(value) for value in form.getlist("task_url")],
        [str(value) for value in form.getlist("bingo")],
    )

    if errors:
        rows = [
            {
                "task_title": form.getlist("task_title")[index],
                "hours": form.getlist("hours")[index],
                "ue": form.getlist("ue")[index]
                if index < len(form.getlist("ue"))
                else "",
                "task_url": form.getlist("task_url")[index]
                if index < len(form.getlist("task_url"))
                else "",
                "bingo": form.getlist("bingo")[index]
                if index < len(form.getlist("bingo"))
                else "",
                "comment": form.getlist("comment")[index]
                if index < len(form.getlist("comment"))
                else "",
            }
            for index in range(len(form.getlist("task_title")))
        ]
        return templates.TemplateResponse(
            request,
            "report_form.html",
            {
                "user": user,
                "report_date": report_date,
                "prev_date": report_date - timedelta(days=1),
                "next_date": (
                    report_date + timedelta(days=1)
                    if report_date + timedelta(days=1) <= svc.today()
                    else None
                ),
                "today": svc.today(),
                "rows": rows,
                "editable": True,
                "existing": svc.get_report(db, user.id, report_date) is not None,
                "task_suggestions": svc.month_task_titles(db, user.id, report_date),
                "bingo": svc.BINGO_FACTORS,
                "errors": errors,
                "warning": None,
            },
            status_code=400,
        )

    svc.save_report(db, owner=user, report_date=report_date, items=items, actor=user)
    return RedirectResponse(
        f"/reports/my?month={report_date:%Y-%m}&saved={report_date:%Y-%m-%d}",
        status_code=303,
    )


def _render_my_month(
    request: Request,
    user: User,
    db: Session,
    first: date,
    saved: str | None = None,
    ue_saved: int | None = None,
    errors: list[str] | None = None,
    ue_raw: dict[int, str] | None = None,
    status_code: int = 200,
):
    reports = svc.month_reports(db, first, user_id=user.id)
    days = svc.month_days(first, reports)
    return templates.TemplateResponse(
        request,
        "my_reports.html",
        {
            **_nav(user, first),
            "weeks": svc.month_weeks(days),
            "total_hours": sum((report.total_hours for report in reports), start=0),
            "total_ue": sum((report.total_ue for report in reports), start=0),
            "saved": saved,
            "ue_saved": ue_saved,
            "errors": errors or [],
            "ue_raw": ue_raw or {},
        },
        status_code=status_code,
    )


@router.get("/reports/my")
def my_reports(
    request: Request,
    month: str | None = None,
    saved: str | None = None,
    ue_saved: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.is_manager:
        return RedirectResponse("/reports", status_code=303)

    return _render_my_month(
        request, user, db, svc.parse_month(month), saved=saved, ue_saved=ue_saved
    )


@router.post("/reports/my/ue")
async def save_month_ue(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """УЕ правятся из месяца в любой день, окно редактирования тут не действует."""
    if user.is_manager:
        return RedirectResponse("/reports", status_code=303)

    form = await request.form()
    first = svc.parse_month(str(form.get("month") or ""))

    values: dict[int, str] = {}
    raw_ue = [str(value) for value in form.getlist("ue")]
    for index, raw_id in enumerate(form.getlist("item_id")):
        item_id = svc.parse_id(str(raw_id))
        if item_id is not None:
            values[item_id] = raw_ue[index] if index < len(raw_ue) else ""

    try:
        changed, errors = svc.set_month_ue(db, owner=user, values=values, actor=user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Чужие задачи править нельзя.")

    if errors:
        return _render_my_month(
            request,
            user,
            db,
            first,
            errors=errors,
            ue_raw=values,
            status_code=400,
        )

    return RedirectResponse(
        f"/reports/my?month={first:%Y-%m}&ue_saved={changed}", status_code=303
    )


@router.get("/reports")
def overview(
    request: Request,
    month: str | None = None,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    """Сводный по отделу: месяц выбирается как в «моём месяце», сотрудник раскрывается в дни."""
    first = svc.parse_month(month)
    rows = svc.month_by_employee(db, first, svc.active_engineers(db))

    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            **_nav(manager, first),
            "rows": rows,
            "reported": sum(1 for row in rows if row["days"]),
            "total_hours": sum((row["hours"] for row in rows), start=0),
            "total_ue": sum((row["ue"] for row in rows), start=0),
        },
    )


@router.get("/reports/export.xlsx")
def export(
    month: str | None = None,
    user_id: str | None = None,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    first = svc.parse_month(month)
    reports = svc.month_reports(db, first, user_id=svc.parse_user_id(user_id))
    payload = build_workbook(first, reports)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(first)}"'
        },
    )


@router.get("/reports/{report_id}")
def report_detail(
    request: Request,
    report_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # адрес разбираем сами: «/reports/что-угодно» должно давать 404, а не ошибку разбора
    number = svc.parse_id(report_id)
    report = (
        db.query(Report)
        .options(selectinload(Report.items), selectinload(Report.user))
        .filter(Report.id == number)
        .one_or_none()
        if number is not None
        else None
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Отчёт не найден.")
    if report.user_id != user.id and not user.is_manager:
        raise HTTPException(status_code=403, detail="Чужой отчёт недоступен.")

    return templates.TemplateResponse(
        request,
        "report_detail.html",
        {
            "user": user,
            "report": report,
            "history": svc.report_history(db, report.id),
            "editable": report.user_id == user.id and svc.can_edit(user, report.report_date),
        },
    )
