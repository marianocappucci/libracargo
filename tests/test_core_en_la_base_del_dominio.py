"""La app arranca y factura con cualquiera de las formas de entorno que hay en la flota (ADR-054).

> 🔑 **Los datos son ficticios**: «Agro Norte», el CUIT 30-12345678-1 y el emisor de `conftest`.

`LIBRACARGO_LIBRACORE_DATABASE_URL` ya no hace falta: el schema de LibraCore vive en la base del dominio desde la
`0015` (ADR-029). Pero **no se puede sacar de golpe de todos lados**: el compose de Suitrans (cliente real) y los
que genera `libracore.provisioning` todavía la llevan, apuntando a la misma base que `DATABASE_URL`. El código nuevo
tiene que andar igual con ella puesta, y éste es el test que lo ata: arma la `Config` **desde el entorno**, como el
arranque real (el resto de la suite la arma con `config_de_prueba`), arranca la app y **emite una factura por ARCA**
—el camino que escribe en las dos mitades del schema en una sola transacción—.

Tres formas, una por cada entorno que existe o va a existir:

- `sin_la_variable`: el compose de dev y una instancia nueva.
- `igual_a_database_url`: **Suitrans**, hoy. La variable puesta, con la misma URL.
- `igual_escrita_distinto`: la misma base con otro driver y parámetros, por si un compose no la copia al carácter.

La forma con la variable apuntando a OTRA base no arranca (fail-closed): la cubre `tests/test_config.py`.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import database
from app.config import Config
from app.main import crear_app
from tests.conftest import CLAVE, URL, USUARIO, crear_schema_de_auth, vaciar_auth
from tests.test_comprobantes import facturar, orden

pytestmark = pytest.mark.con_emisor

VARIABLE_DEL_CORE = "LIBRACARGO_LIBRACORE_DATABASE_URL"


def _formas() -> dict[str, str | None]:
    base = os.environ["DATABASE_URL"]
    return {
        "sin_la_variable": None,
        "igual_a_database_url": base,
        # `postgresql://` en vez de `postgresql+psycopg://`, y un parámetro de conexión.
        "igual_escrita_distinto": base.replace("postgresql+psycopg://", "postgresql://", 1) + "?connect_timeout=10",
    }


@pytest.fixture(params=list(_formas()))
def forma(request, monkeypatch):
    """Deja el entorno como lo tiene esa forma: `DATABASE_URL` siempre, la del core según el caso."""
    monkeypatch.delenv("LIBRACARGO_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", URL)
    valor = _formas()[request.param]
    if valor is None:
        monkeypatch.delenv(VARIABLE_DEL_CORE, raising=False)
    else:
        monkeypatch.setenv(VARIABLE_DEL_CORE, valor)
    return request.param


@pytest.fixture
def cliente(engine, sesion, monkeypatch, _arca_de_cero, forma):
    """Igual que el `cliente` de `conftest`, pero con la `Config` leída del entorno, que es como arranca de verdad."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    cfg = Config.desde_entorno()
    assert cfg.database_url == URL, "el core es la base del dominio, con la variable o sin ella"
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c


def test_arranca_y_factura_por_arca_en_la_misma_transaccion(cliente, datos, emisor, forma):
    o = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [o])

    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["cae"] == "75123456789012"
    # El comprobante (schema del motor), la orden y la cuenta corriente quedaron juntos: es lo que una segunda
    # base —o una URL del core mal resuelta— rompería.
    assert cliente.get(f"/api/ordenes/{o['id']}").json()["estado"] == "facturada"
    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    assert len(cuenta["movimientos"]) == 1
    assert Decimal(cuenta["movimientos"][0]["movimiento"]["debe"]) == Decimal(comp["total"])


def test_el_motor_lee_su_schema_de_la_base_del_dominio(cliente, forma):
    """`libracore.db.core` quedó apuntando a la base del dominio: el add-on se escribe y se lee por ahí."""
    database.set_addon("resguardo_externo", True)
    try:
        assert database.get_modulos()["resguardo_externo"] is True
    finally:
        database.set_addon("resguardo_externo", False)
