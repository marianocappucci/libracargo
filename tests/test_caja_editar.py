"""Editar y anular movimientos de caja.

Es lo último que faltaba del bloque NOVEDAD del sistema viejo, y las dos cosas
tocan **dos registros**: el movimiento y su contrapartida en la cuenta corriente.
"""

from decimal import Decimal

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


@pytest.fixture
def tercero(cliente):
    r = cliente.post("/api/terceros", json={
        "razon_social": "Agro Norte", "es_cliente": True, "es_fletero": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def cobro(tercero_id, **extra):
    base = {
        "fecha": "2026-08-21", "tipo": "ingreso", "concepto": "Cobro",
        "importe": "100000.00", "tercero_id": tercero_id, "rol": "cliente",
    }
    base.update(extra)
    return base


def cuenta(cliente, rol, tercero_id):
    r = cliente.get(f"/api/cuentas/{rol}/{tercero_id}")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["coinciden"] is True
    return Decimal(c["saldo"]), [f["movimiento"] for f in c["movimientos"]]


def test_editar_corrige_el_movimiento_y_su_contrapartida(cliente, tercero):
    """Una línea en la cuenta, no dos: es lo que hace el `UPDATE` del legado."""
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    r = cliente.put(f"/api/caja/{id_}", json=cobro(tercero, importe="120000.00"))
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["importe"]) == Decimal("120000.00")

    saldo, movs = cuenta(cliente, "cliente", tercero)
    assert saldo == Decimal("-120000.00")
    assert len(movs) == 1


def test_cambiar_el_rol_mueve_el_asiento_de_cuenta(cliente, tercero):
    """El mismo tercero puede ser cliente y fletero: son dos cuentas."""
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    r = cliente.put(f"/api/caja/{id_}", json=cobro(tercero, tipo="egreso", rol="fletero"))
    assert r.status_code == 200, r.text

    assert cuenta(cliente, "cliente", tercero) == (Decimal("0.00"), [])
    saldo_flet, movs = cuenta(cliente, "fletero", tercero)
    # Un egreso a un fletero va al HABER: pagarle baja lo que se le debe.
    assert saldo_flet == Decimal("-100000.00")
    assert len(movs) == 1


def test_sacarle_el_tercero_borra_la_contrapartida(cliente, tercero):
    """Un gasto general de la agencia no mueve la cuenta de nadie."""
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    r = cliente.put(f"/api/caja/{id_}", json={
        "fecha": "2026-08-21", "tipo": "egreso", "concepto": "Nafta",
        "importe": "5000.00"})
    assert r.status_code == 200, r.text
    assert cuenta(cliente, "cliente", tercero) == (Decimal("0.00"), [])


def test_agregarle_un_tercero_crea_la_contrapartida(cliente, tercero):
    """El camino inverso del de arriba, que es donde un `update` a secas falla:
    no hay asiento que corregir, hay que crearlo."""
    id_ = cliente.post("/api/caja", json={
        "fecha": "2026-08-21", "tipo": "ingreso", "concepto": "Suelto",
        "importe": "7000.00"}).json()["id"]
    assert cuenta(cliente, "cliente", tercero) == (Decimal("0.00"), [])

    r = cliente.put(f"/api/caja/{id_}", json=cobro(tercero, importe="7000.00"))
    assert r.status_code == 200, r.text
    saldo, movs = cuenta(cliente, "cliente", tercero)
    assert saldo == Decimal("-7000.00")
    assert len(movs) == 1


def test_anular_no_borra_y_deja_el_saldo_en_cero(cliente, tercero):
    """🔴 `elimina_novedad.php` borraba el movimiento y sus asientos: el cobro
    desaparecía y el número de recibo quedaba con un hueco sin explicación."""
    id_ = cliente.post("/api/caja", json=cobro(tercero, recibo="0001-555")).json()["id"]
    r = cliente.delete(f"/api/caja/{id_}")
    assert r.status_code == 200, r.text
    assert r.json()["anulado"] is True

    saldo, movs = cuenta(cliente, "cliente", tercero)
    assert saldo == Decimal("0.00")
    assert len(movs) == 2, "la anulación agrega el contraasiento, no borra el original"
    assert movs[1]["fecha"] == "2026-08-21", "la reversión lleva la fecha del movimiento"

    # Y el movimiento sigue en el listado, con su recibo: es lo que explica el
    # hueco en la numeración.
    filas = cliente.get("/api/caja").json()
    assert len(filas) == 1
    assert filas[0]["recibo"] == "0001-555"
    assert filas[0]["anulado"] is True


def test_un_anulado_no_se_edita_ni_se_vuelve_a_anular(cliente, tercero):
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    cliente.delete(f"/api/caja/{id_}")
    assert cliente.put(f"/api/caja/{id_}", json=cobro(tercero)).status_code == 409
    assert cliente.delete(f"/api/caja/{id_}").status_code == 409


def test_un_anulado_deja_de_contar_en_los_totales(cliente, tercero):
    """🔴 El modo de falla que este filtro cierra.

    El listado **sí** muestra los anulados —un recibo que falta necesita
    explicación— pero los TOTALES no pueden incluirlos. Sin el filtro, un cobro
    dado de baja sigue sumando en los ingresos del período y en el conteo, y el
    número se ve perfectamente plausible.
    """
    cliente.post("/api/caja", json=cobro(tercero, importe="10000.00"))
    a_anular = cliente.post("/api/caja", json=cobro(tercero, importe="90000.00")).json()["id"]

    antes = cliente.get("/api/reportes/resumen").json()
    assert Decimal(antes["cobrado"]) == Decimal("100000.00")
    assert antes["movimientos_caja"] == 2

    cliente.delete(f"/api/caja/{a_anular}")

    despues = cliente.get("/api/reportes/resumen").json()
    assert Decimal(despues["cobrado"]) == Decimal("10000.00")
    assert despues["movimientos_caja"] == 1

    # El otro agregado, el de caja por medio de pago.
    filas = cliente.get("/api/reportes/caja").json()
    total = sum(Decimal(f["importe"]) for f in filas)
    assert total == Decimal("10000.00")

    # Y el listado los sigue mostrando, que es el control de que el filtro es
    # de los totales y no un "esconder".
    assert len(cliente.get("/api/caja").json()) == 2


def test_el_par_tercero_rol_sigue_validandose_al_editar(cliente, tercero):
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    cuerpo = cobro(tercero)
    del cuerpo["rol"]
    assert cliente.put(f"/api/caja/{id_}", json=cuerpo).status_code == 422


def test_editar_un_movimiento_que_no_existe_da_404(cliente):
    assert cliente.put("/api/caja/9999", json={
        "fecha": "2026-08-21", "tipo": "ingreso", "concepto": "x",
        "importe": "1.00"}).status_code == 404
    assert cliente.delete("/api/caja/9999").status_code == 404


def test_sin_sesion_no_se_edita_ni_se_anula(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.put("/api/caja/1", json={}).status_code == 401
        assert anonimo.delete("/api/caja/1").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
