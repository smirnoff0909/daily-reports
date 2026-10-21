from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .deps import AuthRequired, Forbidden
from .routers import auth, reports, staff, vacations
from .templating import templates

app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="dr_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.cookie_secure,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(staff.router)
app.include_router(vacations.router)


@app.exception_handler(AuthRequired)
def on_auth_required(request: Request, exc: AuthRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(Forbidden)
def on_forbidden(request: Request, exc: Forbidden):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"code": 403, "message": "Этот раздел доступен только руководителю."},
        status_code=403,
    )


@app.exception_handler(StarletteHTTPException)
def on_http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        message = "Страница не найдена."
    else:
        message = exc.detail if isinstance(exc.detail, str) else "Что-то пошло не так."
    return templates.TemplateResponse(
        request,
        "error.html",
        {"code": exc.status_code, "message": message},
        status_code=exc.status_code,
    )


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}
