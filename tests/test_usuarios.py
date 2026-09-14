"""El ABM de usuarios, ahora sobre `libraauth.usuarios.build_users_router()`
(ADR-018, v0.43.0).

El ciclo completo (listar → alta → editar → releer → borrar) lo prueba
`verificar_contrato_de_usuarios`, compartido con el resto de la familia: si
alguien le cambia un campo a los modelos públicos de `libraauth`, ese test
cambia con él en el mismo commit, no acá dos semanas después.

Lo que sigue siendo propio de este archivo son **las dos puertas que no se
pueden cerrar desde adentro** (un admin no puede desactivarse ni borrarse a sí
mismo) y las protecciones de router (sólo admin, ni un staff ni un anónimo).
La protección del ÚLTIMO administrador activo -- nueva para este producto con
esta adopción -- se prueba con mutación de estado en el propio `libraauth`
(`tests/test_usuarios_router.py`), no acá: ver el docstring de
`verificar_contrato_de_usuarios`.

🔴 **La contraseña mínima subió de "no vacía" a 6 caracteres**, también en el
alta (antes sólo Contalibra/Restolibra lo exigían ahí). Las contraseñas de
prueba de este archivo tienen 6 caracteres o más a propósito.
"""


import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libraauth.testing import verificar_contrato_de_usuarios

from app.main import crear_app
from tests.conftest import config_de_prueba

ADMIN, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", ADMIN)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


def id_de(cliente, username):
    return next(u["id"] for u in cliente.get("/api/usuarios").json()
                if u["username"] == username)


def test_contrato_de_usuarios(cliente):
    """El ciclo que ejerce el backoffice de la suite, con la sesión de admin."""
    verificar_contrato_de_usuarios(cliente, "/api/usuarios", role="staff")


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
    cuerpo = {"username": "marta", "name": "Marta", "password": "clave1", "role": "staff"}
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
        "username": "pedro", "name": "Pedro", "password": "clave1", "role": "admin"}).json()
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


def test_la_clave_corta_no_se_acepta_ni_en_el_alta_ni_en_el_reset(cliente):
    """🔑 Nuevo con esta adopción: antes el alta de este producto no exigía
    largo mínimo (sólo Contalibra/Restolibra lo hacían). Ahora sí, en los ocho."""
    corta = cliente.post("/api/usuarios", json={
        "username": "cortita", "name": "Cortita", "password": "abc12", "role": "staff"})
    assert corta.status_code == 422, corta.text

    creado = cliente.post("/api/usuarios", json={
        "username": "normal", "name": "Normal", "password": "una-clave", "role": "staff"}).json()
    reset_corto = cliente.put(f"/api/usuarios/{creado['id']}/password",
                              json={"password": "abc12"})
    assert reset_corto.status_code == 422, reset_corto.text


def test_un_usuario_staff_no_administra_usuarios(cliente):
    """El router entero exige admin: un operador no ve ni toca esta pantalla."""
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    assert staff.post("/auth/login",
                      json={"username": "marta", "password": "una-clave"}).status_code == 200
    assert staff.get("/api/usuarios").status_code == 403
    assert staff.post("/api/usuarios", json={
        "username": "otro", "name": "Otro", "password": "clave1", "role": "admin"}).status_code == 403
    # Control: el mismo pedido con la sesión de admin pasa.
    assert cliente.get("/api/usuarios").status_code == 200


def test_sin_sesion_no_se_ven_los_usuarios(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/usuarios").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
