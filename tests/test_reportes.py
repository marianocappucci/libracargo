"""Los reportes.

Se arma un escenario chico pero completo —dos clientes, un fletero, órdenes en
dos meses, una anulada, una factura y movimientos de caja— y **cada aserción es
un número calculado a mano**. Un reporte que devuelve algo no prueba nada: lo que
prueba es que devuelva **ese** número y no otro.
"""

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


def crear(c, ruta, datos):
    r = c.post(ruta, json=datos)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def escenario(cliente):
    """Dos clientes, dos fleteros, y órdenes repartidas en dos meses.

    Los importes están elegidos para que cada total del reporte sea distinguible:
    si dos filas sumaran lo mismo, una aserción no distinguiría un reporte que
    agrupa bien de uno que agrupa mal.
    """
    d = {
        "cliente_a": crear(cliente, "/api/terceros",
                           {"razon_social": "Agro Norte", "es_cliente": True})["id"],
        "cliente_b": crear(cliente, "/api/terceros",
                           {"razon_social": "Molino Sur", "es_cliente": True})["id"],
        "fletero": crear(cliente, "/api/terceros",
                         {"razon_social": "Transportes Uno", "es_fletero": True})["id"],
        "suipacha": crear(cliente, "/api/localidades", {"nombre": "Suipacha"})["id"],
        "rosario": crear(cliente, "/api/localidades", {"nombre": "Rosario"})["id"],
        "mercedes": crear(cliente, "/api/localidades", {"nombre": "Mercedes"})["id"],
        "razon": crear(cliente, "/api/razones-sociales", {"nombre": "Suitrans"})["id"],
    }

    def orden(fecha, cliente_id, tarifa, comision, origen, destino, fletero=True):
        return crear(cliente, "/api/ordenes", {
            "fecha": fecha, "cliente_id": cliente_id, "origen_id": d[origen],
            "destino_id": d[destino], "tarifa": tarifa, "comision": comision,
            "fletero_id": d["fletero"] if fletero else None, "cantidad": "10"})

    # Julio: dos órdenes del cliente A por la misma ruta, una del B.
    d["o1"] = orden("2026-07-05", d["cliente_a"], "1000.00", "100.00", "suipacha", "rosario")
    d["o2"] = orden("2026-07-20", d["cliente_a"], "2000.00", "200.00", "suipacha", "rosario")
    d["o3"] = orden("2026-07-25", d["cliente_b"], "4000.00", "400.00", "suipacha", "mercedes")
    # Agosto: una del A, y una anulada que no tiene que sumar en ningún importe.
    d["o4"] = orden("2026-08-10", d["cliente_a"], "8000.00", "800.00", "rosario", "suipacha")
    d["anulada"] = orden("2026-07-15", d["cliente_b"], "9999.00", "999.00", "suipacha", "rosario")
    assert cliente.delete(f"/api/ordenes/{d['anulada']['id']}").status_code == 200

    # Una factura de julio sobre las dos órdenes del cliente A.
    d["comprobante"] = cliente.post("/api/comprobantes", json={
        "fecha": "2026-07-31", "razon_social_id": d["razon"], "cliente_id": d["cliente_a"],
        "tipo": "factura_a", "punto_venta": 1, "numero": 1,
        "orden_ids": [d["o1"]["id"], d["o2"]["id"]]}).json()

    # Caja: un cobro del cliente A y un pago al fletero, los dos en julio.
    cliente.post("/api/caja", json={
        "fecha": "2026-07-31", "tipo": "ingreso", "concepto": "Cobro",
        "importe": "1500.00", "tercero_id": d["cliente_a"], "rol": "cliente",
        "medio_pago": "transferencia"})
    cliente.post("/api/caja", json={
        "fecha": "2026-07-31", "tipo": "egreso", "concepto": "Pago flete",
        "importe": "300.00", "tercero_id": d["fletero"], "rol": "fletero",
        "medio_pago": "efectivo"})
    return d


def test_el_resumen_del_periodo_cuenta_lo_que_paso_en_el_periodo(cliente, escenario):
    """Julio contra agosto: si el filtro de fechas no se aplicara, darían igual."""
    julio = cliente.get("/api/reportes/resumen?desde=2026-07-01&hasta=2026-07-31").json()
    assert julio["ordenes"] == 3
    assert julio["ordenes_anuladas"] == 1
    assert Decimal(julio["tarifa"]) == Decimal("7000.00")      # 1000 + 2000 + 4000
    assert Decimal(julio["comision"]) == Decimal("700.00")
    # La anulada NO suma en los importes, pero se cuenta aparte.
    assert Decimal(julio["tarifa"]) != Decimal("16999.00")
    assert julio["comprobantes"] == 1
    assert Decimal(julio["facturado"]) == Decimal("3630.00")   # (1000 + 2000) * 1.21
    assert Decimal(julio["cobrado"]) == Decimal("1500.00")
    assert Decimal(julio["pagado"]) == Decimal("300.00")

    agosto = cliente.get("/api/reportes/resumen?desde=2026-08-01&hasta=2026-08-31").json()
    assert agosto["ordenes"] == 1
    assert Decimal(agosto["tarifa"]) == Decimal("8000.00")
    assert Decimal(agosto["cobrado"]) == Decimal("0.00")
    assert agosto["desde"] == "2026-08-01" and agosto["hasta"] == "2026-08-31"

    # Sin rango, el universo es todo.
    todo = cliente.get("/api/reportes/resumen").json()
    assert todo["ordenes"] == 4
    assert Decimal(todo["tarifa"]) == Decimal("15000.00")


