"""El login real contra `libraauth`, que es el criterio de F1.

🔴 `TestClient` va con `base_url="https://…"` a propósito. `SessionAuth` marca
la cookie como `Secure`, y sobre `http://testserver` httpx la acepta pero **no
la reenvía**: el login daría 200 y todo lo de después 401, con la sesión rota
por el esquema de la URL y no por las credenciales. Es el mismo síntoma que ya
se pagó sembrando datos por `curl` contra una instancia local.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.auth import COOKIE
from app.main import crear_app
from tests.conftest import config_de_prueba

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def entorno(engine, monkeypatch):
    """Tablas del motor de auth en limpio y las variables que espera el bootstrap.

    Se dropean y recrean por test: el `sesion` del conftest sólo trunca las
    tablas del dominio, así que sin esto el admin de un test sobrevive al
    siguiente y `ensure_default_admin` —que no hace nada si ya hay usuarios—
    dejaría de sembrar.
    """
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    yield
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def cliente(entorno):

    cfg = config_de_prueba()
    return TestClient(crear_app(cfg), base_url="https://testserver")


def test_se_entra_con_el_usuario_sembrado(cliente):
    r = cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    assert r.status_code == 200, r.text
    assert COOKIE in r.cookies or COOKIE in cliente.cookies


def test_la_clave_equivocada_no_entra(cliente):
    """El control negativo: sin esto, un login que aceptara cualquier cosa
    pasaría el test de arriba igual."""
    r = cliente.post("/auth/login", json={"username": USUARIO, "password": "otra"})
    assert r.status_code == 401
    assert COOKIE not in cliente.cookies


def test_me_sin_sesion_no_contesta_un_usuario(cliente):
    assert cliente.get("/auth/me").status_code == 401


def test_la_sesion_sobrevive_al_request_siguiente(cliente):
    """Lo que de verdad prueba que la cookie sirve: un GET posterior."""
    cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    r = cliente.get("/auth/me")
    assert r.status_code == 200, r.text
    assert r.json()["username"] == USUARIO


def test_el_logout_corta_la_sesion(cliente):
    cliente.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    assert cliente.get("/auth/me").status_code == 200
    cliente.post("/auth/logout")
    assert cliente.get("/auth/me").status_code == 401


def test_sin_clave_de_admin_la_app_no_levanta(engine, monkeypatch):
    """Fail-closed, la variante que usan los productos FastAPI de la familia.

    La otra (`ensure_admin_user`) inventa una contraseña y la imprime. No son
    intercambiables: si un día esto arranca igual sin la variable, alguien
    cambió de variante y la instancia queda con una clave que nadie eligió.
    """

    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("LIBRACARGO_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("SECRET_KEY", "un-secreto-cualquiera-para-el-test")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    try:
        cfg = config_de_prueba(entorno="production")
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            crear_app(cfg)
    finally:
        AuthBase.metadata.drop_all(engine)


def test_sin_secreto_de_sesion_la_app_no_levanta(engine, monkeypatch):
    """La otra mitad del fail-closed: sin `SECRET_KEY` no se firma nada.

    Si esto arrancara igual, las sesiones se firmarían con el secreto de
    desarrollo que está escrito en el código fuente: cualquiera que lea el repo
    —público— podría fabricar una cookie válida.
    """

    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba(entorno="production")
    try:
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            crear_app(cfg)
    finally:
        AuthBase.metadata.drop_all(engine)
