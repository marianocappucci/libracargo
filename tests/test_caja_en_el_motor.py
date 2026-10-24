"""La caja de LibraCargo es la del motor (ADR-055): alta, anulación, edición, ganchos y reportes.

Cada movimiento es una fila de `caja_movimientos` más su fila propia en `movimientos_caja_cargo`, **con el mismo id**.
Lo escribe `libracore.db.caja` con la conexión de la sesión, así que corren los ganchos de caja del motor (ADR-076)
dentro de la misma transacción. En un nodo corregir es anular y cargar de nuevo.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.testing import crear_schema_de_auth
from libracore.ganchos_de_caja import GanchosDeCaja
from sqlalchemy import text

from app.main import crear_app
from app.servicios import caja as servicio_de_caja
from tests.conftest import config_de_prueba, vaciar_auth

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    c = TestClient(crear_app(config_de_prueba()), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    vaciar_auth(engine)


@pytest.fixture
def tercero(cliente):
    r = cliente.post("/api/terceros", json={
        "razon_social": "Agro Norte", "es_cliente": True, "es_fletero": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def cobro(tercero_id, **extra):
    base = {"fecha": "2026-08-21", "tipo": "ingreso", "concepto": "Cobro", "importe": "100000.00",
            "tercero_id": tercero_id, "rol": "cliente", "descripcion": "Cheque 1234", "recibo": "0001-0000045"}
    base.update(extra)
    return base


def _sql(engine, sentencia: str, **params):
    with engine.connect() as con:
        return con.execute(text(sentencia), params).all()


def _monto(engine, id_: int) -> Decimal:
    return Decimal(_sql(engine, "SELECT monto::text FROM caja_movimientos WHERE id = :i", i=id_)[0][0])


def _saldo(cliente, rol, tercero_id) -> Decimal:
    r = cliente.get(f"/api/cuentas/{rol}/{tercero_id}")
    assert r.status_code == 200, r.text
    assert r.json()["coinciden"] is True          # F4: la base y Python suman lo mismo
    return Decimal(r.json()["saldo"])


# ── Alta ────────────────────────────────────────────────────────────────────


def test_el_alta_es_una_fila_del_motor_y_una_fila_propia_con_el_mismo_id(cliente, engine, tercero):
    r = cliente.post("/api/caja", json=cobro(tercero))
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]
    assert r.json()["importe"] == "100000.00" and r.json()["anulado"] is False

    motor = _sql(engine, "SELECT fecha, tipo, concepto, monto, medio_pago, anulado, referencia, usuario_id, "
                         "turno_id, origen, origen_id FROM caja_movimientos WHERE id = :i", i=id_)
    assert len(motor) == 1
    fecha, tipo, concepto, monto, medio, anulado, referencia, usuario, turno, origen, origen_id = motor[0]
    assert (fecha, tipo, concepto, medio, anulado) == ("2026-08-21", "ingreso", "Cobro", "efectivo", 0)
    assert Decimal(monto) == Decimal("100000.00")
    # `referencia` queda vacía: es la clave de idempotencia del motor, y un recibo repetido no puede comerse un cobro.
    assert referencia == "" and turno is None and origen is None and origen_id is None
    assert usuario == _sql(engine, "SELECT id FROM usuarios WHERE username = :u", u=USUARIO)[0][0]

    propia = _sql(engine, "SELECT tercero_id, descripcion, recibo, origen_legado FROM movimientos_caja_cargo "
                          "WHERE movimiento_id = :i", i=id_)
    assert propia == [(tercero, "Cheque 1234", "0001-0000045", None)]

    # La cuenta corriente quedó atada al movimiento del motor, y el cobro bajó la deuda.
    asiento = _sql(engine, "SELECT a.rol, a.haber FROM cc_asientos a JOIN movimientos_cuenta_cargo c "
                           "ON c.asiento_id = a.id WHERE c.movimiento_caja_id = :i", i=id_)
    assert [(a[0], Decimal(a[1])) for a in asiento] == [("cliente", Decimal("100000.00"))]
    assert _saldo(cliente, "cliente", tercero) == Decimal("-100000.00")


def test_dos_altas_seguidas_toman_ids_distintos_de_la_secuencia_del_motor(cliente, engine, tercero):
    a = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    b = cliente.post("/api/caja", json=cobro(tercero, recibo="0001-0000045")).json()["id"]   # el mismo recibo
    assert b == a + 1
    assert _sql(engine, "SELECT count(*) FROM caja_movimientos")[0][0] == 2   # no se comió el repetido


@pytest.mark.parametrize("importe", ["0.01", "0.07", "0.10", "1.01", "33333.33", "999999999.99", "123456789012.34"])
def test_el_importe_llega_al_motor_exacto(cliente, engine, tercero, importe):
    id_ = cliente.post("/api/caja", json=cobro(tercero, importe=importe)).json()["id"]
    assert _monto(engine, id_) == Decimal(importe)
    assert _saldo(cliente, "cliente", tercero) == -Decimal(importe)


def test_un_gasto_general_no_mueve_ninguna_cuenta(cliente, engine):
    r = cliente.post("/api/caja", json={"fecha": "2026-08-21", "tipo": "egreso", "concepto": "Gasoil",
                                        "importe": "5000.00", "medio_pago": "transferencia"})
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]
    assert _sql(engine, "SELECT tercero_id FROM movimientos_caja_cargo WHERE movimiento_id = :i", i=id_) == [(None,)]
    assert _sql(engine, "SELECT medio_pago FROM caja_movimientos WHERE id = :i", i=id_) == [("transferencia",)]
    assert _sql(engine, "SELECT count(*) FROM movimientos_cuenta_cargo WHERE movimiento_caja_id = :i", i=id_) == [(0,)]


def test_la_caja_ya_no_acepta_un_importe_cero(cliente, tercero):
    """La `CHECK` de la tabla vieja (`importe > 0`) no tiene dónde vivir: lo dice el esquema y el servicio."""
    assert cliente.post("/api/caja", json=cobro(tercero, importe="0")).status_code == 422
    with pytest.raises(ValueError, match="mayor que cero"):
        servicio_de_caja.registrar(None, fecha=None, tipo=None, concepto="x", importe=Decimal("0"))


# ── Anulación y reportes ────────────────────────────────────────────────────


def test_anular_marca_el_movimiento_del_motor_revierte_la_cuenta_y_sale_de_los_reportes(cliente, engine, tercero):
    vigente = cliente.post(
        "/api/caja", json=cobro(tercero, importe="40000.00", medio_pago="transferencia")).json()["id"]
    anulado = cliente.post("/api/caja", json=cobro(tercero, importe="60000.00")).json()["id"]
    assert _saldo(cliente, "cliente", tercero) == Decimal("-100000.00")

    r = cliente.delete(f"/api/caja/{anulado}")
    assert r.status_code == 200 and r.json()["anulado"] is True
    # La fila queda (en las dos tablas) y el motor la marca; la cuenta tiene el original y su contraasiento.
    assert _sql(engine, "SELECT anulado FROM caja_movimientos WHERE id = :i", i=anulado) == [(1,)]
    assert _sql(engine, "SELECT count(*) FROM movimientos_caja_cargo WHERE movimiento_id = :i", i=anulado) == [(1,)]
    assert _sql(engine, "SELECT count(*) FROM movimientos_cuenta_cargo WHERE movimiento_caja_id = :i",
                i=anulado) == [(2,)]
    assert _saldo(cliente, "cliente", tercero) == Decimal("-40000.00")
    assert cliente.delete(f"/api/caja/{anulado}").status_code == 409

    # El listado lo muestra marcado; los totales no lo cuentan.
    lista = {m["id"]: m for m in cliente.get("/api/caja").json()}
    assert lista[anulado]["anulado"] is True and lista[vigente]["anulado"] is False
    caja = cliente.get("/api/reportes/caja").json()
    assert [(f["tipo"], f["medio_pago"], f["movimientos"], Decimal(f["importe"])) for f in caja] == [
        ("ingreso", "transferencia", 1, Decimal("40000.00"))]
    resumen = cliente.get("/api/reportes/resumen").json()
    assert resumen["movimientos_caja"] == 1 and Decimal(resumen["cobrado"]) == Decimal("40000.00")


def test_los_reportes_por_tercero_y_medio_siguen_dando_lo_mismo(cliente, tercero):
    otro = cliente.post("/api/terceros", json={"razon_social": "Molino Sur", "es_cliente": True}).json()["id"]
    cliente.post("/api/caja", json=cobro(tercero, importe="1000.00"))
    cliente.post("/api/caja", json=cobro(tercero, importe="250.50", medio_pago="cheque"))
    cliente.post("/api/caja", json=cobro(otro, importe="700.00"))
    cliente.post("/api/caja", json={"fecha": "2026-08-22", "tipo": "egreso", "concepto": "Peaje", "importe": "90.00"})
    por_tercero = cliente.get(f"/api/reportes/caja?tercero_id={tercero}").json()
    assert sorted((f["medio_pago"], Decimal(f["importe"])) for f in por_tercero) == [
        ("cheque", Decimal("250.50")), ("efectivo", Decimal("1000.00"))]
    solo_egresos = cliente.get("/api/reportes/caja?tipo=egreso").json()
    assert [(f["tipo"], Decimal(f["importe"])) for f in solo_egresos] == [("egreso", Decimal("90.00"))]
    assert cliente.get("/api/reportes/resumen").json()["movimientos_caja"] == 4
    assert len(cliente.get("/api/caja?medio_pago=cheque").json()) == 1


# ── Ganchos de caja del motor ───────────────────────────────────────────────


def _ganchos_que_anotan(engine, llamadas: list) -> GanchosDeCaja:
    def anotar(nombre):
        def gancho(conn, datos):
            # Con la conexión del cambio la fila ya se ve; desde otra conexión todavía no: no se confirmó.
            propia = conn.execute("SELECT count(*) FROM caja_movimientos WHERE id=?",
                                  (datos["movimiento_id"],)).fetchone()[0]
            ajena = _sql(engine, "SELECT count(*) FROM caja_movimientos WHERE id = :i", i=datos["movimiento_id"])[0][0]
            llamadas.append((nombre, datos, propia, ajena))
        return gancho
    return GanchosDeCaja(al_registrar_movimiento=anotar("registrar"), al_anular_movimiento=anotar("anular"))


def test_el_alta_y_la_anulacion_corren_los_ganchos_una_vez_dentro_de_la_transaccion(cliente, engine, tercero,
                                                                                   monkeypatch):
    llamadas = []
    monkeypatch.setattr(servicio_de_caja, "GANCHOS_DE_CAJA", _ganchos_que_anotan(engine, llamadas))

    id_ = cliente.post("/api/caja", json=cobro(tercero, importe="1234.56", medio_pago="cheque")).json()["id"]
    assert len(llamadas) == 1
    nombre, datos, propia, ajena = llamadas[0]
    assert nombre == "registrar" and (propia, ajena) == (1, 0)
    assert (datos["movimiento_id"], datos["tipo"], datos["concepto"], datos["monto"], datos["medio_pago"],
            datos["fecha"], datos["anulado"], datos["referencia"]) == (
        id_, "ingreso", "Cobro", 1234.56, "cheque", "2026-08-21", 0, "")

    # Editar no dispara nada: el motor no tiene gancho de modificación (por eso en el nodo no se edita).
    assert cliente.put(f"/api/caja/{id_}", json=cobro(tercero, importe="2000.00")).status_code == 200
    assert len(llamadas) == 1

    assert cliente.delete(f"/api/caja/{id_}").status_code == 200
    assert [nombre for nombre, *_ in llamadas] == ["registrar", "anular"] and llamadas[1][1]["anulado"] == 1
    # Una anulación repetida (409) no vuelve a subir.
    assert cliente.delete(f"/api/caja/{id_}").status_code == 409
    assert len(llamadas) == 2


def test_si_el_gancho_falla_no_queda_ni_el_movimiento_ni_su_asiento(cliente, engine, tercero, monkeypatch):
    def cae(conn, datos):
        raise RuntimeError("outbox caído")

    monkeypatch.setattr(servicio_de_caja, "GANCHOS_DE_CAJA", GanchosDeCaja(al_registrar_movimiento=cae))
    with pytest.raises(RuntimeError, match="outbox caído"):
        cliente.post("/api/caja", json=cobro(tercero))
    for tabla in ("caja_movimientos", "movimientos_caja_cargo", "cc_asientos"):
        assert _sql(engine, f"SELECT count(*) FROM {tabla}") == [(0,)], tabla


def test_si_el_gancho_de_anular_falla_el_movimiento_sigue_vigente_y_su_cuenta_intacta(cliente, engine, tercero,
                                                                                    monkeypatch):
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]

    def cae(conn, datos):
        raise RuntimeError("outbox caído")

    monkeypatch.setattr(servicio_de_caja, "GANCHOS_DE_CAJA", GanchosDeCaja(al_anular_movimiento=cae))
    with pytest.raises(RuntimeError, match="outbox caído"):
        cliente.delete(f"/api/caja/{id_}")
    assert _sql(engine, "SELECT anulado FROM caja_movimientos WHERE id = :i", i=id_) == [(0,)]
    assert _saldo(cliente, "cliente", tercero) == Decimal("-100000.00")


# ── Edición: en el central como siempre; en el nodo, anular y cargar de nuevo ──


def test_en_el_central_se_edita_el_movimiento_del_motor_y_su_fila_propia(cliente, engine, tercero):
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    r = cliente.put(f"/api/caja/{id_}", json=cobro(tercero, importe="80000.50", concepto="Cobro corregido",
                                                   fecha="2026-08-22", medio_pago="transferencia",
                                                   descripcion="Transferencia", recibo="0001-0000046"))
    assert r.status_code == 200, r.text
    assert (_sql(engine, "SELECT fecha, concepto, medio_pago FROM caja_movimientos WHERE id = :i", i=id_)
            == [("2026-08-22", "Cobro corregido", "transferencia")])
    assert _monto(engine, id_) == Decimal("80000.50")
    assert (_sql(engine, "SELECT descripcion, recibo FROM movimientos_caja_cargo WHERE movimiento_id = :i", i=id_)
            == [("Transferencia", "0001-0000046")])
    assert _saldo(cliente, "cliente", tercero) == Decimal("-80000.50")      # una línea por cuenta, no dos


def test_en_un_nodo_corregir_es_anular_y_cargar_de_nuevo(cliente, engine, tercero, monkeypatch):
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    monkeypatch.setenv("LIBRAEDGE_NODE_ID", "oficina-1")

    r = cliente.put(f"/api/caja/{id_}", json=cobro(tercero, importe="1.00"))
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "solo_en_el_central"
    assert "anulalo y cargalo de nuevo" in r.json()["detail"]["mensaje"]
    assert _monto(engine, id_) == Decimal("100000.00")

    # Lo que sí se puede: anular y cargar de nuevo. La cuenta queda como si se hubiera corregido.
    assert cliente.delete(f"/api/caja/{id_}").status_code == 200
    nuevo = cliente.post("/api/caja", json=cobro(tercero, importe="90000.00")).json()["id"]
    assert nuevo != id_
    assert _saldo(cliente, "cliente", tercero) == Decimal("-90000.00")
    assert _sql(engine, "SELECT anulado FROM caja_movimientos WHERE id = :i", i=id_) == [(1,)]

    # Fuera del nodo vuelve a andar: se lee en cada pedido.
    monkeypatch.delenv("LIBRAEDGE_NODE_ID")
    assert cliente.put(f"/api/caja/{nuevo}", json=cobro(tercero, importe="95000.00")).status_code == 200


def test_el_central_no_edita_un_movimiento_que_subio_de_un_nodo(cliente, engine, tercero):
    id_ = cliente.post("/api/caja", json=cobro(tercero)).json()["id"]
    with engine.begin() as con:     # como lo deja el aplicador del central (ADR-076 del motor)
        con.execute(text("UPDATE caja_movimientos SET origen = 'oficina-1', origen_id = 77 WHERE id = :i"), {"i": id_})
    r = cliente.put(f"/api/caja/{id_}", json=cobro(tercero, importe="1.00"))
    assert r.status_code == 409 and "vino de un nodo" in r.json()["detail"]
