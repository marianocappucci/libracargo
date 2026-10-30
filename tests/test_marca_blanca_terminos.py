"""Con marca propia la instancia exige los Terminos del revendedor y nunca cae a los de la familia (libraauth ADR-030).

🔴 Se marca `sin_aceptar_terminos` para que el gate corte de verdad. Es lo que se pondria rojo si alguien sacara
`contrato_propio` o `exigir_propio` de `TerminosRepository(...)` en `app/main.py`: el producto seguiria andando y una
instancia de revendedor aceptaria los terminos de Libra en silencio.
"""
import os

import pytest
from fastapi.testclient import TestClient
from libraauth.testing import crear_schema_de_auth
from libracore import config_manager

from app.main import crear_app
from tests.conftest import config_de_prueba, vaciar_auth

pytestmark = pytest.mark.sin_aceptar_terminos

USUARIO, CLAVE = "admin", "clave-de-prueba"
TEXTO = "Terminos del revendedor, version de prueba.\n"


@pytest.fixture(autouse=True)
def _marca_propia_del_test(tmp_path, monkeypatch):
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "MARCA_DIR", str(tmp_path / "marca"))


@pytest.fixture
def logueado(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    c = TestClient(crear_app(config_de_prueba()), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    vaciar_auth(engine)


def _marca_propia() -> None:
    cfg = config_manager.load()
    cfg["marca"] = {"nombre": "Transportes Modelo"}
    config_manager.save(cfg)


def _terminos_propios() -> None:
    cfg = config_manager.load()
    cfg["terminos_propios"] = {"version": "rev-1.0", "vigente_desde": "01-01-2026"}
    config_manager.save(cfg)
    os.makedirs(config_manager.MARCA_DIR, exist_ok=True)
    with open(os.path.join(config_manager.MARCA_DIR, "terminos.md"), "w", encoding="utf-8", newline="") as f:
        f.write(TEXTO)


def test_sin_marca_propia_rigen_los_terminos_de_la_familia(logueado):
    estado = logueado.get("/terminos").json()
    assert estado["pendiente"] is True
    assert estado["version"] != "rev-1.0"


def test_con_marca_propia_y_sin_terminos_propios_la_instancia_queda_frenada(logueado):
    _marca_propia()
    r = logueado.get("/api/ordenes")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "terminos_pendientes"
    # Nadie puede aceptar nada: no hay contrato, ni siquiera el de la familia.
    estado = logueado.get("/terminos").json()
    assert estado["sin_contrato"] is True
    aceptar = logueado.post("/terminos/aceptar", json={"version": "1.0", "hash_texto": "0" * 64})
    assert aceptar.status_code >= 400
    assert logueado.get("/api/ordenes").status_code == 403


def test_con_terminos_propios_se_acepta_el_contrato_del_revendedor(logueado):
    _marca_propia()
    _terminos_propios()
    estado = logueado.get("/terminos").json()
    assert estado["version"] == "rev-1.0"
    assert estado["pendiente"] is True
    r = logueado.post("/terminos/aceptar", json={"version": estado["version"], "hash_texto": estado["hash_texto"]})
    assert r.status_code == 200, r.text
    assert logueado.get("/api/ordenes").status_code == 200
