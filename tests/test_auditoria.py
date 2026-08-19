"""El log: quién hizo qué, y **qué cambió**.

La tabla `sucesos` del legado guardaba que algo había pasado y nada más. Lo que
se prueba acá es lo que la hace útil: que el asiento quede en la **misma
transacción** que el cambio, que guarde el diff y no la fila entera, y que un
`PUT` que no cambió nada no ensucie el log.
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


def log(cliente, **filtros):
    consulta = "&".join(f"{k}={v}" for k, v in filtros.items())
    r = cliente.get(f"/api/auditoria?{consulta}")
    assert r.status_code == 200, r.text
    return r.json()


def test_el_alta_de_un_maestro_queda_registrada_con_quien_la_hizo(cliente):
    creado = cliente.post("/api/terceros", json={
        "razon_social": "Agro Norte", "es_cliente": True}).json()

    pagina = log(cliente, entidad="terceros")
    assert pagina["total"] == 1
    asiento = pagina["registros"][0]
    assert asiento["accion"] == "alta"
    assert asiento["entidad_id"] == creado["id"]
    assert asiento["usuario_nombre"] == ADMIN
    assert asiento["datos_despues"]["razon_social"] == "Agro Norte"
    assert asiento["datos_antes"] is None


def test_la_modificacion_guarda_el_antes_y_el_despues_de_lo_que_cambio(cliente):
    """🔑 Lo que `sucesos` nunca guardó: **qué** cambió.

    Y sólo lo que cambió: guardar las 23 columnas de una orden por cada
    corrección de un remito convierte leer el log en buscar una aguja.
    """
    creado = cliente.post("/api/terceros", json={
        "razon_social": "Agro Norte", "es_cliente": True, "telefono": "2324-1"}).json()
    cliente.put(f"/api/terceros/{creado['id']}", json={
        "razon_social": "Agro Norte SA", "es_cliente": True, "telefono": "2324-1"})

    asiento = log(cliente, entidad="terceros", accion="modificacion")["registros"][0]
    assert asiento["datos_antes"] == {"razon_social": "Agro Norte"}
    assert asiento["datos_despues"] == {"razon_social": "Agro Norte SA"}
    # El teléfono no cambió: no está en el diff.
    assert "telefono" not in asiento["datos_despues"]


def test_un_put_que_no_cambia_nada_no_deja_asiento(cliente):
    """El control del test de arriba: si el diff no se calculara, esto sumaría uno."""
    creado = cliente.post("/api/terceros", json={
        "razon_social": "Agro Norte", "es_cliente": True}).json()
    cuerpo = {"razon_social": "Agro Norte", "es_cliente": True}
    assert cliente.put(f"/api/terceros/{creado['id']}", json=cuerpo).status_code == 200

    assert log(cliente, entidad="terceros", accion="modificacion")["total"] == 0
    # Y el alta sigue estando: no se borró nada, simplemente no se agregó ruido.
    assert log(cliente, entidad="terceros")["total"] == 1


def test_el_importe_se_guarda_como_texto_y_no_como_float(cliente):
    """Un log de auditoría donde el importe pasó por `float` no sirve de prueba."""
    maestros = {
        "cliente": cliente.post("/api/terceros",
                                json={"razon_social": "Agro", "es_cliente": True}).json()["id"],
        "origen": cliente.post("/api/localidades", json={"nombre": "Suipacha"}).json()["id"],
        "destino": cliente.post("/api/localidades", json={"nombre": "Rosario"}).json()["id"],
    }
    orden = cliente.post("/api/ordenes", json={
        "fecha": "2026-08-10", "cliente_id": maestros["cliente"],
        "origen_id": maestros["origen"], "destino_id": maestros["destino"],
        "tarifa": "1234567.89"}).json()

    asiento = log(cliente, entidad="orden_carga")["registros"][0]
    assert asiento["entidad_id"] == orden["id"]
    assert asiento["datos_despues"]["tarifa"] == "1234567.89"
    assert isinstance(asiento["datos_despues"]["tarifa"], str)


def test_la_anulacion_de_una_orden_queda_como_baja(cliente):
    maestros = {
        "cliente": cliente.post("/api/terceros",
                                json={"razon_social": "Agro", "es_cliente": True}).json()["id"],
        "origen": cliente.post("/api/localidades", json={"nombre": "Suipacha"}).json()["id"],
        "destino": cliente.post("/api/localidades", json={"nombre": "Rosario"}).json()["id"],
    }
    orden = cliente.post("/api/ordenes", json={
        "fecha": "2026-08-10", "cliente_id": maestros["cliente"],
        "origen_id": maestros["origen"], "destino_id": maestros["destino"],
        "tarifa": "100.00"}).json()
    cliente.delete(f"/api/ordenes/{orden['id']}")

    asiento = log(cliente, entidad="orden_carga", accion="baja")["registros"][0]
    assert asiento["datos_antes"]["estado"] == "pendiente"
    assert asiento["datos_despues"]["estado"] == "anulada"


def test_si_la_operacion_falla_no_queda_asiento(cliente):
    """🔴 Misma transacción. Un log que registra lo que no pasó miente igual.

    El alta repetida choca contra la unicidad y termina en 409; el asiento de
    esa alta tiene que irse con el `rollback`.
    """
    cliente.post("/api/localidades", json={"nombre": "Suipacha"})
    antes = log(cliente, entidad="localidades")["total"]
    assert cliente.post("/api/localidades", json={"nombre": "Suipacha"}).status_code == 409
    assert log(cliente, entidad="localidades")["total"] == antes


def test_el_movimiento_de_caja_y_el_comprobante_tambien_se_registran(cliente):
    tercero = cliente.post("/api/terceros", json={
        "razon_social": "Agro", "es_cliente": True}).json()["id"]
    cliente.post("/api/caja", json={
        "fecha": "2026-08-10", "tipo": "ingreso", "concepto": "Cobro",
        "importe": "500.00", "tercero_id": tercero, "rol": "cliente"})
    assert log(cliente, entidad="movimiento_caja")["total"] == 1

    entidades = cliente.get("/api/auditoria/entidades").json()
    assert "movimiento_caja" in entidades and "terceros" in entidades
    assert cliente.get("/api/auditoria/usuarios").json() == [ADMIN]


def test_el_listado_pagina_y_dice_cuantos_hay(cliente):
    for i in range(7):
        cliente.post("/api/localidades", json={"nombre": f"Pueblo {i}"})
    pagina = log(cliente, limite=3)
    assert pagina["total"] == 7
    assert len(pagina["registros"]) == 3
    # Más nuevo primero.
    assert pagina["registros"][0]["datos_despues"]["nombre"] == "Pueblo 6"
    segunda = log(cliente, limite=3, desplazamiento=3)
    assert segunda["total"] == 7
    assert segunda["registros"][0]["datos_despues"]["nombre"] == "Pueblo 3"


def test_un_operador_no_ve_el_log(cliente):
    """El log es de administración: dice quién hizo qué, incluido el que mira."""
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    assert staff.post("/auth/login",
                      json={"username": "marta", "password": "una-clave"}).status_code == 200
    assert staff.get("/api/auditoria").status_code == 403
    # Control: el admin sí.
    assert cliente.get("/api/auditoria").status_code == 200


def test_sin_sesion_no_se_ve_el_log(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/auditoria").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
