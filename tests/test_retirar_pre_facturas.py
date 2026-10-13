"""La revisión `0029`: se borran las pre facturas de LibraCargo, con las reservas de sus órdenes (ADR-048).

Se arma una base como la de antes —en la `0028`, con sus dos tablas y pre facturas en todos los estados— y se sube a la
`0029` mirando **qué pasó con los datos**:

- se borran las pre facturas de LibraCargo (pendiente, enviada, aceptada, anulada y la ya facturada) y sus reservas;
- las órdenes que estaban reservadas **siguen pendientes y libres**: vuelven a «Facturar pendientes»;
- la factura que salió de una pre factura **no se toca**, ni sus órdenes facturadas;
- la bandeja del motor (`comprobantes_pendientes`) **no se dropea ni pierde lo de otros productos**;
- cuenta y deja el rastro de lo que borra (log y `auditoria`), y es idempotente.

Los datos son ficticios: «Agro Norte», «Molino Sur».
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from libracore import pre_facturas as dominio
from libracore.db import comprobantes_pendientes as bandeja
from libracore.db import core as libracore_core
from libracore.db import facturas as db_facturas
from sqlalchemy import text

from tests.conftest import URL, URL_CORE, rearmar_en

RAIZ = Path(__file__).resolve().parents[1]


def _alembic(destino: str, *, bajar: bool = False) -> None:
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        (command.downgrade if bajar else command.upgrade)(cfg, destino)
    finally:
        if previo is not None:
            os.environ["DATABASE_URL"] = previo


def _modulo():
    spec = importlib.util.spec_from_file_location(
        "m0029", RAIZ / "migrations" / "versions" / "0029_retirar_pre_facturas.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql(con, sentencia: str, **params):
    return con.execute(text(sentencia), params)


@pytest.fixture
def base_de_antes(engine, sesion):
    """La base en la `0028`. Al salir vuelve a `head` y vacía."""
    rearmar_en("0028")
    try:
        yield engine
    finally:
        sesion.rollback()
        with engine.begin() as con:
            for tabla in ("pre_factura_ordenes", "pre_facturas_cargo", "ordenes_carga", "comprobantes_cargo",
                          "comprobante_de_apertura", "configuracion_empresa", "terceros", "auditoria"):
                if con.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar():
                    _sql(con, f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")
            for tabla in ("comprobantes_pendientes", "facturas"):
                _sql(con, f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")
        _alembic("head")


def _sembrar(engine) -> dict:
    """Cuatro órdenes, un cliente y pre facturas en todos los estados, más una fila de otro producto en la bandeja."""
    with engine.begin() as con:
        _sql(con, "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, es_fletero, "
                  "es_proveedor, activo) VALUES (1, 'Agro Norte', 'responsable_inscripto', true, false, false, true)")
        _sql(con, "INSERT INTO localidades (id, nombre, activa) VALUES (1, 'Suipacha', true), (2, 'Rosario', true)")
        for i in range(1, 6):
            _sql(con, "INSERT INTO ordenes_carga (id, fecha, cliente_id, origen_id, destino_id, tarifa, alicuota_iva, "
                      "iva, total, comision, estado) VALUES (:i, '2026-09-01', 1, 1, 2, 100, 21, 21, 121, 0, "
                      "'pendiente')", i=i)
    libracore_core.configure(URL_CORE)
    item = {"description": "Flete", "qty": 1, "unit_price": 100.0, "iva_rate": 0.21}
    ids = {}

    def crear(clave, ordenes, **extra):
        pf = dominio.crear(
            origen_producto="libracargo", origen_instancia="", cliente_razon="Agro Norte",
            cliente_cuit="30-12345678-1", tipo_comprobante=1, fecha_sugerida="2026-09-01",
            items=[item | {"orden_id": o} for o in ordenes], **extra)
        ids[clave] = pf["id"]
        with engine.begin() as con:
            _sql(con, "INSERT INTO pre_facturas_cargo (pre_factura_id, cliente_id) VALUES (:p, 1)", p=pf["id"])
            for o in ordenes:
                _sql(con, "INSERT INTO pre_factura_ordenes (orden_id, pre_factura_id) VALUES (:o, :p)",
                     o=o, p=pf["id"])
        return pf

    crear("pendiente", [1, 2])
    crear("aceptada", [3])
    dominio.marcar_aceptada(ids["aceptada"], "admin")
    crear("anulada", [5])
    dominio.anular(ids["anulada"], "admin", "El cliente cambió el pedido")
    with engine.begin() as con:   # anular libera las órdenes (`servicios.pre_facturas.liberar`)
        _sql(con, "DELETE FROM pre_factura_ordenes WHERE pre_factura_id = :p", p=ids["anulada"])
    # Una ya facturada: su factura existe en `facturas` y sus órdenes están facturadas.
    crear("facturada", [4])
    factura_id = db_facturas.create_factura(
        1, 1, 1, "2026-09-01", "30-12345678-1", "Agro Norte", 1, [item], 100, 21, 121,
        ambiente="produccion", emisor_id=None)
    dominio.marcar_facturada(ids["facturada"], factura_id, "admin")
    with engine.begin() as con:
        _sql(con, "DELETE FROM pre_factura_ordenes WHERE pre_factura_id = :p", p=ids["facturada"])
        _sql(con, "INSERT INTO comprobantes_cargo (factura_id, cliente_id, anulado, created_at, updated_at) "
                  "VALUES (:f, 1, false, now(), now())", f=factura_id)
        _sql(con, "UPDATE ordenes_carga SET estado = 'facturada', comprobante_id = :f WHERE id = 4", f=factura_id)
    # Y una fila de la bandeja que NO es de LibraCargo.
    ajena, _ = bandeja.upsert_comprobante(
        origen_producto="contalibra", origen_instancia="demo", origen_tipo="remito", origen_id="R-1",
        cliente_razon="Otro Cliente SA", items=[{"description": "Flete", "qty": 1, "unit_price": 50.0}])
    ids["ajena"] = ajena
    ids["factura"] = factura_id
    return ids


def _pendientes_en_la_bandeja(con):
    return {r[0] for r in _sql(con, "SELECT origen_producto FROM comprobantes_pendientes")}


def test_se_borran_las_pre_facturas_de_libracargo_con_sus_reservas_y_nada_mas(base_de_antes, capsys):
    ids = _sembrar(base_de_antes)
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM pre_factura_ordenes").scalar() == 3
        assert _sql(con, "SELECT count(*) FROM comprobantes_pendientes").scalar() == 5

    _alembic("0029")

    with base_de_antes.connect() as con:
        # Las dos tablas propias ya no están; la bandeja del motor sí.
        assert _sql(con, "SELECT to_regclass('pre_factura_ordenes')").scalar() is None
        assert _sql(con, "SELECT to_regclass('pre_facturas_cargo')").scalar() is None
        assert _sql(con, "SELECT to_regclass('comprobantes_pendientes')").scalar() is not None
        # De la bandeja se fue lo de LibraCargo, en todos los estados, y quedó lo de otro producto intacto.
        assert _pendientes_en_la_bandeja(con) == {"contalibra"}
        (fila,) = _sql(con, "SELECT id, cliente_razon, estado FROM comprobantes_pendientes").all()
        assert tuple(fila) == (ids["ajena"], "Otro Cliente SA", "pendiente")
        # Las órdenes que estaban reservadas siguen pendientes y sin comprobante: vuelven a «Facturar pendientes».
        pendientes = _sql(con, "SELECT id FROM ordenes_carga WHERE estado = 'pendiente' AND comprobante_id IS NULL "
                               "ORDER BY id").all()
        assert [r[0] for r in pendientes] == [1, 2, 3, 5]
        # La factura que salió de una pre factura no se toca, ni su orden facturada.
        assert _sql(con, "SELECT count(*) FROM facturas WHERE id = :f", f=ids["factura"]).scalar() == 1
        assert _sql(con, "SELECT estado, comprobante_id FROM ordenes_carga WHERE id = 4").one() == (
            "facturada", ids["factura"])

    salida = capsys.readouterr().out
    assert "[0029] pre facturas de LibraCargo: 4" in salida
    assert "reservas de órdenes: 3 (3 órdenes vuelven a Facturar pendientes)" in salida
    for numero in ("PF-0001", "PF-0002", "PF-0003", "PF-0004"):
        assert f"se borra {numero}" in salida
    assert "facturada en el comprobante" in salida, "la ya facturada dice con qué comprobante quedó"


def test_deja_el_rastro_en_la_auditoria(base_de_antes):
    ids = _sembrar(base_de_antes)
    _alembic("0029")
    with base_de_antes.connect() as con:
        fila = _sql(con, "SELECT usuario_nombre, entidad, accion, datos_antes FROM auditoria").one()
    assert fila[:3] == ("migracion 0029", "pre_factura", "baja")
    antes = fila[3]
    assert antes["reservas"] == 3 and antes["ordenes"] == 3
    assert [p["numero"] for p in antes["pre_facturas"]] == ["PF-0001", "PF-0002", "PF-0003", "PF-0004"]
    assert {p["estado"] for p in antes["pre_facturas"]} == {"pendiente", "aceptado", "descartado", "facturado"}
    assert next(p for p in antes["pre_facturas"] if p["estado"] == "facturado")["factura_id"] == ids["factura"]


def test_es_idempotente_la_segunda_vez_no_hay_nada_que_borrar(base_de_antes, capsys):
    _sembrar(base_de_antes)
    modulo = _modulo()
    with base_de_antes.begin() as con:
        primera = modulo.retirar(con)
    assert primera["pre_facturas"] == 4 and primera["reservas"] == 3 and primera["ordenes"] == 3
    assert primera["por_estado"] == {"pendiente": 1, "aceptado": 1, "descartado": 1, "facturado": 1}

    capsys.readouterr()
    with base_de_antes.begin() as con:
        segunda = modulo.retirar(con)
    assert segunda == {"pre_facturas": 0, "por_estado": {}, "reservas": 0, "ordenes": 0}
    assert "ninguna, no hay nada que borrar" in capsys.readouterr().out
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM auditoria").scalar() == 1, "la segunda no deja otro rastro"
        assert _pendientes_en_la_bandeja(con) == {"contalibra"}


def test_sin_pre_facturas_no_escribe_ni_borra_nada(base_de_antes, capsys):
    """El caso de una instancia que nunca generó una: la migración corre igual y sólo dropea las dos tablas."""
    with base_de_antes.begin() as con:
        _sql(con, "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, es_fletero, "
                  "es_proveedor, activo) VALUES (1, 'Agro Norte', 'responsable_inscripto', true, false, false, true)")
    libracore_core.configure(URL_CORE)
    bandeja.upsert_comprobante(
        origen_producto="libradesk", origen_instancia="demo", origen_tipo="presupuesto", origen_id="P-9",
        cliente_razon="Otro SA", items=[{"description": "x", "qty": 1, "unit_price": 1.0}])

    _alembic("0029")

    assert "ninguna, no hay nada que borrar" in capsys.readouterr().out
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM auditoria").scalar() == 0
        assert _pendientes_en_la_bandeja(con) == {"libradesk"}
        assert _sql(con, "SELECT to_regclass('pre_factura_ordenes')").scalar() is None


def test_una_pre_factura_marcada_como_de_libracargo_sin_su_fila_propia_tambien_se_borra(base_de_antes):
    """Por si falta la fila de `pre_facturas_cargo`: el motor la marca como suya (`origen_producto`) y la bandeja
    quedaría con un fantasma que nadie puede abrir."""
    libracore_core.configure(URL_CORE)
    dominio.crear(origen_producto="libracargo", origen_instancia="", cliente_razon="Huérfana SA",
                  items=[{"description": "x", "qty": 1, "unit_price": 1.0, "iva_rate": 0.21}])
    _alembic("0029")
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM comprobantes_pendientes").scalar() == 0


def test_el_downgrade_recrea_las_dos_tablas_vacias(base_de_antes):
    _sembrar(base_de_antes)
    _alembic("0029")
    _alembic("0028", bajar=True)
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM pre_factura_ordenes").scalar() == 0
        assert _sql(con, "SELECT count(*) FROM pre_facturas_cargo").scalar() == 0
        assert _sql(con, "SELECT to_regclass('comprobantes_pendientes')").scalar() is not None
    # Y se vuelve a subir sin problema.
    _alembic("head")


def test_la_0030_agrega_la_marca_sin_tocar_ninguna_fila(base_de_antes):
    ids = _sembrar(base_de_antes)
    _alembic("0029")
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'comprobantes_cargo' "
                         "AND column_name = 'sin_ordenes'").scalar() == 0
    _alembic("0030")
    with base_de_antes.connect() as con:
        marca = _sql(con, "SELECT sin_ordenes FROM comprobantes_cargo WHERE factura_id = :f", f=ids["factura"]).one()
        assert marca[0] is False, "todo lo anterior agrupa órdenes"
    _alembic("0029", bajar=True)
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'comprobantes_cargo' "
                         "AND column_name = 'sin_ordenes'").scalar() == 0
    _alembic("head")
