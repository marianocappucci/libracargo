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


def _soltar(con) -> None:
    """Cierra las sesiones que hayan quedado abiertas y tira la base.

    🔴 Sin esto, **un test que falla rompe a los que siguen**: PostgreSQL no deja
    borrar una base con una sesion viva, y la conexion del test que se cayo sigue
    ahi. El resultado es un fallo real seguido de tres errores de arrastre, y el
    que mira el resumen no sabe cual fue el que importo.
    """
    con.execute(text(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{BASE_SCRATCH}' AND pid <> pg_backend_pid()"))
    con.execute(text(f"DROP DATABASE IF EXISTS {BASE_SCRATCH}"))


@pytest.fixture
def base_limpia():
    """Una base descartable, aparte de la de la suite."""
    admin = create_engine(_url_con_base(BASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        _soltar(con)
        con.execute(text(f"CREATE DATABASE {BASE_SCRATCH}"))
    url = _url_con_base(BASE_URL, BASE_SCRATCH)
    yield url
    with admin.connect() as con:
        _soltar(con)
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
            # 12 del dominio + alembic_version. Sube cuando entra una tabla nueva,
        # y ese es el punto: el numero se toca a mano al agregarla, asi una
        # tabla que aparece sin querer --por un modelo importado de mas-- se ve.
        assert tablas == 13
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


def test_el_schema_migrado_rechaza_el_equipo_duplicado(base_limpia):
    """La restriccion del equipo, sobre el schema que construye ALEMBIC.

    Los tests del ABM corren contra las tablas que crea `Base.metadata`, o sea
    el modelo. Eso no dice nada de la base real, que se construye migrando: las
    dos pueden divergir y el sintoma aparece en produccion. Acá se prueba la
    forma que va a tener la base de verdad.

    El caso es el que estaba roto: dos camiones con la misma patente de chasis y
    **sin acoplado**. Con la restriccion original —`UNIQUE` a secas sobre un par
    con una columna nullable— los dos entraban, porque `NULL` no colisiona con
    `NULL`.
    """
    from sqlalchemy.exc import IntegrityError

    command.upgrade(_alembic(base_limpia), "head")
    motor = create_engine(base_limpia)
    with motor.begin() as con:
        con.execute(text(
            "insert into vehiculos (patente_chasis, activo) values ('AB123CD', true)"
        ))
    with pytest.raises(IntegrityError, match="uq_vehiculos_equipo"):
        with motor.begin() as con:
            con.execute(text(
                "insert into vehiculos (patente_chasis, activo) values ('AB123CD', true)"
            ))
    # Control positivo: otra patente SÍ entra. Sin esto, un insert que fallara
    # por cualquier otro motivo —una columna que falta, un default ausente—
    # daria el mismo verde.
    with motor.begin() as con:
        con.execute(text(
            "insert into vehiculos (patente_chasis, activo) values ('ZZ999ZZ', true)"
        ))
    motor.dispose()


def test_la_0005_completa_la_provincia_solo_donde_no_hay_duda(base_limpia):
    """Se corre la migración de verdad, con filas sembradas antes de que corra.

    Se sube hasta la **0004**, se siembran las localidades y recién ahí se sube
    a la 0005: si se sembraran después, la migración ya habría pasado y el test
    mediría la nada. El caso de `Chivilcoy` es el importante — tiene una
    provincia cargada a mano, equivocada a propósito, y **no se toca**: un dato
    que puso una persona vale más que uno deducido acá.
    """
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "0004")

        eng = create_engine(base_limpia)
        with eng.begin() as con:
            for nombre, provincia in [
                ("Suipacha", None),          # una sola en el catalogo -> se completa
                ("Capilla del Señor", None),  # idem, y ademas prueba los acentos
                ("San Pedro", None),         # en ocho provincias -> ambigua, no se toca
                ("Cnel. Bogado", None),      # abreviatura, no matchea -> no se toca
                ("Shap", None),              # no es una localidad -> no se toca
                ("Chivilcoy", "Cordoba"),    # cargada a mano y MAL -> no se toca
            ]:
                con.execute(
                    text("INSERT INTO localidades (nombre, provincia, activa) "
                         "VALUES (:n, :p, true)"),
                    {"n": nombre, "p": provincia})

        command.upgrade(cfg, "head")

        with eng.connect() as con:
            filas = dict(con.execute(
                text("SELECT nombre, provincia FROM localidades")).fetchall())

        assert filas["Suipacha"] == "Buenos Aires"
        assert filas["Capilla del Señor"] == "Buenos Aires"
        # Los cuatro que no se tocan, y cada uno por un motivo distinto.
        assert filas["San Pedro"] is None, "una localidad ambigua no se resuelve sola"
        assert filas["Cnel. Bogado"] is None, "una abreviatura no matchea, y esta bien"
        assert filas["Shap"] is None
        assert filas["Chivilcoy"] == "Cordoba", "piso un dato cargado a mano"
        eng.dispose()
    finally:
        if original:
            os.environ["DATABASE_URL"] = original
