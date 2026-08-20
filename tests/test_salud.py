"""La sonda de salud, que es lo que mira el HEALTHCHECK del contenedor.

Se prueba en las dos direcciones. Sólo con el caso feliz, una sonda que
devolviera `{"estado": "ok"}` constante —sin tocar la base— pasaría igual, y el
contenedor se reportaría sano con PostgreSQL caído.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import obtener_sesion
from app.main import crear_app


def _app():
    """`sembrar_admin=False`: la sonda no tiene nada que ver con el usuario
    inicial, y sembrarlo obligaría a estos tests a cargar la variable
    fail-closed de `libraauth`. El login se prueba en `test_auth.py`."""
    return crear_app(sembrar_admin=False)


@pytest.fixture
def cliente(sesion):
    app = _app()
    app.dependency_overrides[obtener_sesion] = lambda: sesion
    return TestClient(app, raise_server_exceptions=False)


def test_con_la_base_viva_dice_ok(cliente):
    r = cliente.get("/salud")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok"


def test_el_ts_viene_en_hora_argentina(cliente):
    """UTC-3 fijo: regla del ecosistema desde el 2026-08-12, no un gusto."""
    ts = datetime.fromisoformat(cliente.get("/salud").json()["ts"])
    assert ts.utcoffset() == timedelta(hours=-3)


def test_health_es_la_misma_sonda_que_salud(cliente):
    """La ruta de la familia. La sirve el mismo handler, no una copia.

    🔴 Lo que importa no es que `/health` conteste 200 —con la SPA horneada, el
    catch-all de `app/asgi.py` contesta 200 en cualquier ruta— sino que
    conteste **la sonda**: mismo cuerpo, con `estado` adentro. Es la diferencia
    entre un healthcheck que mide la base y uno que mide que haya estáticos.

    El alta de un cliente le estampa a su contenedor un chequeo contra
    `/health`, que es el default de `libracore.provisioning`. Que esa ruta sea
    una que este router sirve lo verifica `tests/test_provisioning.py` desde el
    otro lado.
    """
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok"
    assert set(r.json()) == set(cliente.get("/salud").json()), (
        "las dos rutas tienen que dar la misma forma: son el mismo handler")


def test_health_tambien_falla_cerrado():
    """El control de la de arriba, por la ruta nueva.

    Sin esto, `/health` podría estar servida por cualquier cosa que devuelva
    `{"estado": "ok"}` sin tocar la base — que es exactamente el falso verde que
    esta ruta viene a evitar.
    """

    class _BaseCaida:
        def execute(self, *_a, **_k):
            raise OperationalError("SELECT 1", {}, Exception("conexion rechazada"))

    app = _app()
    app.dependency_overrides[obtener_sesion] = lambda: _BaseCaida()
    r = TestClient(app, raise_server_exceptions=False).get("/health")

    assert r.status_code == 500
    assert "ok" not in r.text


def test_falla_cerrado_si_la_base_no_responde():
    """El control negativo del caso de arriba."""

    class _BaseCaida:
        def execute(self, *_a, **_k):
            raise OperationalError("SELECT 1", {}, Exception("conexion rechazada"))

    app = _app()
    app.dependency_overrides[obtener_sesion] = lambda: _BaseCaida()
    r = TestClient(app, raise_server_exceptions=False).get("/salud")

    assert r.status_code == 500
    assert "ok" not in r.text
