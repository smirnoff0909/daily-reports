from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import manager_only
from ..models import User, Vacation
from ..services import vacations as svc
from ..services.users import staff
from ..templating import templates

router = APIRouter()


def _vacation(db: Session, raw_id: str) -> Vacation:
    try:
        number = int(raw_id)
    except ValueError:
        number = None
    vacation = db.get(Vacation, number) if number is not None else None
    if vacation is None:
        raise HTTPException(status_code=404, detail="Отпуск не найден.")
    return vacation


def _page(request: Request, manager: User, db: Session, year: int,
          existing: Vacation | None = None, values: dict | None = None,
          errors: list[str] | None = None, status_code: int = 200, saved: str | None = None):
    vacations = svc.year_vacations(db, year)
    months, people = svc.year_calendar(year, vacations)
    return templates.TemplateResponse(request, "vacations.html", {
        "user": manager, "year": year, "months": months, "people": people,
        "vacations": vacations, "staff": staff(db), "weekdays": svc.WEEKDAY_NAMES,
        "color_index": svc.color_index, "existing": existing,
        "values": values if values is not None else {
            "user_id": str(existing.user_id) if existing else "",
            "start_date": existing.start_date.isoformat() if existing else "",
            "end_date": existing.end_date.isoformat() if existing else "",
        },
        "errors": errors or [], "saved": saved,
    }, status_code=status_code)


@router.get("/vacations")
def vacations(request: Request, year: str | None = None, edit: str | None = None,
              saved: str | None = None, manager: User = Depends(manager_only),
              db: Session = Depends(get_db)):
    existing = _vacation(db, edit) if edit is not None else None
    return _page(request, manager, db, svc.parse_year(year), existing=existing, saved=saved)


@router.post("/vacations")
async def create_vacation(request: Request, manager: User = Depends(manager_only),
                          db: Session = Depends(get_db)):
    form = dict(await request.form())
    values, errors = svc.parse_vacation(db, form)
    if errors:
        return _page(request, manager, db, svc.parse_year(form.get("year")),
                     values=form, errors=errors, status_code=400)
    vacation = svc.save_vacation(db, values, manager)
    return RedirectResponse(f"/vacations?year={vacation.start_date.year}&saved=create", status_code=303)


@router.post("/vacations/{vacation_id}")
async def update_vacation(request: Request, vacation_id: str,
                          manager: User = Depends(manager_only), db: Session = Depends(get_db)):
    existing = _vacation(db, vacation_id)
    form = dict(await request.form())
    values, errors = svc.parse_vacation(db, form, existing)
    if errors:
        return _page(request, manager, db, svc.parse_year(form.get("year")),
                     existing=existing, values=form, errors=errors, status_code=400)
    vacation = svc.save_vacation(db, values, manager, existing)
    return RedirectResponse(f"/vacations?year={vacation.start_date.year}&saved=update", status_code=303)


@router.post("/vacations/{vacation_id}/delete")
async def delete_vacation(request: Request, vacation_id: str,
                          manager: User = Depends(manager_only), db: Session = Depends(get_db)):
    vacation = _vacation(db, vacation_id)
    form = await request.form()
    year = svc.parse_year(form.get("year"))
    svc.delete_vacation(db, vacation, manager)
    return RedirectResponse(f"/vacations?year={year}&saved=delete", status_code=303)
