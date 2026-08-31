from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def fmt_hours(value) -> str:
    if value is None:
        return "—"
    quantized = Decimal(value).quantize(Decimal("0.01")).normalize()
    text = format(quantized, "f")
    return text.replace(".", ",")


def fmt_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def fmt_datetime(value) -> str:
    if not value:
        return ""
    return value.astimezone(settings.tz).strftime("%d.%m.%Y %H:%M")


templates.env.filters["hours"] = fmt_hours
templates.env.filters["date_ru"] = fmt_date
templates.env.filters["datetime_ru"] = fmt_datetime
templates.env.globals["app_name"] = settings.app_name
