"""El ABM de usuarios.

El módulo lo pone `libra-ui`; lo que se prueba acá es el backend que consume, y
sobre todo **las dos puertas que no se pueden cerrar desde adentro**: un admin no
puede desactivarse ni borrarse a sí mismo. Con un solo administrador —el caso de
una instancia recién entregada— eso dejaría el producto sin nadie que pueda
administrar usuarios, y la única salida sería entrar a la base.
"""

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

ADMIN, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", ADMIN)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


def id_de(cliente, username):
    return next(u["id"] for u in cliente.get("/api/usuarios").json()
                if u["username"] == username)


def test_el_admin_sembrado_aparece_en_la_lista(cliente):
    usuarios = cliente.get("/api/usuarios").json()
    assert [u["username"] for u in usuarios] == [ADMIN]
    assert usuarios[0]["role"] == "admin"
    assert usuarios[0]["active"] is True


def test_alta_edicion_y_baja_de_un_usuario(cliente):
    r = cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta Operadora", "password": "una-clave",
        "role": "staff", "email": "marta@example.com"})
    assert r.status_code == 201, r.text
    creado = r.json()
    assert creado["role"] == "staff"

    # El usuario nuevo entra de verdad: puede iniciar sesión.
    otro = TestClient(cliente.app, base_url="https://testserver")
    assert otro.post("/auth/login",
                     json={"username": "marta", "password": "una-clave"}).status_code == 200

    editado = cliente.put(f"/api/usuarios/{creado['id']}", json={
        "name": "Marta Encargada", "role": "admin", "active": True})
    assert editado.status_code == 200
    assert editado.json()["name"] == "Marta Encargada"
    # 🔴 El correo NO se borra al editar sin mandarlo: el botón de activar y
    # desactivar de la grilla manda este mismo cuerpo.
    assert editado.json()["email"] == "marta@example.com"

    assert cliente.delete(f"/api/usuarios/{creado['id']}").status_code == 204
    assert [u["username"] for u in cliente.get("/api/usuarios").json()] == [ADMIN]


def test_el_nombre_de_usuario_repetido_se_rechaza(cliente):
    cuerpo = {"username": "marta", "name": "Marta", "password": "x", "role": "staff"}
    assert cliente.post("/api/usuarios", json=cuerpo).status_code == 201
    repetido = cliente.post("/api/usuarios", json=cuerpo)
    assert repetido.status_code == 409
    assert "ya existe" in repetido.text


def test_un_admin_no_se_puede_desactivar_ni_degradar_a_si_mismo(cliente):
    """Las dos puertas, con su control: sobre OTRO usuario las dos operaciones valen."""
    mio = id_de(cliente, ADMIN)
    cuerpo = {"name": "Admin", "role": "admin", "active": False}
    assert cliente.put(f"/api/usuarios/{mio}", json=cuerpo).status_code == 409
    degradarme = {"name": "Admin", "role": "staff", "active": True}
    assert cliente.put(f"/api/usuarios/{mio}", json=degradarme).status_code == 409
    assert cliente.delete(f"/api/usuarios/{mio}").status_code == 409
    # Y sigo pudiendo entrar: la guarda no rompió nada.
    assert cliente.get("/api/usuarios").status_code == 200

    # Control: sobre otro usuario, las tres operaciones se permiten.
    otro = cliente.post("/api/usuarios", json={
        "username": "pedro", "name": "Pedro", "password": "x", "role": "admin"}).json()
    assert cliente.put(f"/api/usuarios/{otro['id']}",
                       json={"name": "Pedro", "role": "staff", "active": False}).status_code == 200
    assert cliente.delete(f"/api/usuarios/{otro['id']}").status_code == 204


def test_la_clave_vacia_no_se_acepta(cliente):
    creado = cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"}).json()
    assert cliente.put(f"/api/usuarios/{creado['id']}/password",
                       json={"password": "   "}).status_code == 422
    # Control: una clave de verdad sí entra, y la vieja deja de servir.
    assert cliente.put(f"/api/usuarios/{creado['id']}/password",
                       json={"password": "otra-clave"}).status_code == 204
    otro = TestClient(cliente.app, base_url="https://testserver")
    assert otro.post("/auth/login",
                     json={"username": "marta", "password": "una-clave"}).status_code == 401
    assert otro.post("/auth/login",
                     json={"username": "marta", "password": "otra-clave"}).status_code == 200


def test_un_usuario_staff_no_administra_usuarios(cliente):
    """El router entero exige admin: un operador no ve ni toca esta pantalla."""
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    assert staff.post("/auth/login",
                      json={"username": "marta", "password": "una-clave"}).status_code == 200
    assert staff.get("/api/usuarios").status_code == 403
    assert staff.post("/api/usuarios", json={
        "username": "otro", "name": "Otro", "password": "x", "role": "admin"}).status_code == 403
    # Control: el mismo pedido con la sesión de admin pasa.
    assert cliente.get("/api/usuarios").status_code == 200


def test_sin_sesion_no_se_ven_los_usuarios(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/usuarios").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
