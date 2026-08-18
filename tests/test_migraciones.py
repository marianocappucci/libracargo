"""La cadena de migraciones tiene que ser reversible de verdad.

El estándar del ecosistema exige rollback probado. "Probado" no es que
`downgrade` no tire error: es que después se pueda volver a subir.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/libracargo_test"
)
BASE_SCRATCH = "libracargo_migtest"


def _url_con_base(url: str, base: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(partes._replace(path=f"/{base}"))


@pytest.fixture
def base_limpia():
    """Una base descartable, aparte de la de la suite."""
    admin = create_engine(_url_con_base(BASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        con.execute(text(f"DROP DATABASE IF EXISTS {BASE_SCRATCH}"))
        con.execute(text(f"CREATE DATABASE {BASE_SCRATCH}"))
    url = _url_con_base(BASE_URL, BASE_SCRATCH)
    yield url
    with admin.connect() as con:
        con.execute(text(f"DROP DATABASE IF EXISTS {BASE_SCRATCH}"))
    admin.dispose()


def _alembic(url: str) -> Config:
    cfg = Config("alembic.ini")
    os.environ["DATABASE_URL"] = url
    return cfg


@pytest.fixture(autouse=True)
def _restaurar_database_url():
    """`_alembic` pisa DATABASE_URL para apuntar a la base descartable, y esa
    base se dropea al terminar. Sin restaurarla, cualquier test posterior que
    llame a `inicializar()` se conecta a una base que ya no existe."""
    previo = os.environ.get("DATABASE_URL")
    yield
    if previo is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previo


def test_upgrade_downgrade_upgrade(base_limpia):
    """El ciclo completo, que es donde apareció el defecto real.

    Alembic autogenera el `DROP TABLE` pero **no el de los tipos `ENUM`**. Sin
    los `DROP TYPE` explícitos, el downgrade deja los 7 tipos huérfanos y el
    upgrade siguiente muere con `DuplicateObject`. La migración parecía
    reversible y no lo era.
    """
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        eng = create_engine(base_limpia)
        with eng.connect() as con:
            enums = con.execute(
                text("SELECT count(*) FROM pg_type WHERE typtype = 'e'")
            ).scalar_one()
        assert enums == 0, "el downgrade dejó tipos ENUM huérfanos"

        # Si los tipos hubieran quedado, esto revienta.
        command.upgrade(cfg, "head")
        with eng.connect() as con:
            tablas = con.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )).scalar_one()
        assert tablas == 12  # 11 del dominio + alembic_version
        eng.dispose()
    finally:
        if original:
            os.environ["DATABASE_URL"] = original


def test_los_modelos_no_tienen_cambios_sin_migrar(base_limpia):
    """`alembic check`: el schema de los modelos y la cadena no divergen."""
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "head")
        command.check(cfg)  # levanta si hay diff pendiente
    finally:
        if original:
            os.environ["DATABASE_URL"] = original
