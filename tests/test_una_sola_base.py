"""Una sola base: el schema de LibraCore vive en la del dominio (etapa 3, salida A).

Lo que se fija acá es el camino que va a recorrer cada instancia que se una, el
mismo que se midió el 2026-10-05 sobre una copia de Suitrans:

1. Una base de antes tiene la clave primaria de `alembic_version_libracargo` con
   el nombre de la tabla vieja, `alembic_version_pkc`. Con ese nombre la cadena
   del motor no puede crear su propia `alembic_version` en la misma base:
   *relation "alembic_version_pkc" already exists*.
2. La revisión `0015` la renombra.
3. Y entonces `libracore-migrar` corre sobre la base del dominio y la deja en la
   última revisión del motor, sin tocar una fila del dominio.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from tests.conftest import URL

RAIZ = Path(__file__).resolve().parents[1]


def _nombre_de_la_clave(con) -> str:
    return con.execute(text(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = to_regclass('alembic_version_libracargo') AND contype = 'p'"
    )).scalar_one()


def _alembic() -> AlembicConfig:
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    return cfg


def test_una_base_de_antes_se_une_y_el_motor_migra_adentro(engine):
    # Como estaba una base de antes de la 0015: la clave con el nombre viejo y
    # sin la cadena del motor (la suite crea su schema con el DDL, sin Alembic).
    # Primero se saca la del motor: si otro test ya corrió su cadena, su clave
    # ocupa justo el nombre que hay que recrear.
    # La base de antes no tiene la `0016` (los comprobantes en `facturas`): se baja
    # de verdad, porque el rebobinado a mano de abajo sólo cambia el número.
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        command.downgrade(_alembic(), "0015")
    finally:
        if previo is not None:
            os.environ["DATABASE_URL"] = previo
    with engine.begin() as con:
        con.execute(text("DROP TABLE IF EXISTS alembic_version"))
        con.execute(text("ALTER TABLE alembic_version_libracargo "
                         "RENAME CONSTRAINT alembic_version_libracargo_pkc TO alembic_version_pkc"))
        con.execute(text("UPDATE alembic_version_libracargo SET version_num = '0014'"))

    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        command.upgrade(_alembic(), "head")
    finally:
        if previo is not None:
            os.environ["DATABASE_URL"] = previo

    with engine.connect() as con:
        assert _nombre_de_la_clave(con) == "alembic_version_libracargo_pkc"

    # La cadena del motor, contra la base del DOMINIO: es lo que hace el deploy
    # de una instancia unida, con las dos variables apuntando a la misma URL.
    r = subprocess.run(
        ["libracore-migrar", "upgrade", "--prefijo", "libracargo"],
        env={**os.environ, "LIBRACARGO_LIBRACORE_DATABASE_URL": URL, "DATABASE_URL": URL},
        capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    with engine.connect() as con:
        assert con.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        # Las dos cadenas conviven, cada una con su tabla y su clave.
        claves = set(con.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname LIKE 'alembic_version%'")).scalars())
        assert {"alembic_version_libracargo_pkc", "alembic_version_pkc"} <= claves


def test_la_0015_no_hace_nada_si_la_clave_ya_tiene_su_nombre(engine):
    """Una base creada después del renombre de la tabla ya nace con el nombre bueno."""
    with engine.connect() as con:
        antes = _nombre_de_la_clave(con)
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        command.downgrade(_alembic(), "0014")
        command.upgrade(_alembic(), "head")
    finally:
        if previo is not None:
            os.environ["DATABASE_URL"] = previo
    with engine.connect() as con:
        assert _nombre_de_la_clave(con) == antes == "alembic_version_libracargo_pkc"
