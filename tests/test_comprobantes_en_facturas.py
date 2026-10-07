"""La revisión `0016`: los comprobantes pasan a `facturas` del motor (ADR-030).

Se arma una base como la de antes —en la `0015`, con su tabla `comprobantes`—, con
lo que tiene Suitrans y un poco más: facturas con órdenes y cuenta corriente, una
anulada, una nota de crédito con su asociado y el comprobante de apertura con sus
órdenes. Después se sube a la `0016` y se mira que no se perdió ni se movió nada.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from app.models import Comprobante
from app.servicios.comprobantes import totales_facturados
from tests.conftest import URL, rearmar_en

RAIZ = Path(__file__).resolve().parents[1]


def _alembic(destino: str, *, subir: bool = False) -> None:
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        if destino == "head" or subir:
            command.upgrade(cfg, destino)
        else:
            # Una base «de antes» se arma de cero: desde la `0018` bajar no tiene vuelta.
            rearmar_en(destino)
    finally:
        if previo is not None:
            os.environ["DATABASE_URL"] = previo


def _sql(con, sentencia: str, **params):
    return con.execute(text(sentencia), params)


@pytest.fixture
def base_de_antes(engine, sesion):
    """La base en la `0015`, con datos. Al salir vuelve a `head` vacía."""
    _alembic("0015")
    try:
        _cargar(engine)
        yield engine
    finally:
        # La `sesion` del test se cierra DESPUÉS de esta fixture: si quedó con una
        # transacción abierta, el `TRUNCATE` de la limpieza la esperaría para siempre.
        sesion.rollback()
        _volver_a_head(engine)


def _cargar(engine):
    with engine.begin() as con:
        _sql(con, "INSERT INTO razones_sociales (id, nombre, condicion_iva, punto_venta, "
                  "codigo_legado, activa) VALUES (1, 'Suitrans', 'responsable_inscripto', 1, 1, true)")
        _sql(con, "INSERT INTO terceros (id, razon_social, cuit, condicion_iva, es_cliente, "
                  "es_fletero, es_proveedor, direccion, activo) VALUES "
                  "(1, 'ACOPIO SUR SA', '30-12345678-1', 'responsable_inscripto', true, false, "
                  "false, 'Ruta 9 km 300', true)")
        _sql(con, "INSERT INTO localidades (id, nombre, activa) VALUES (1, 'Suipacha', true), "
                  "(2, 'Rosario', true)")
        comprobantes = [
            # id, tipo, pv, nro, fecha, neto, iva, total, anulado, legado, asociado, motivo, cae
            (10, "factura_a", 1, 100, "2026-08-01", "1000.00", "210.00", "1210.00", False,
             "factura:100:1", None, None, None),
            (11, "factura_a", 1, 101, "2026-08-02", "500.00", "105.00", "605.00", True,
             None, None, None, None),
            (12, "factura_a", 1, 102, "2026-08-03", "2000.00", "420.00", "2420.00", False,
             None, None, None, "75000000000010"),
            (13, "nota_credito_a", 1, 1, "2026-08-04", "100.00", "21.00", "121.00", False,
             None, 12, "diferencia de kilos", "75000000000011"),
            (14, "factura_a", 0, 0, "2023-08-03", "300.00", "63.00", "363.00", False,
             "apertura", None, None, None),
        ]
        for (id_, tipo, pv, nro, fecha, neto, iva, total, anulado, legado, asociado, motivo,
             cae) in comprobantes:
            _sql(con, "INSERT INTO comprobantes (id, razon_social_id, tipo, punto_venta, numero, "
                      "fecha, cliente_id, neto, iva, total, anulado, origen_legado, "
                      "comprobante_asociado_id, motivo, cae, cae_vencimiento) VALUES "
                      "(:id, 1, :tipo, :pv, :nro, :fecha, 1, :neto, :iva, :total, :anulado, "
                      ":legado, :asociado, :motivo, :cae, :vto)",
                 id=id_, tipo=tipo, pv=pv, nro=nro, fecha=fecha, neto=neto, iva=iva, total=total,
                 anulado=anulado, legado=legado, asociado=asociado, motivo=motivo, cae=cae,
                 vto="2026-08-13" if cae else None)
        _sql(con, "SELECT setval(pg_get_serial_sequence('comprobantes', 'id'), 14)")
        ordenes = [
            # id, comprobante, tarifa, iva, total, estado, legado
            (1, 10, "600.00", "126.00", "726.00", "facturada", None),
            (2, 10, "400.00", "84.00", "484.00", "facturada", None),
            (3, None, "500.00", "105.00", "605.00", "pendiente", None),
            (4, 12, "2000.00", "420.00", "2420.00", "facturada", None),
            (5, 14, "300.00", "63.00", "363.00", "facturada", "carga:5"),
        ]
        for id_, comp, tarifa, iva, total, estado, legado in ordenes:
            _sql(con, "INSERT INTO ordenes_carga (id, fecha, cliente_id, origen_id, destino_id, "
                      "remito, tarifa, alicuota_iva, iva, total, comision, estado, razon_social_id, "
                      "comprobante_id, origen_legado) VALUES (:id, '2026-07-30', 1, 1, 2, :remito, "
                      ":tarifa, 21, :iva, :total, 0, :estado, 1, :comp, :legado)",
                 id=id_, remito=f"R-{id_}", tarifa=tarifa, iva=iva, total=total, estado=estado,
                 comp=comp, legado=legado)
        for id_, comp, debe, haber in ((1, 10, "1210.00", "0"), (2, 11, "605.00", "0"),
                                       (3, 11, "0", "605.00"), (4, 12, "2420.00", "0"),
                                       (5, 13, "0", "121.00")):
            _sql(con, "INSERT INTO movimientos_cuenta (id, fecha, tercero_id, rol, concepto, debe, "
                      "haber, comprobante_id) VALUES (:id, '2026-08-01', 1, 'cliente', 'c', :debe, "
                      ":haber, :comp)", id=id_, debe=debe, haber=haber, comp=comp)


def _volver_a_head(engine):
    with engine.begin() as con:
        for tabla in ("movimientos_cuenta", "movimientos_cuenta_cargo", "cc_asientos",
                      "movimientos_cuenta_legado", "ordenes_carga", "comprobantes_cargo",
                      "comprobante_de_apertura", "facturas", "comprobantes_legado", "localidades",
                      "terceros", "razones_sociales"):
            if con.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar():
                _sql(con, f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")
    # Si el test se cortó en la `0015`, el resto de la suite necesita `head`.
    # Siempre de vuelta a `head` (no hace nada si ya está).
    _alembic("head")


def test_la_0016_pasa_los_comprobantes_a_facturas_sin_mover_nada(base_de_antes, sesion):
    with base_de_antes.connect() as con:
        movimientos_antes = _sql(con, "SELECT id, comprobante_id, debe, haber FROM movimientos_cuenta "
                                      "ORDER BY id").all()
    # Hasta la `0016`: la `0018` borra `comprobantes_legado`, que acá se mira.
    _alembic("0016", subir=True)

    with base_de_antes.connect() as con:
        # La tabla vieja queda, renombrada; la apertura no entra a `facturas`.
        assert _sql(con, "SELECT count(*) FROM comprobantes_legado").scalar() == 5
        assert _sql(con, "SELECT array_agg(id ORDER BY id) FROM facturas").scalar() == [10, 11, 12, 13]
        assert _sql(con, "SELECT array_agg(factura_id ORDER BY factura_id) FROM comprobantes_cargo"
                    ).scalar() == [10, 11, 12, 13]
        # La secuencia sigue: el próximo comprobante no choca.
        assert _sql(con, "SELECT nextval(pg_get_serial_sequence('facturas', 'id'))").scalar() == 14

        f10 = _sql(con, "SELECT * FROM facturas WHERE id = 10").mappings().one()
        assert (f10["tipo"], f10["punto_venta"], f10["numero"], f10["fecha"]) == (1, 1, 100, "2026-08-01")
        assert (f10["subtotal"], f10["iva_amount"], f10["total"]) == (
            Decimal("1000.00"), Decimal("210.00"), Decimal("1210.00"))
        assert f10["ambiente"] == "produccion" and f10["emisor_id"] is None
        assert (f10["cliente_cuit"], f10["cliente_razon"], f10["cliente_iva_cond"]) == (
            "30-12345678-1", "ACOPIO SUR SA", 1)
        items = json.loads(f10["items"])
        assert [i["unit_price"] for i in items] == [600.0, 400.0]
        assert items[0]["detalle"] == "Orden 1 del 30/07/2026, remito R-1"

        # La nota, con su asociado en las dos formas: la FK y la terna que viaja a ARCA.
        f13 = _sql(con, "SELECT * FROM facturas WHERE id = 13").mappings().one()
        assert (f13["tipo"], f13["cbte_asoc_tipo"], f13["cbte_asoc_pv"], f13["cbte_asoc_nro"],
                f13["cbte_asoc_fecha"], f13["observaciones"], f13["cae"], f13["cae_vto"]) == (
            3, 1, 1, 102, "20260803", "diferencia de kilos", "75000000000011", "20260813")
        assert _sql(con, "SELECT comprobante_asociado_id FROM comprobantes_cargo "
                         "WHERE factura_id = 13").scalar() == 12

        # La apertura, con sus órdenes.
        apertura = _sql(con, "SELECT * FROM comprobante_de_apertura").mappings().one()
        assert (apertura["total"], apertura["origen_legado"]) == (Decimal("363.00"), "apertura")
        assert _sql(con, "SELECT comprobante_id, apertura_id, estado FROM ordenes_carga WHERE id = 5"
                    ).one() == (None, apertura["id"], "facturada")
        # Las demás órdenes y la cuenta corriente, intactas.
        assert _sql(con, "SELECT array_agg(comprobante_id ORDER BY id) FROM ordenes_carga "
                         "WHERE id < 5").scalar() == [10, 10, None, 12]
        assert _sql(con, "SELECT id, comprobante_id, debe, haber FROM movimientos_cuenta ORDER BY id"
                    ).all() == movimientos_antes

    # Y el producto lo lee como antes.
    sesion.expire_all()
    c11 = sesion.get(Comprobante, 11)
    assert c11.anulado is True and c11.neto == Decimal("500.00") and c11.fecha.isoformat() == "2026-08-02"
    c12 = sesion.get(Comprobante, 12)
    assert (c12.cae, c12.cae_vencimiento.isoformat()) == ("75000000000010", "2026-08-13")
    # El F5: 10 y 12 facturados, menos la nota de 12, de los dos lados. La apertura afuera.
    fila = totales_facturados(sesion)
    assert fila.coinciden is True
    assert fila.total_comprobantes == Decimal("1210.00") + Decimal("2420.00") - Decimal("121.00")


def test_la_0016_se_niega_si_dos_comprobantes_chocarian_en_la_numeracion(base_de_antes):
    """Dos razones sociales sin ARCA propio, con el mismo tipo, punto de venta y número."""
    with base_de_antes.begin() as con:
        _sql(con, "INSERT INTO razones_sociales (id, nombre, condicion_iva, punto_venta, "
                  "codigo_legado, activa) VALUES (2, 'Otra', 'responsable_inscripto', 1, 2, true)")
        _sql(con, "INSERT INTO comprobantes (id, razon_social_id, tipo, punto_venta, numero, fecha, "
                  "cliente_id, neto, iva, total, anulado) VALUES "
                  "(20, 2, 'factura_a', 1, 100, '2026-08-05', 1, 1, 0, 1, false)")
    with pytest.raises(RuntimeError, match="misma numeración"):
        _alembic("head")
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT to_regclass('comprobantes')").scalar() is not None, "no tocó nada"
        assert _sql(con, "SELECT count(*) FROM facturas").scalar() == 0
    with base_de_antes.begin() as con:
        _sql(con, "DELETE FROM comprobantes WHERE id = 20")
    _alembic("head")
