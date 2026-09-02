"""*Probar conexión* del correo, montado en este producto.

El router es del motor y ahí está probado a fondo. Lo que se prueba acá es lo
único que el motor no puede: que **este producto lo monte**, detrás de su gate
de admin, y con **su** resolver de SMTP.

🔴 Sin la línea de montaje el botón de la pantalla compartida da 404, y la
instancia no falla por eso: arranca perfecto y el cliente descubre que no puede
probar su correo. Es la misma clase de defecto silencioso que el gate de
términos, que también tiene su test en cada producto.
"""


import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.main import crear_app
from tests.conftest import config_de_prueba

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


def test_el_endpoint_de_probar_esta_montado(cliente):
    """Sin SMTP cargado contesta 400 y dice qué falta — pero contesta.

    🔑 El 400 es la prueba de que la ruta existe: si no estuviera montada, el
    catch-all del SPA la atendería y esto sería 404 o 405.
    """
    r = cliente.post("/admin/smtp/probar")

    assert r.status_code == 400, r.text
    assert "Completá" in r.json()["detail"]


def test_una_ruta_inventada_al_lado_NO_contesta(cliente):
    """El control del test de arriba: distingue "está montado" de "el catch-all
    contesta cualquier cosa colgada de /admin/smtp"."""
    r = cliente.post("/admin/smtp/inventado")

    assert r.status_code in (404, 405), r.text


def test_probar_es_de_administrador(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        # Abrir una sesión SMTP con las credenciales del cliente no es algo que
        # pueda hacer cualquiera que esté logueado.
        assert anonimo.post("/admin/smtp/probar").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