def test_el_ranking_de_clientes_ordena_por_facturado_y_trae_el_saldo(cliente, escenario):
    filas = cliente.get("/api/reportes/por-cliente?desde=2026-07-01&hasta=2026-07-31").json()
    # Ordena por facturado, no por cantidad de ordenes: Molino Sur hizo UNA orden
    # de 4.000 y Agro Norte dos que suman 3.000.
    assert [f["tercero"] for f in filas] == ["Molino Sur", "Agro Norte"]
    b, a = filas
    assert a["ordenes"] == 2
    assert b["ordenes"] == 1
    assert Decimal(a["facturado"]) == Decimal("3630.00")   # (1000 + 2000) * 1.21
    assert Decimal(b["facturado"]) == Decimal("4840.00")   # 4000 * 1.21
    # 🔑 El saldo NO se acota al rango: es lo que el tercero debe hoy.
    # Agro Norte: 3.630 de la factura menos 1.500 cobrados = 2.130.
    assert Decimal(a["saldo"]) == Decimal("2130.00")
    # Molino Sur no tiene factura ni cobros: su cuenta no se movió.
    assert Decimal(b["saldo"]) == Decimal("0.00")


def test_el_ranking_de_fleteros_usa_la_comision(cliente, escenario):
    filas = cliente.get("/api/reportes/por-fletero").json()
    assert len(filas) == 1
    assert filas[0]["tercero"] == "Transportes Uno"
    assert filas[0]["ordenes"] == 4               # la anulada no cuenta
    assert Decimal(filas[0]["comision"]) == Decimal("1500.00")   # 100+200+400+800
    # Se le pagaron 300, y en la convencion del modelo un EGRESO va al debe --
    # la misma para las tres cuentas: el signo lo da el movimiento, no el rol.
    assert Decimal(filas[0]["saldo"]) == Decimal("300.00")


def test_los_saldos_traen_todas_las_cuentas_y_esconden_las_saldadas(cliente, escenario):
    """El default deja afuera las cuentas en cero, y se pueden pedir."""
    filas = cliente.get("/api/reportes/saldos").json()
    cuentas = {(f["tercero"], f["rol"]): Decimal(f["saldo"]) for f in filas}
    assert cuentas[("Agro Norte", "cliente")] == Decimal("2130.00")
    assert cuentas[("Transportes Uno", "fletero")] == Decimal("300.00")
    assert all(Decimal(f["saldo"]) != 0 for f in filas)
    # Filtrado por rol.
    solo_clientes = cliente.get("/api/reportes/saldos?rol=cliente").json()
    assert {f["rol"] for f in solo_clientes} == {"cliente"}
    # Y el último movimiento de la cuenta viene con la fila: sin eso no se sabe
    # si un saldo es de ayer o de hace tres años.
    assert filas[0]["ultimo_movimiento"] is not None


def test_la_caja_se_abre_por_tipo_y_medio_de_pago(cliente, escenario):
    filas = cliente.get("/api/reportes/caja?desde=2026-07-01&hasta=2026-07-31").json()
    por_clave = {(f["tipo"], f["medio_pago"]): f for f in filas}
    assert Decimal(por_clave[("ingreso", "transferencia")]["importe"]) == Decimal("1500.00")
    assert Decimal(por_clave[("egreso", "efectivo")]["importe"]) == Decimal("300.00")
    assert len(filas) == 2
    # Control del rango: en agosto no hubo caja.
    assert cliente.get("/api/reportes/caja?desde=2026-08-01").json() == []


def test_las_rutas_se_agrupan_por_par_origen_destino(cliente, escenario):
    """Suipacha→Rosario dos veces, y la vuelta es OTRA ruta."""
    filas = cliente.get("/api/reportes/por-ruta").json()
    rutas = {(f["origen"], f["destino"]): f for f in filas}
    assert rutas[("Suipacha", "Rosario")]["ordenes"] == 2
    assert Decimal(rutas[("Suipacha", "Rosario")]["total"]) == Decimal("3630.00")
    assert rutas[("Rosario", "Suipacha")]["ordenes"] == 1
    assert rutas[("Suipacha", "Mercedes")]["ordenes"] == 1
    # La anulada era Suipacha→Rosario: si contara, serían 3.
    assert sum(f["ordenes"] for f in filas) == 4


def test_lo_facturado_por_razon_social(cliente, escenario):
    filas = cliente.get("/api/reportes/por-razon-social").json()
    assert len(filas) == 1
    assert filas[0]["razon_social"] == "Suitrans"
    assert filas[0]["comprobantes"] == 1
    assert Decimal(filas[0]["total"]) == Decimal("3630.00")


def test_sin_sesion_no_se_ven_los_reportes(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        for ruta in ("resumen", "por-cliente", "saldos", "caja", "por-ruta"):
            assert anonimo.get(f"/api/reportes/{ruta}").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
