"""Cuentas corrientes y caja.

El criterio de F4 en el ROADMAP es que **el saldo de un tercero dé igual
calculado por dos caminos distintos**, y eso es lo que más se prueba acá.
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
    r = cliente.post("/api/terceros", json={"razon_social": "Agro Norte",
                                            "es_cliente": True, "es_fletero": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def caja(fecha, tipo, importe, **extra):
    return {"fecha": fecha, "tipo": tipo, "concepto": "cobro", "importe": importe, **extra}


def test_el_saldo_da_igual_por_los_dos_caminos(cliente, tercero):
    """El criterio de F4, sobre varios movimientos y con centavos.

    🔑 **Lo que este test detecta es una divergencia entre los dos caminos**, no
    el redondeo de un float. Medido con dos sabotajes: saltear una fila en el
    `SUM` de la base lo pone rojo, pero pasar el acumulado de Python por `float`
    **no** —float64 representa estos importes sin perder nada—.

    La pérdida documentada del legado es de `FLOAT` de **precisión simple** (4
    bytes, ~7 dígitos), que es otra cosa; decir "un float no representa esto
    exacto" a secas era una afirmación de más. Los `Decimal` se usan igual, y
    por el mismo motivo que la base usa `NUMERIC`: no depender de que el rango
    de importes de hoy siga entrando mañana.
    """
    for i, (tipo, importe) in enumerate([
        ("egreso", "1500000.55"), ("ingreso", "0.10"), ("egreso", "1234567.89"),
        ("ingreso", "987654.32"), ("egreso", "0.01"),
    ]):
        r = cliente.post("/api/caja", json=caja(
            f"2026-08-{10 + i:02d}", tipo, importe, tercero_id=tercero, rol="cliente"))
        assert r.status_code == 201, r.text

    c = cliente.get(f"/api/cuentas/cliente/{tercero}").json()
    assert c["coinciden"] is True
    assert Decimal(c["saldo"]) == Decimal(c["saldo_recorriendo"])
    # Y el numero, calculado a mano: los egresos suman, los ingresos restan.
    esperado = (Decimal("1500000.55") + Decimal("1234567.89") + Decimal("0.01")
                - Decimal("0.10") - Decimal("987654.32"))
    assert Decimal(c["saldo"]) == esperado
    # El saldo de la ultima fila es el saldo de la cuenta: si el acumulado se
    # calculara sobre otro orden, este seria otro numero.
    assert Decimal(c["movimientos"][-1]["saldo"]) == esperado


def test_sin_movimientos_el_saldo_es_cero_y_no_ausente(cliente, tercero):
    """`SUM` sobre cero filas devuelve NULL, y un saldo ausente no es un cero."""
    c = cliente.get(f"/api/cuentas/cliente/{tercero}").json()
    assert Decimal(c["saldo"]) == Decimal("0.00")
    assert c["coinciden"] is True
    assert c["movimientos"] == []


def test_cada_rol_es_una_cuenta_distinta(cliente, tercero):
    """El mismo tercero puede ser cliente y fletero: son dos cuentas."""
    cliente.post("/api/caja", json=caja("2026-08-10", "ingreso", "100.00",
                                        tercero_id=tercero, rol="cliente"))
    cliente.post("/api/caja", json=caja("2026-08-10", "egreso", "40.00",
                                        tercero_id=tercero, rol="fletero"))
    como_cliente = cliente.get(f"/api/cuentas/cliente/{tercero}").json()
    como_fletero = cliente.get(f"/api/cuentas/fletero/{tercero}").json()
    assert Decimal(como_cliente["saldo"]) == Decimal("-100.00")
    # 🔴 Este numero decia `40.00`, y era el mismo error que el codigo: el test
    # heredo la premisa de que el signo lo da el movimiento y no el rol.
    # Pagarle 40 a un fletero **baja** lo que se le debe. Con el saldo en +40,
    # la pantalla habria dicho que se le deben 40 justo despues de pagarle.
    assert Decimal(como_fletero["saldo"]) == Decimal("-40.00")


def test_el_signo_del_asiento_de_caja_depende_del_rol(cliente, tercero):
    """La tabla de la convencion, fijada en un test.

    Es la del legado y la de los 22.645 movimientos migrados: el cargo va a
    `debe` y el pago a `haber` en las tres cuentas. Lo que cambia es cual de
    los dos es un ingreso.
    """
    casos = [
        # rol,        tipo,      debe,      haber
        ("cliente",   "ingreso", "0.00",   "100.00"),   # cobranza
        ("cliente",   "egreso",  "100.00", "0.00"),     # devolucion al cliente
        ("fletero",   "egreso",  "0.00",   "100.00"),   # pago al fletero
        ("fletero",   "ingreso", "100.00", "0.00"),     # el fletero devuelve
        ("proveedor", "egreso",  "0.00",   "100.00"),   # pago al proveedor
        ("proveedor", "ingreso", "100.00", "0.00"),
    ]
    for rol, tipo, debe, haber in casos:
        t = cliente.post("/api/terceros", json={
            "razon_social": f"Tercero {rol} {tipo}", "es_cliente": True,
            "es_fletero": True, "es_proveedor": True}).json()["id"]
        r = cliente.post("/api/caja", json=caja("2026-08-10", tipo, "100.00",
                                                tercero_id=t, rol=rol))
        assert r.status_code == 201, r.text
        movs = cliente.get(f"/api/cuentas/{rol}/{t}").json()["movimientos"]
        assert len(movs) == 1, (rol, tipo)
        m = movs[0]["movimiento"]
        assert (Decimal(m["debe"]), Decimal(m["haber"])) == (Decimal(debe), Decimal(haber)), \
            f"{tipo} en la cuenta de {rol}"


def test_el_corte_por_fecha_mueve_los_dos_saldos_igual(cliente, tercero):
    cliente.post("/api/caja", json=caja("2026-08-01", "egreso", "100.00",
                                        tercero_id=tercero, rol="cliente"))
    cliente.post("/api/caja", json=caja("2026-08-20", "egreso", "50.00",
                                        tercero_id=tercero, rol="cliente"))
    c = cliente.get(f"/api/cuentas/cliente/{tercero}?hasta=2026-08-10").json()
    assert Decimal(c["saldo"]) == Decimal("100.00")
    assert c["coinciden"] is True


def test_un_movimiento_de_caja_deja_su_contrapartida(cliente, tercero):
    r = cliente.post("/api/caja", json=caja("2026-08-10", "ingreso", "250.00",
                                            tercero_id=tercero, rol="cliente"))
    assert r.status_code == 201
    c = cliente.get(f"/api/cuentas/cliente/{tercero}").json()
    assert len(c["movimientos"]) == 1
    m = c["movimientos"][0]["movimiento"]
    assert m["movimiento_caja_id"] == r.json()["id"]
    assert Decimal(m["haber"]) == Decimal("250.00")
    assert Decimal(m["debe"]) == Decimal("0.00")


def test_un_gasto_general_no_mueve_la_cuenta_de_nadie(cliente, tercero):
    r = cliente.post("/api/caja", json=caja("2026-08-10", "egreso", "80.00",
                                            concepto="nafta"))
    assert r.status_code == 201, r.text
    assert cliente.get(f"/api/cuentas/cliente/{tercero}").json()["movimientos"] == []


def test_con_tercero_pero_sin_rol_no_se_registra(cliente, tercero):
    """Un mismo tercero puede tener tres cuentas: sin rol no se sabe cual."""
    r = cliente.post("/api/caja", json=caja("2026-08-10", "ingreso", "10.00",
                                            tercero_id=tercero))
    assert r.status_code == 422
    assert "rol" in r.text
    # Y no quedo el movimiento de caja suelto.
    assert cliente.get("/api/caja").json() == []


def test_sin_sesion_no_se_ven_las_cuentas(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/cuentas/cliente/1").status_code == 401
        assert anonimo.get("/api/caja").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
