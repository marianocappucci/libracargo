"""La marca blanca esta cableada: la instancia puede tener nombre, color y logo del revendedor (libracore ADR-092).

Lo que se mide aca es el **cableado** del producto, no el motor: que las rutas esten montadas, que escribir las gatee el
rol del producto y que el mail de recuperacion salga con el nombre de la marca. El comportamiento lo prueba `libracore`.
"""
import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient
from libraauth.testing import crear_schema_de_auth
from libracore import config_manager

MARCA = {"nombre": "Transportes Modelo", "nombre_corto": "Modelo", "color": "#c0392b"}


@pytest.fixture(autouse=True)
def _marca_propia_del_test(tmp_path, monkeypatch):
    """La marca vive en el `config.json` y el volumen de la instancia: cada test usa los suyos (la suite no aisla ese
    archivo)."""
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "MARCA_DIR", str(tmp_path / "marca"))


@pytest.fixture
def anonimo(cliente):
    """Un cliente SIN sesion sobre la misma app que `cliente` (que ya viene logueado como admin)."""
    return TestClient(cliente.app, base_url="https://testserver")


@pytest.fixture
def staff(cliente):
    r = cliente.post(
        "/api/usuarios", json={"username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"}
    )
    assert r.status_code == 201, r.text
    otro = TestClient(cliente.app, base_url="https://testserver")
    assert otro.post("/auth/login", json={"username": "marta", "password": "una-clave"}).status_code == 200
    return otro


def test_sin_marca_la_instancia_es_la_del_producto(anonimo):
    r = anonimo.get("/api/marca")
    assert r.status_code == 200
    assert r.json()["propia"] is False
    assert r.json()["terminos_propios"] is False


def test_el_admin_carga_la_marca_y_cualquiera_la_lee(cliente, anonimo):
    assert cliente.put("/api/marca", json=MARCA).status_code == 200
    leida = anonimo.get("/api/marca").json()  # sin sesion: el login tambien lleva la marca
    assert leida["propia"] is True
    assert leida["nombre"] == "Transportes Modelo"
    assert leida["color"] == "#c0392b"


@pytest.mark.parametrize("metodo", ["put", "delete"])
def test_sin_sesion_no_se_escribe_la_marca(anonimo, metodo):
    r = anonimo.request(metodo, "/api/marca", json=MARCA if metodo == "put" else None)
    assert r.status_code in (401, 403)


def test_el_staff_no_escribe_la_marca(staff):
    assert staff.put("/api/marca", json=MARCA).status_code == 403


def test_sin_sesion_no_se_escriben_los_terminos_propios(anonimo):
    r = anonimo.put("/api/marca/terminos", json={"version": "r-1.0", "vigente_desde": "01-01-2026", "texto": "x"})
    assert r.status_code in (401, 403)


def test_el_manifest_es_el_de_la_marca_y_no_el_index_de_la_spa(cliente, anonimo, monkeypatch, tmp_path):
    cliente.put("/api/marca", json=MARCA)
    r = anonimo.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert r.json()["name"] == "Transportes Modelo"


def test_el_mail_de_recuperacion_sale_con_el_nombre_de_la_marca(cliente):
    reset = cliente.app.state.password_reset
    assert reset.product_name == "LibraCargo"
    cliente.put("/api/marca", json=MARCA)
    assert reset.product_name == "Transportes Modelo"
    cliente.delete("/api/marca")
    assert reset.product_name == "LibraCargo"


def test_el_manifest_le_gana_al_catch_all_de_la_spa(engine, monkeypatch, tmp_path):
    """🔴 Con un build, `app/asgi.py` contesta `index.html` a cualquier ruta que no conozca. Si la marca se montara
    despues, el navegador leeria HTML como manifest. Corre el entrypoint real con un build de juguete (`frontend_dist()`
    apuntado a el)."""
    from app import frontend_dist as fd

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-de-prueba</html>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name": "LibraCargo", "icons": []}', encoding="utf-8")
    monkeypatch.setattr(fd, "_DIST_DOCKER", tmp_path / "no-existe")
    monkeypatch.setattr(fd, "_DIST_LOCAL", dist)
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", "clave-de-prueba")
    monkeypatch.setenv("SECRET_KEY", "libracargo-suite-no-es-un-secreto-real")
    crear_schema_de_auth(os.environ["DATABASE_URL"])
    previo = sys.modules.pop("app.asgi", None)
    try:
        asgi = importlib.import_module("app.asgi")
        c = TestClient(asgi.app, base_url="https://testserver")
        r = c.get("/manifest.webmanifest")
        assert r.status_code == 200 and r.json()["name"] == "LibraCargo", r.text
        assert "manifest" in r.headers["content-type"], r.headers
        assert c.get("/api/marca").json()["propia"] is False
    finally:
        sys.modules.pop("app.asgi", None)
        if previo is not None:
            sys.modules["app.asgi"] = previo
