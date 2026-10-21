import os
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, User, Vacation
from app.security import hash_password


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'vacations.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        password_hash = hash_password("test-pass")
        db.add_all([
            User(full_name="Иванов Иван", login="engineer", role="engineer", password_hash=password_hash),
            User(full_name="Петров Пётр", login="manager", role="manager", password_hash=password_hash),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def client(sessions):
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def login(client, name="manager"):
    response = client.post("/login", data={"login": name, "password": "test-pass"},
                           follow_redirects=False)
    assert response.status_code == 303


def period(**changes):
    return {"user_id": "1", "start_date": "2026-12-28", "end_date": "2027-01-10",
            "year": "2026", **changes}


class CalendarDays(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.days = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "button" and "vacation-day" in attrs.get("class", "").split():
            self.days[attrs["data-label"]] = attrs


def test_vacations_require_manager(client):
    assert client.get("/vacations", follow_redirects=False).status_code == 303
    assert client.post("/vacations", data=period(), follow_redirects=False).status_code == 303
    login(client, "engineer")
    assert client.get("/vacations").status_code == 403
    assert client.post("/vacations", data=period()).status_code == 403
    assert client.post("/vacations/1", data=period()).status_code == 403
    assert client.post("/vacations/1/delete").status_code == 403
    assert 'href="/vacations"' not in client.get("/reports/new").text


def test_vacation_lifecycle_and_cross_year_calendar(client, sessions):
    login(client)
    empty = client.get("/vacations?year=2026")
    assert empty.status_code == 200
    assert 'class="here" href="/vacations">Отпуска' in empty.text
    assert empty.text.count('<section class="vacation-month"') == 12
    assert "пока не добавлены" in empty.text

    saved = client.post("/vacations", data=period(), follow_redirects=False)
    assert saved.status_code == 303, saved.text
    with sessions() as db:
        vacation = db.scalar(select(Vacation))
        vacation_id = vacation.id
        assert vacation.days == 14
        assert vacation.user_id == 1

    december = CalendarDays(client.get("/vacations?year=2026").text).days
    assert len(december) == 365
    assert december["28.12.2026"]["data-names"] == "Иванов Иван"
    assert december["27.12.2026"]["data-names"] == ""
    january_page = client.get("/vacations?year=2027")
    january = CalendarDays(january_page.text).days
    assert january["01.01.2027"]["data-names"] == "Иванов Иван"
    assert january["10.01.2027"]["data-names"] == "Иванов Иван"
    assert january["11.01.2027"]["data-names"] == ""
    assert "28.12.2026 — 10.01.2027" in january_page.text

    edit = client.get(f"/vacations?year=2027&edit={vacation_id}")
    assert edit.status_code == 200
    assert 'value="2026-12-28"' in edit.text
    updated = client.post(f"/vacations/{vacation_id}", data=period(end_date="2027-01-12"),
                           follow_redirects=False)
    assert updated.status_code == 303, updated.text
    with sessions() as db:
        assert db.get(Vacation, vacation_id).end_date == date(2027, 1, 12)

    deleted = client.post(f"/vacations/{vacation_id}/delete", data={"year": "2027"},
                           follow_redirects=False)
    assert deleted.status_code == 303
    assert "year=2027" in deleted.headers["location"]
    with sessions() as db:
        assert db.get(Vacation, vacation_id) is None
        history = list(db.scalars(select(AuditLog).where(AuditLog.entity == "vacation")
                                  .order_by(AuditLog.id)))
        assert [item.action for item in history] == ["create", "update", "delete"]
        assert all(item.actor_id == 2 for item in history)
        assert history[1].payload["before"]["end_date"] == "2027-01-10"
        assert history[2].payload["before"]["end_date"] == "2027-01-12"
    assert CalendarDays(client.get("/vacations?year=2027").text).days["01.01.2027"]["data-names"] == ""


@pytest.mark.parametrize("changes, error", [
    ({"user_id": "999"}, "Выберите сотрудника"),
    ({"user_id": "wrong"}, "Выберите сотрудника"),
    ({"start_date": ""}, "дату начала"),
    ({"start_date": "2026-02-30"}, "дату начала"),
    ({"end_date": "wrong"}, "дату окончания"),
    ({"end_date": "2026-12-27"}, "раньше начала"),
])
def test_invalid_vacations_do_not_write(client, sessions, changes, error):
    login(client)
    response = client.post("/vacations", data=period(**changes))
    assert response.status_code == 400
    assert error in response.text
    assert 'value="2026-12-28"' in response.text or "start_date" in changes
    with sessions() as db:
        assert db.scalar(select(Vacation)) is None
        assert db.scalar(select(AuditLog)) is None


def test_vacation_overlaps_and_failed_update(client, sessions):
    login(client)
    assert client.post("/vacations", data=period(), follow_redirects=False).status_code == 303
    overlapping = period(start_date="2027-01-10", end_date="2027-01-20")
    rejected = client.post("/vacations", data=overlapping)
    assert rejected.status_code == 400
    assert "пересекающийся" in rejected.text
    # Другой сотрудник может отдыхать одновременно; соседние периоды допустимы.
    assert client.post("/vacations", data={**overlapping, "user_id": "2"},
                       follow_redirects=False).status_code == 303
    assert client.post("/vacations", data=period(start_date="2027-01-11", end_date="2027-01-20"),
                       follow_redirects=False).status_code == 303
    with sessions() as db:
        last = db.scalar(select(Vacation).order_by(Vacation.id.desc()))
        last_id = last.id
    rejected_update = client.post(f"/vacations/{last_id}", data=overlapping)
    assert rejected_update.status_code == 400
    with sessions() as db:
        assert db.get(Vacation, last_id).start_date == date(2027, 1, 11)
        assert len(list(db.scalars(select(AuditLog)))) == 3
    both = CalendarDays(client.get("/vacations?year=2027").text).days["10.01.2027"]
    assert both["data-names"] == "Иванов Иван, Петров Пётр"


def test_vacation_years_and_missing_period(client):
    login(client)
    leap = CalendarDays(client.get("/vacations?year=2028").text).days
    assert len(leap) == 366
    assert "29.02.2028" in leap
    for year in ("wrong", "0", "10000", "1", "9999"):
        assert client.get(f"/vacations?year={year}").status_code == 200
    assert client.get("/vacations?edit=wrong").status_code == 404
    assert client.post("/vacations/999", data=period()).status_code == 404
    assert client.post("/vacations/999/delete").status_code == 404


def test_vacation_migration_preserves_existing_tables(tmp_path):
    database = tmp_path / "migration.db"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables
                                            if table.name != "vacations"])
    with engine.begin() as connection:
        connection.execute(User.__table__.insert(), {"id": 1, "full_name": "Сотрудник",
                           "login": "existing", "password_hash": "hash", "role": "engineer"})
    environment = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"}
    root = Path(__file__).resolve().parents[1]
    for args in (("stamp", "0005"), ("upgrade", "head")):
        result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root,
                                env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    with engine.begin() as connection:
        connection.execute(Vacation.__table__.insert(), {"user_id": 1,
                           "start_date": date(2026, 6, 1), "end_date": date(2026, 6, 14)})
        assert connection.scalar(select(Vacation.id)) == 1
        assert connection.scalar(select(User.login)) == "existing"
    result = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0005"],
                            cwd=root, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        assert connection.scalar(select(User.login)) == "existing"
    engine.dispose()
