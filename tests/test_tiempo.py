"""Huso horario y formato de fecha del ecosistema: UTC-3 fijo y `dd-mm-aaaa`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.tiempo import TZ, ahora, formatear_fecha, formatear_fecha_hora, hoy


def test_ahora_viene_en_utc_menos_3():
    assert ahora().utcoffset() == timedelta(hours=-3)


def test_no_hay_horario_de_verano():
    """Argentina no lo usa. En enero y en julio el offset tiene que ser el mismo:
    es lo que distingue `America/Argentina/Buenos_Aires` de una zona con DST."""
    enero = datetime(2026, 1, 15, 12, tzinfo=TZ).utcoffset()
    julio = datetime(2026, 7, 15, 12, tzinfo=TZ).utcoffset()
    assert enero == julio == timedelta(hours=-3)


def test_formato_de_fecha():
    assert formatear_fecha(date(2026, 8, 18)) == "18-08-2026"
    assert formatear_fecha(None) == ""


def test_un_naive_se_lee_como_utc_y_puede_cambiar_de_dia():
    """El caso que distingue convertir de no convertir.

    01:30 UTC del 18 es todavía el 17 a las 22:30 en Argentina. Si la conversión
    se cayera, saldría `18-08-2026 01:30`: el test se pone rojo en el día, no
    sólo en la hora. Con un mediodía no se notaría la diferencia.
    """
    assert formatear_fecha_hora(datetime(2026, 8, 18, 1, 30)) == "17-08-2026 22:30"


def test_un_aware_se_convierte_a_local():
    assert formatear_fecha_hora(datetime(2026, 8, 18, 1, 30, tzinfo=UTC)) == (
        "17-08-2026 22:30"
    )


def test_sin_valor_no_se_inventa_fecha():
    assert formatear_fecha_hora(None) == ""


def test_hoy_es_la_fecha_local():
    assert hoy() == ahora().date()
