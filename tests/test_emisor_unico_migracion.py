"""La revisión `0020`: se retira la razón social y «Datos de la empresa» queda como único emisor (ADR-035).

Se arma una base como la de antes —en la `0019`, con su tabla `razones_sociales` y la columna `razon_social_id`
repartida en cuatro tablas— con distintos estados de `configuracion_empresa`, y se sube a la `0020` mirando
**qué pasó con los datos**: lo que sólo estaba en la razón social se copia a la empresa, **lo que la empresa ya
tenía no se pisa**, y el texto libre de la condición de IVA pasa a la enumeración sólo si se reconoce.

Los datos son ficticios: «Transportes de Prueba», «Otra Demo SA», CUIT con dígito verificador válido.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from tests.conftest import URL, rearmar_en

RAIZ = Path(__file__).resolve().parents[1]

CUIT_RAZON = "30-55667788-9"
CUIT_EMPRESA = "30-12345678-1"


def _migracion():
    """El módulo de la `0020`, cargado por su ruta (el nombre empieza con un dígito)."""
    ruta = RAIZ / "migrations" / "versions" / "0020_emisor_unico.py"
    spec = importlib.util.spec_from_file_location("m0020", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


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


def _sql(con, sentencia: str, **params):
    return con.execute(text(sentencia), params)


@pytest.fixture
def base_de_antes(engine, sesion):
    """La base en la `0019`. Al salir vuelve a `head` y vacía."""
    rearmar_en("0019")
    try:
        yield engine
    finally:
        sesion.rollback()
        with engine.begin() as con:
            for tabla in ("pre_facturas_cargo", "ordenes_carga", "comprobantes_cargo",
                          "comprobante_de_apertura", "razones_sociales", "configuracion_empresa",
                          "terceros"):
                if con.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar():
                    _sql(con, f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")
        _alembic("head")


def _razon(con, nombre, cuit=None, condicion="responsable_inscripto", activa=True, legado=None):
    _sql(con, "INSERT INTO razones_sociales (nombre, cuit, condicion_iva, punto_venta, activa, codigo_legado) "
              "VALUES (:n, :c, CAST(:i AS condicion_iva), 1, :a, :l)",
         n=nombre, c=cuit, i=condicion, a=activa, l=legado)


def _empresa(con, razon_social="Transportes de Prueba SRL", cuit=None, condicion=None):
    _sql(con, "INSERT INTO configuracion_empresa (id, razon_social, cuit, condicion_iva) "
              "VALUES (1, :r, :c, :i)", r=razon_social, c=cuit, i=condicion)


def _leer_empresa(engine):
    with engine.connect() as con:
        fila = _sql(con, "SELECT razon_social, cuit, condicion_iva::text FROM configuracion_empresa").all()
    return fila[0] if fila else None


# ── Lo que se copia a la empresa ────────────────────────────────────────────


def test_con_la_empresa_vacia_y_una_razon_social_se_copia_todo(base_de_antes):
    """El caso de una instancia que sólo había cargado la razón social: la empresa no existía."""
    with base_de_antes.begin() as con:
        _razon(con, "Transportes de Prueba SRL", CUIT_RAZON, "responsable_inscripto")

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_RAZON, "responsable_inscripto")


def test_la_empresa_que_ya_tiene_cuit_lo_conserva_y_recibe_la_condicion_que_le_faltaba(base_de_antes):
    """🔑 El caso de Suitrans: una razón social sin CUIT y la empresa con el suyo, sin condición de IVA."""
    with base_de_antes.begin() as con:
        _razon(con, "Suitrans", None, "responsable_inscripto", legado=1)
        _empresa(con, "Transportes de Prueba SRL", CUIT_EMPRESA, None)

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_EMPRESA, "responsable_inscripto")


def test_lo_que_la_empresa_ya_tiene_no_se_pisa(base_de_antes):
    """La razón social dice otro CUIT y otra condición: manda lo que la empresa ya tenía."""
    with base_de_antes.begin() as con:
        _razon(con, "Otra Demo SA", CUIT_RAZON, "monotributo")
        _empresa(con, "Transportes de Prueba SRL", CUIT_EMPRESA, "Responsable Inscripto")

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_EMPRESA, "responsable_inscripto")


def test_si_la_empresa_no_tiene_razon_social_se_copia_el_nombre(base_de_antes):
    with base_de_antes.begin() as con:
        _razon(con, "Transportes de Prueba SRL", CUIT_RAZON)
        _empresa(con, "", None, None)

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_RAZON, "responsable_inscripto")


def test_con_dos_razones_sociales_se_elige_la_unica_con_cuit(base_de_antes):
    """El legado facturaba con dos nombres: la que tiene CUIT es el emisor, y la otra se descarta."""
    with base_de_antes.begin() as con:
        _razon(con, "Otra Demo SA", None, "monotributo", legado=2)
        _razon(con, "Transportes de Prueba SRL", CUIT_RAZON, "responsable_inscripto", legado=1)

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_RAZON, "responsable_inscripto")


def test_con_dos_razones_sociales_ambiguas_no_se_adivina_el_cuit(base_de_antes):
    """Sin una única razón con CUIT no se elige: la fila se crea con el nombre de la primera activa, sin CUIT."""
    with base_de_antes.begin() as con:
        _razon(con, "Otra Demo SA", CUIT_RAZON, "monotributo", activa=False, legado=2)
        _razon(con, "Transportes de Prueba SRL", "30-99999999-7", "responsable_inscripto", legado=1)

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", None, None)


def test_sin_razones_sociales_ni_empresa_no_se_inventa_nada(base_de_antes):
    _alembic("0020")
    assert _leer_empresa(base_de_antes) is None


# ── El texto libre pasa a la enumeración ────────────────────────────────────


@pytest.mark.parametrize("texto, esperado", [
    ("Responsable Inscripto", "responsable_inscripto"),
    ("IVA Responsable Inscripto", "responsable_inscripto"),
    ("  responsable   inscripto ", "responsable_inscripto"),
    ("Resp. Inscripto", "responsable_inscripto"),
    ("RI", "responsable_inscripto"),
    ("Monotributo", "monotributo"),
    ("Monotributista", "monotributo"),
    ("Responsable Monotributo", "monotributo"),
    ("Exento", "exento"),
    ("IVA Sujeto Exento", "exento"),
    ("Consumidor Final", "consumidor_final"),
    ("No Alcanzado", None),
    ("No Inscripto", None),
    ("No responsable", None),
    ("algo raro", None),
    ("", None),
    (None, None),
])
def test_el_texto_de_la_condicion_se_reconoce_o_queda_en_nulo(texto, esperado):
    assert _migracion()._condicion_de(texto) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("Monotributista", "monotributo"),
    ("Régimen simplificado raro", None),
])
def test_la_migracion_mapea_la_condicion_de_la_empresa(base_de_antes, texto, esperado):
    with base_de_antes.begin() as con:
        _empresa(con, "Transportes de Prueba SRL", CUIT_EMPRESA, texto)

    _alembic("0020")

    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_EMPRESA, esperado)


# ── Lo que se quita, y que se puede volver ──────────────────────────────────


def test_se_quitan_la_tabla_y_las_columnas_y_las_filas_siguen(base_de_antes):
    """Los datos de las tablas que perdían la columna siguen: sólo se quitó el vínculo a la razón social."""
    with base_de_antes.begin() as con:
        _razon(con, "Transportes de Prueba SRL", CUIT_RAZON)
        _sql(con, "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, es_fletero, "
                  "es_proveedor, activo) VALUES (1, 'Agro Norte', 'responsable_inscripto', true, false, "
                  "false, true)")
        _sql(con, "INSERT INTO localidades (id, nombre, activa) VALUES (1, 'Suipacha', true), (2, 'Rosario', true)")
        _sql(con, "INSERT INTO ordenes_carga (id, fecha, cliente_id, origen_id, destino_id, tarifa, alicuota_iva, "
                  "iva, total, comision, estado, razon_social_id) VALUES (1, '2026-07-30', 1, 1, 2, 100, 21, 21, "
                  "121, 0, 'pendiente', 1)")

    _alembic("0020")

    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT to_regclass('razones_sociales')").scalar() is None
        for tabla in ("ordenes_carga", "comprobantes_cargo", "pre_facturas_cargo", "comprobante_de_apertura"):
            columnas = {r[0] for r in _sql(
                con, "SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=tabla)}
            assert columnas and "razon_social_id" not in columnas, tabla
        assert _sql(con, "SELECT total FROM ordenes_carga WHERE id = 1").scalar() == 121
        # El tipo se queda: lo usa `terceros`.
        assert _sql(con, "SELECT count(*) FROM pg_type WHERE typname = 'condicion_iva'").scalar() == 1


def test_bajar_y_volver_a_subir_conserva_la_empresa_y_recrea_una_razon_social(base_de_antes):
    """El `downgrade` recrea la estructura con **una** razón social hecha de la empresa; subir no pierde nada."""
    with base_de_antes.begin() as con:
        _empresa(con, "Transportes de Prueba SRL", CUIT_EMPRESA, "Monotributo")
    _alembic("0020")
    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_EMPRESA, "monotributo")

    _alembic("0019", bajar=True)
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT nombre, cuit, condicion_iva::text, punto_venta, activa FROM razones_sociales"
                    ).all() == [("Transportes de Prueba SRL", CUIT_EMPRESA, "monotributo", 1, True)]
        assert _sql(con, "SELECT condicion_iva FROM configuracion_empresa").scalar() == "Monotributista"
        columnas = {r[0] for r in _sql(
            con, "SELECT column_name FROM information_schema.columns WHERE table_name = 'ordenes_carga'")}
        assert "razon_social_id" in columnas

    _alembic("0020")
    assert _leer_empresa(base_de_antes) == ("Transportes de Prueba SRL", CUIT_EMPRESA, "monotributo")
    with base_de_antes.connect() as con:
        assert _sql(con, "SELECT to_regclass('razones_sociales')").scalar() is None
