"""Huso horario y formato de fecha del ecosistema.

Argentina, UTC-3 fijo, sin horario de verano. La base guarda `timestamptz`;
el formateo `dd-mm-aaaa` es sólo de presentación y vive **acá**, no repetido
por vista.

> Cuando LibraCore entre como dependencia, `ahora()` pasa a delegar en su
> `_ar_now()`. Se define local para no bloquear F1 sobre un repo privado.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def ahora() -> datetime:
    """Momento actual, consciente de zona horaria."""
    return datetime.now(TZ)


def hoy() -> date:
    return ahora().date()


def formatear_fecha(valor: date | None) -> str:
    """`dd-mm-aaaa`. Presentación únicamente: las APIs siguen en ISO 8601."""
    return valor.strftime("%d-%m-%Y") if valor else ""


def formatear_fecha_hora(valor: datetime | None) -> str:
    """`dd-mm-aaaa HH:MM`, reloj de 24 h, en hora local."""
    if valor is None:
        return ""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=ZoneInfo("UTC"))
    return valor.astimezone(TZ).strftime("%d-%m-%Y %H:%M")
