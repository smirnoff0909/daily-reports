"""Дымовой тест на SQLite: вход, сохранение отчёта, месяц, сводка, экспорт."""
import os
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///" + tempfile.mkstemp(suffix=".db")[1])
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("COOKIE_SECURE", "false")

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

Base.metadata.create_all(engine)


def seed() -> None:
    with SessionLocal() as db:
        if db.query(User).count():
            return
        db.add_all(
            [
                User(full_name="Иванов Иван", login="ivanov", role="engineer",
                     password_hash=hash_password("engineer-pass-1")),
                User(full_name="Петров Пётр", login="petrov", role="manager",
                     password_hash=hash_password("manager-pass-1")),
            ]
        )
        db.commit()


def login(client: TestClient, login_name: str, password: str) -> None:
    response = client.post(
        "/login", data={"login": login_name, "password": password}, follow_redirects=False
    )
    assert response.status_code == 303, response.text


def test_full_flow():
    seed()
    with TestClient(app) as client:
        assert client.get("/reports/new", follow_redirects=False).status_code == 303

        login(client, "ivanov", "engineer-pass-1")
        assert client.get("/reports/new").status_code == 200

        today = date.today().isoformat()
        saved = client.post(
            "/reports",
            data={
                "report_date": today,
                "task_title": ["Замена насоса на ЦТП-4", "Обход оборудования"],
                "hours": ["4,5", "3"],
                "comment": ["Заменён подшипник", ""],
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303, saved.text

        month = client.get("/reports/my")
        assert month.status_code == 200
        assert "Замена насоса" in month.text
        assert "7,5" in month.text

        bad = client.post(
            "/reports",
            data={
                "report_date": today,
                "task_title": ["Дежурство на объекте"],
                "hours": ["30"],
                "comment": [""],
            },
        )
        assert bad.status_code == 400
        assert "24" in bad.text

        assert client.get("/reports", follow_redirects=False).status_code == 403

    with TestClient(app) as client:
        login(client, "petrov", "manager-pass-1")
        overview = client.get("/reports")
        assert overview.status_code == 200
        assert "Иванов Иван" in overview.text

        export = client.get("/reports/export.xlsx")
        assert export.status_code == 200
        assert export.content[:2] == b"PK"


def test_task_suggestions():
    """Задачи текущего месяца подсказываются в поле названия вместе со ссылкой."""
    seed()
    with TestClient(app) as client:
        login(client, "ivanov", "engineer-pass-1")

        today = date.today()
        saved = client.post(
            "/reports",
            data={
                "report_date": today.isoformat(),
                "task_title": ["Ревизия задвижки"],
                "hours": ["6"],
                "comment": [""],
                "ue": [""],
                "task_url": ["https://tracker.example/12"],
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303, saved.text

        # другой день того же месяца: подсказка должна доехать
        other = today.replace(day=1) if today.day > 1 else today
        form = client.get(f"/reports/new?date={other.isoformat()}")
        assert form.status_code == 200
        assert '<option value="Ревизия задвижки">' in form.text
        assert "https://tracker.example/12" in form.text


def test_bingo_ue():
    """Бинго ненормированных работ: пример из bingo.xlsx даёт те же 5,44 УЕ."""
    from decimal import Decimal

    from app.services import reports as svc

    hard = {"complexity": 3, "uncertainty": 8, "impact": 2, "breadth": 0}
    assert svc.bingo_ue(Decimal("32"), hard) == Decimal("5.44")
    # все факторы минимальные — обычные часы, делённые на восемь
    assert svc.bingo_ue(Decimal("8"), {}) == Decimal("1.00")

    seed()
    with TestClient(app) as client:
        login(client, "ivanov", "engineer-pass-1")
        form = client.get("/reports/new")
        assert form.status_code == 200
        assert 'id="bingo-dialog"' in form.text
        assert "Мультидисциплинарность" in form.text
