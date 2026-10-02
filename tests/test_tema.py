"""El tema de la suite en esta instancia (libracore ADR-012, libra-ui ADR-007/008): `GET /api/tema`
público y `PUT /api/tema` del admin o del token de servicio del backoffice.

🔴 El caso que importa para el backoffice es el del token: `require_admin` a secas NO lo acepta (sólo
`require_admin_o_servicio`), y sin esto la pantalla «Apariencia» no podría empujar nada.
"""
import pytest
from fastapi.testclient import TestClient
from libraauth.session_auth import SERVICE_TOKEN_ENV, SERVICE_TOKEN_HEADER
from libracore import config_manager

TEMA = {"menuActivoFondo": "#FDF2F8", "menuActivoBorde": "#F9A8D4"}
NORMALIZADO = {"menuActivoFondo": "#fdf2f8", "menuActivoBorde": "#f9a8d4"}
TOKEN = "un-token-de-servicio-de-prueba"


@pytest.fixture(autouse=True)
def _config_propia(tmp_path, monkeypatch):
    """El tema vive en el `config.json` de la instancia: cada test usa el suyo. Sin esto, el tema que
    guarda un test lo ve el siguiente (la suite de este producto no aísla ese archivo)."""
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))


@pytest.fixture
def anonimo(cliente):
    """Un cliente SIN sesión sobre la misma app que `cliente` (que ya viene logueado como admin)."""
    return TestClient(cliente.app, base_url="https://testserver")


def test_la_lectura_es_publica_y_arranca_vacia(anonimo):
    r = anonimo.get("/api/tema")
    assert r.status_code == 200
    assert r.json() == {"tema": {}}
    assert r.headers["cache-control"] == "no-cache"


def test_el_admin_guarda_y_cualquiera_lo_lee_sin_sesion(cliente, anonimo):
    r = cliente.put("/api/tema", json={"tema": TEMA})
    assert r.status_code == 200, r.text
    assert r.json() == {"tema": NORMALIZADO}
    assert anonimo.get("/api/tema").json() == {"tema": NORMALIZADO}


def test_un_tema_vacio_restaura_los_valores_por_defecto(cliente):
    cliente.put("/api/tema", json={"tema": TEMA})
    assert cliente.put("/api/tema", json={"tema": {}}).status_code == 200
    assert cliente.get("/api/tema").json() == {"tema": {}}


def test_sin_sesion_ni_token_no_escribe(anonimo):
    assert anonimo.put("/api/tema", json={"tema": TEMA}).status_code == 401


def test_el_token_de_servicio_del_backoffice_escribe_el_tema(anonimo, monkeypatch):
    monkeypatch.setenv(SERVICE_TOKEN_ENV, TOKEN)
    r = anonimo.put("/api/tema", json={"tema": TEMA}, headers={SERVICE_TOKEN_HEADER: TOKEN})
    assert r.status_code == 200, r.text
    assert anonimo.get("/api/tema").json() == {"tema": NORMALIZADO}


def test_un_token_equivocado_o_sin_la_variable_no_escribe(anonimo, monkeypatch):
    monkeypatch.setenv(SERVICE_TOKEN_ENV, TOKEN)
    r = anonimo.put("/api/tema", json={"tema": TEMA}, headers={SERVICE_TOKEN_HEADER: "otro"})
    assert r.status_code == 401
    monkeypatch.delenv(SERVICE_TOKEN_ENV, raising=False)
    r = anonimo.put("/api/tema", json={"tema": TEMA}, headers={SERVICE_TOKEN_HEADER: TOKEN})
    assert r.status_code == 401


def test_lo_que_no_tiene_la_forma_de_un_color_es_422(cliente):
    assert cliente.put("/api/tema", json={"tema": {"menuActivoFondo": "verde"}}).status_code == 422
    assert cliente.get("/api/tema").json() == {"tema": {}}
