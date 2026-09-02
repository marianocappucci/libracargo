from __future__ import annotations

import datetime
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libracore import config_manager
from libracore.db import core as libracore_core
from libracore.db.schema import init_core_schema
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import db
from app.config import Config
from app.main import crear_app
from app.models import Base

URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/libracargo_test"
)

#: La base de **LibraCore**, que es otra. No es una preferencia de la suite: el
#: schema del motor declara `usuarios` y `auth_log`, y las dos ya existen del
#: lado del dominio con la forma de `libraauth`. En una sola base el segundo
#: `CREATE TABLE IF NOT EXISTS` no hace nada y el motor termina leyendo la tabla
#: del otro — que es un verde que no dice nada.
URL_CORE = os.environ.get(
    "LIBRACARGO_LIBRACORE_DATABASE_URL",
    "postgresql+psycopg://postgres@127.0.0.1:5433/libracargo_test_core",
)


def par_de_arca() -> tuple[bytes, bytes]:
    """Un certificado y su clave, de verdad y hechos en el momento.

    De verdad y no dos strings: el motor valida el par **antes** de escribirlo
    —lee el X.509, lee la clave y compara las públicas— así que un par de
    mentira no llega ni a guardarse, y el test mediría el 422 en vez de lo que
    quería medir.

    Se generan en cada llamada en vez de venir de un archivo del repo: uno
    fijo vence, y el día que venza el rojo aparece lejos de la causa —en un
    test de backup, por ejemplo— con un mensaje sobre fechas.
    """
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=730))
        .sign(clave, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        clave.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption()),
    )


def config_de_prueba(**extra) -> Config:
    """El `Config` de la suite, con las DOS bases.

    Existe porque `database_url_core` no tiene default —a propósito: caer en la
    base del dominio es justo el choque que la separación evita— y sin esto
    cada archivo de test tendría que acordarse de la segunda URL. Catorce
    copias de la misma línea es de donde salen las divergencias.
    """
    return Config(**{
        "database_url": os.environ["DATABASE_URL"],
        "database_url_core": URL_CORE,
        "entorno": "test",
        "debug": False,
        **extra,
    })


@pytest.fixture(scope="session", autouse=True)
def _schema_de_libracore():
    """Crea el schema del motor una vez para toda la suite.

    En producción esto lo hace `libracore-migrar upgrade --prefijo libracargo`,
    declarado en el deploy; acá se llama al DDL directo para no arrastrar
    alembic a cada corrida. Es la baseline de esa misma cadena, así que crea lo
    mismo.
    """
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        init_core_schema(conn)
    yield


@pytest.fixture(autouse=True)
def _arca_de_cero(tmp_path, monkeypatch):
    """Cada test arranca sin fila de `arca_config` y con su propio `CERTS_DIR`.

    🔴 **Los archivos importan tanto como la fila, y por una razón que no es
    obvia:** `resolve_cert_paths` rescata un path obsoleto cayendo al **nombre
    estándar** dentro de `CERTS_DIR`. Un certificado que quedó de otro test se
    **revive** ahí, así que un test que cree estar arrancando sin credenciales
    puede encontrarlas puestas — y el que mide "sin par no emite" pasaría a
    verde por el motivo equivocado.

    Se parcha `config_manager.CERTS_DIR` y no se exporta `DATA_DIR` antes de los
    imports: el módulo lo resuelve **al importarse**, así que la variable de
    entorno sólo funcionaría desde arriba de todo el archivo, empujando cada
    import de la suite abajo de una asignación. El router lo lee en cada
    request —`_certs_dir()` existe justamente para eso— así que el parche
    alcanza, y de paso el aislamiento es por test y no por corrida.
    """
    monkeypatch.setattr(config_manager, "CERTS_DIR", str(tmp_path / "arca_certs"))
    yield
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        conn.execute("DELETE FROM arca_config")


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


# ── Términos y Condiciones: aceptados para el resto de la suite ─────────────
#
# Desde libraauth v0.31.0 el motor corta con 403 **cualquier** llamada gateada
# por rol mientras la instancia no haya aceptado la versión vigente del
# contrato. Sin esta excepción, la suite entera se pone roja de golpe: cada
# test que loguea y pide datos recibe el 403 del gate en vez de lo que iba a
# medir, y el rojo no dice nada sobre el dominio.
#
# 🔴 **Esto NO apaga el gate donde importa.** Lo que la suite no puede es medir
# el dominio a través de un corte que no está probando; el corte tiene su propio
# archivo, `test_terminos_gate.py`, que se marca con `sin_aceptar_terminos` y
# queda afuera de esta excepción. Si alguien borrara el cableado de
# `app.state.terminos`, esa marca es lo único que se pondría rojo — el resto de
# la suite seguiría verde, porque no lo mira.


@pytest.fixture(autouse=True)
def _terminos_ya_aceptados(request):
    if request.node.get_closest_marker("sin_aceptar_terminos"):
        yield
        return

    from libraauth.terminos import TerminosRepository

    # 🔴 **`MonkeyPatch()` propio y no el fixture `monkeypatch`.** El fixture es
    # uno solo por test y lo comparten todas las fixtures que lo pidan, asi que
    # un `monkeypatch.undo()` en el cuerpo de un test —que existe, y es
    # legitimo— deshace TAMBIEN este parche y le prende el gate a la mitad del
    # test. El sintoma no se parece a la causa: la llamada siguiente devuelve
    # 403 y el test explota con un `KeyError` sobre la clave que esperaba en el
    # JSON. Lo encontro `test_despues_de_un_fallo_el_boton_puede_emitirlo` de
    # VentaLibra, que era el unico de las seis suites que llama `undo()`.
    mp = pytest.MonkeyPatch()
    mp.setattr(TerminosRepository, "esta_aceptada", lambda self: True)
    yield
    mp.undo()


# ── App logueada y maestros minimos ────────────────────────────────────────
#
# Viven aca y no en un modulo de test porque las usan varios. Importarlas de
# `test_comprobantes` ataba un archivo a otro y ademas ruff lo lee como
# redefinicion (F811) en cuanto el otro archivo las toma como parametro.

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch, _arca_de_cero):
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


def _crear(c, ruta, datos):
    r = c.post(ruta, json=datos)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def datos(cliente):
    """Los maestros mínimos para que una orden exista."""
    return {
        "cliente": _crear(cliente, "/api/terceros",
                          {"razon_social": "Agro Norte", "es_cliente": True}),
        "otro_cliente": _crear(cliente, "/api/terceros",
                               {"razon_social": "Molino Sur", "es_cliente": True}),
        "origen": _crear(cliente, "/api/localidades", {"nombre": "Suipacha"}),
        "destino": _crear(cliente, "/api/localidades", {"nombre": "Rosario"}),
        "razon": _crear(cliente, "/api/razones-sociales", {"nombre": "Suitrans"}),
        "otra_razon": _crear(cliente, "/api/razones-sociales", {"nombre": "Mauricio"}),
    }
