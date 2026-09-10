"""El add-on `resguardo_externo`: apagado hasta que el backoffice lo prenda.

Lo que se mide es el camino entero y no una pieza suelta: el estado se escribe
con `app.database.set_addon` —la MISMA función que corre el backoffice por
`docker exec`— y se lee pegándole a la ruta real. Un test que parchara el gate
para devolver True o False mediría el parche.

🔴 **El caso que importa es el primero**: una instancia recién creada no tiene
fila en `modulos`, y así tiene que quedar cerrada. Es el que se pone rojo si el
gate deja pasar de más, y fue el que se usó para la falla forzada.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libracore.db import core as libracore_core

import plans
from app import database
from app.main import crear_app
from tests.conftest import URL_CORE, config_de_prueba

ADMIN, CLAVE = "admin", "clave-de-prueba"
ADDON = "resguardo_externo"
RUTA = "/api/config/resguardo-externo/enlace"


def _borrar_fila_del_addon() -> None:
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        conn.execute("DELETE FROM modulos WHERE modulo = ?", (ADDON,))


@pytest.fixture(autouse=True)
def _sin_fila_del_addon():
    """Cada test arranca como una instancia recién creada: sin fila.

    La tabla `modulos` vive en la base del core, que la suite crea una vez por
    corrida; sin esta limpieza, el test que lo prende dejaría prendido al
    siguiente y el caso "sin fila" pasaría a medir otra cosa.
    """
    _borrar_fila_del_addon()
    yield
    _borrar_fila_del_addon()


@pytest.fixture
def cliente(engine, sesion, tmp_path, monkeypatch):
    """La app logueada como admin, con los backups en un directorio temporal."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", ADMIN)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba(directorio_de_datos=str(tmp_path))
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


# ── El gate ──────────────────────────────────────────────────────────────────


def test_sin_fila_el_addon_esta_apagado(cliente):
    """Así viene cada instancia: sin fila en `modulos`, y entonces 403."""
    assert ADDON not in database.get_modulos(), "el control: arranca sin fila"
    assert cliente.get(RUTA).status_code == 403


def test_con_la_fila_en_false_sigue_apagado(cliente):
    database.set_addon(ADDON, False)
    assert database.get_modulos()[ADDON] is False, "el control: la fila existe"
    assert cliente.get(RUTA).status_code == 403


def test_prendido_desde_el_backoffice_deja_pasar(cliente):
    """Y el efecto es inmediato en las dos direcciones: no hay foto del arranque."""
    database.set_addon(ADDON, True)

    r = cliente.get(RUTA)
    assert r.status_code == 200, r.text
    assert {"proveedores", "enlace"} <= set(r.json()), r.json()

    database.set_addon(ADDON, False)
    assert cliente.get(RUTA).status_code == 403, "apagarlo no tuvo efecto hasta reiniciar"


def test_todas_las_rutas_del_enlace_pasan_por_el_gate(cliente):
    """El gate va en el `include_router`, así que alcanzaría con una ruta... hasta
    que alguien monte otra por su lado. Se prueban las cuatro, con el add-on
    apagado.
    """
    assert cliente.get(RUTA).status_code == 403
    assert cliente.post(f"{RUTA}/drive").status_code == 403
    assert cliente.get(f"{RUTA}/callback", params={"state": "x", "code": "y"}).status_code == 403
    assert cliente.delete(RUTA).status_code == 403


def test_un_usuario_que_no_es_admin_no_entra_aunque_este_prendido(cliente):
    """Con el add-on prendido, para que el 403 sea el del rol y no el del add-on."""
    database.set_addon(ADDON, True)
    assert cliente.get(RUTA).status_code == 200, "el control: el admin sí entra"

    assert cliente.post("/api/usuarios", json={
        "username": "operador", "name": "Operador", "role": "staff",
        "password": "otra-clave-de-prueba",
    }).status_code == 201
    otro = TestClient(cliente.app, base_url="https://testserver")
    assert otro.post("/auth/login", json={
        "username": "operador", "password": "otra-clave-de-prueba"}).status_code == 200
    assert otro.get(RUTA).status_code in (401, 403)

    anonimo = TestClient(cliente.app, base_url="https://testserver")
    assert anonimo.get(RUTA).status_code in (401, 403)


def test_si_no_se_puede_leer_el_estado_falla_cerrado(cliente):
    """🔑 403 y no 500 cuando la tabla no está.

    Se apunta el core a la base del DOMINIO, que no tiene `modulos`: es el caso
    real —el que se midió en `libracargo-demo`— y no una excepción inventada.
    Aunque la fila esté prendida en la base de verdad, el gate no la puede ver y
    tiene que cerrar.
    """
    database.set_addon(ADDON, True)
    assert cliente.get(RUTA).status_code == 200, "el control: prendido, entra"

    libracore_core.configure(os.environ["DATABASE_URL"])
    try:
        assert cliente.get(RUTA).status_code == 403
    finally:
        libracore_core.configure(URL_CORE)


# ── plans.py ─────────────────────────────────────────────────────────────────


def test_el_addon_esta_declarado_y_fuera_de_todo_plan():
    """Un add-on no se reparte por plan: si estuviera en uno, `apply_plan` lo
    prendería o apagaría solo al cambiar de plan."""
    assert ADDON in plans.ADDONS
    assert ADDON not in plans.MODULOS
    assert ADDON not in plans.MODULO_LABELS
    for plan, modulos in plans.PLAN_MODULOS.items():
        assert ADDON not in modulos, plan


# ── El contrato del backoffice ───────────────────────────────────────────────


def test_el_backoffice_lee_lo_que_escribe():
    """Lo que corre `libracore.admin.services` por `docker exec`, tal cual."""
    from app.database import get_modulos, set_addon

    set_addon(ADDON, True)
    assert get_modulos()[ADDON] is True
    set_addon(ADDON, False)
    assert get_modulos()[ADDON] is False


def test_bajo_docker_exec_el_core_se_configura_solo(monkeypatch):
    """Bajo `docker exec` no corrió `crear_app()`: el core arranca sin configurar.

    Se simula dejándolo sin configurar y con la variable que el contenedor sí
    define. Si `_asegurar_core_configurado` usara la URL del dominio —o no se
    configurara— este test muere con `RuntimeError` o con la tabla ausente.
    """
    monkeypatch.setattr(libracore_core, "_db_path", None)
    monkeypatch.setattr(libracore_core, "_database_url", None)
    monkeypatch.setenv("LIBRACARGO_LIBRACORE_DATABASE_URL", URL_CORE)
    assert not libracore_core.esta_configurado(), "el control: sin configurar"

    database.set_addon(ADDON, True)
    assert database.get_modulos()[ADDON] is True
    assert libracore_core.esta_configurado()
