from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import db
from app.models import Base

URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/libracargo_test"
)


#: Secreto de firma de sesión para la suite. Fijo y evidente: no es una clave,
#: es una constante de test.
SECRETO_DE_PRUEBA = "libracargo-suite-no-es-un-secreto-real"


@pytest.fixture(autouse=True)
def _secreto_de_sesion(monkeypatch):
    """`SessionAuth` no se construye sin `SECRET_KEY` (salvo `ENV=development`).

    Va acá, autouse, porque si no la suite pasa o falla según lo que tenga
    exportado el shell de quien la corre: local con `ENV=development` daba
    verde, y el CI —que no lo tiene— habría dado rojo en tres tests con un
    error que no habla de la causa. Un test tiene que traer su entorno, no
    heredarlo.
    """
    monkeypatch.setenv("SECRET_KEY", SECRETO_DE_PRUEBA)


@pytest.fixture(autouse=True)
def _sin_pools_colgados():
    """Cierra el pool que dejó `crear_app()`, si el test armó una app.

    🔴 **Sin esto la suite se queda sin conexiones y el error no habla de la
    causa.** Cada `crear_app()` construye un engine nuevo y lo deja en el módulo
    `db`; el anterior queda con su pool abierto hasta que el recolector lo
    junte. Con ~190 tests que arman una app cada uno, eso pasa las 100
    conexiones de PostgreSQL y el fallo sale como
    `FATAL: sorry, too many clients already` en un test cualquiera — el que
    tuvo la mala suerte de ser el número 100, que no tiene nada que ver.

    Peor todavía: depender del recolector lo vuelve **no determinista**. Andaba
    con 181 tests, se cayó con 189, y el número exacto depende de cuándo corre
    el GC. Un límite que se cruza según el orden de los tests es un rojo que
    aparece en el CI de otro y no se reproduce.
    """
    yield
    if db._engine is not None:
        db._engine.dispose()


@pytest.fixture(scope="session")
def engine():
    """Los tests corren contra PostgreSQL real, nunca contra SQLite.

    Una suite verde sobre SQLite no dice nada del motor de producción: no
    chequea las FK con el pragma apagado y acepta una cadena donde la base
    pide un entero. Es la regla del ecosistema desde el 2026-08-12.
    """
    eng = create_engine(URL)
    with eng.connect() as con:
        assert con.dialect.name == "postgresql", "la suite exige PostgreSQL"
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def sesion(engine):
    Sesion = sessionmaker(bind=engine, expire_on_commit=False)
    s = Sesion()
    yield s
    s.rollback()
    for tabla in reversed(Base.metadata.sorted_tables):
        s.execute(text(f'TRUNCATE TABLE "{tabla.name}" RESTART IDENTITY CASCADE'))
    s.commit()
    s.close()
