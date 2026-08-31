from datetime import date

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
    return RedirectResponse("/reports/new", status_code=303)


@router.get("/reports/new")
def new_report(
    request: Request,
    date_param: str | None = Query(None, alias="date"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    report_date = svc.parse_date(date_param)
    report = svc.get_report(db, user.id, report_date)
    rows = (
        [
            {"task_title": item.task_title, "hours": item.hours, "comment": item.comment}
            for item in report.items
        ]
        if report
        else []
    )
    return templates.TemplateResponse(
        request,
        "report_form.html",
        {
            "user": user,
            "report_date": report_date,
            "today": svc.today(),
            "rows": rows,
            "editable": svc.can_edit(user, report_date),
            "edit_window_days": svc.settings.edit_window_days,
            "existing": report is not None,
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
    form = await request.form()
    report_date = svc.parse_date(form.get("report_date"))

    if not svc.can_edit(user, report_date):
        raise HTTPException(status_code=403, detail="Этот день уже закрыт для правок.")

    items, errors = svc.parse_items(
        [str(value) for value in form.getlist("task_title")],
        [str(value) for value in form.getlist("hours")],
        [str(value) for value in form.getlist("comment")],
    )

    if errors:
        rows = [
            {
                "task_title": form.getlist("task_title")[index],
                "hours": form.getlist("hours")[index],
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
                "today": svc.today(),
                "rows": rows,
                "editable": True,
                "edit_window_days": svc.settings.edit_window_days,
                "existing": svc.get_report(db, user.id, report_date) is not None,
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


@router.get("/reports/my")
def my_reports(
    request: Request,
    month: str | None = None,
    saved: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    first = svc.parse_month(month)
    reports = svc.month_reports(db, first, user_id=user.id)
    days = svc.month_days(first, reports)
    total = sum((report.total_hours for report in reports), start=0)
    return templates.TemplateResponse(
        request,
        "my_reports.html",
        {
            **_nav(user, first),
            "days": days,
            "total_hours": total,
            "filled_days": len(reports),
            "missing_days": sum(1 for day in days if day["is_missing"]),
            "saved": saved,
        },
    )


@router.get("/reports")
def overview(
    request: Request,
    month: str | None = None,
    user_id: int | None = None,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    first = svc.parse_month(month)
    reports = svc.month_reports(db, first, user_id=user_id)
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            **_nav(manager, first),
            "reports": reports,
            "totals": svc.totals_by_user(reports),
            "employees": svc.active_users(db),
            "selected_user_id": user_id,
            "total_hours": sum((report.total_hours for report in reports), start=0),
        },
    )


@router.get("/reports/export.xlsx")
def export(
    month: str | None = None,
    user_id: int | None = None,
    manager: User = Depends(manager_only),
    db: Session = Depends(get_db),
):
    first = svc.parse_month(month)
    reports = svc.month_reports(db, first, user_id=user_id)
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
    report_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    report = (
        db.query(Report)
        .options(selectinload(Report.items), selectinload(Report.user))
        .filter(Report.id == report_id)
        .one_or_none()
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
