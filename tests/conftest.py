from __future__ import annotations

import datetime
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from libraauth import session_auth as _session_auth
from libraauth.captcha import Captcha
from libraauth.models import Base as AuthBase
from libraauth.testing import crear_schema_de_auth
from libracore import config_manager, pdf_generator
from libracore.db import core as libracore_core
from libracore.db.schema import init_core_schema
from libracore.testing.pg_por_worker import base_por_worker
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import db
from app.config import Config
from app.main import crear_app
from app.models import Base

RAIZ = Path(__file__).resolve().parent.parent

# --- Una base por worker de xdist ------------------------------------------
# La suite corre con `pytest -n 4` (reglas/ci.md del wiki) y los workers no pueden
# compartir base: cada test vacia y rearma tablas (`engine`, `sesion`, `cliente`),
# asi que dos procesos se pisarian el schema. El mecanismo vive en
# `libracore.testing.pg_por_worker` (libracore >= v1.122.0): crea `<base>_gwN` y la
# borra al salir.
#
# Son DOS bases, como siempre (ver `URL_CORE`), asi que son dos `base_por_worker`:
# `libracargo_test_gwN` y `libracargo_test_core_gwN`. Cada una pide que exista la
# ORIGINAL (`libracargo_test` la crea el servicio de PostgreSQL del CI;
# `libracargo_test_core`, el paso "Base de LibraCore" del job: lo mismo que ya
# hacia falta antes, cuando la suite iba directo a ella).
#
# 🔴 **SIN plantillas (`restaurar()`), a proposito.** A diferencia de VentaLibra o
# LibraCommerce, esta suite NO rearma la base en cada test: arma el schema UNA vez
# por sesion (`engine`, la cadena de Alembic; `_schema_de_libracore`) y entre tests
# solo trunca (`sesion`) y dropea las tablas de auth (`cliente`). Medido sobre
# PostgreSQL 16 (test_cuentas + test_fce + test_ordenes, 55 tests, una sola corrida):
#
#     limpieza actual (14 TRUNCATE ... RESTART IDENTITY CASCADE)   ~0,11 s/test con fsync=off
#                                                                  ~0,9  s/test con fsync (disco de WSL)
#     restaurar la plantilla `migrada` (DROP DATABASE FORCE + CREATE ... TEMPLATE)
#                                                                  ~0,22 s/test con fsync=off
#                                                                  ~0,12 s/test con fsync
#
# O sea que la plantilla solo gana donde el disco serializa los fsync (WSL), y el
# runner de GitHub no es ese caso (ver reglas/ci.md: el piloto de `fsync = off` no
# midio ganancia). Y la plantilla "armada" con la cadena de auth ahorraria ~0,17 s
# en los tests con `cliente`, a costa de tocar los ~14 fixtures que la crean y de
# cambiar el estado de partida de los tests de arranque. No paga: lo que da el
# tiempo aca es xdist.
#
# 🔴 Se pisan las dos variables de entorno con la URL del worker ANTES de que
# nadie las lea: `Config.desde_entorno()`, `migrations/env.py` y varios tests
# toman `DATABASE_URL` / `LIBRACARGO_LIBRACORE_DATABASE_URL` del entorno. El proceso
# que lanza a xdist tambien importa este archivo y sus workers heredan su entorno;
# `base_por_worker` ya lo maneja (guarda la URL original aparte).
_PG = base_por_worker(
    "libracargo",
    os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/libracargo_test"),
)
URL = _PG.url
os.environ["DATABASE_URL"] = URL

#: La base de **LibraCore** es **la misma** que la del dominio (etapa 3, salida A
#: del diseño `libracargo-modelo-normalizado-diseno`): la suite corre como corre
#: una instancia unida. `usuarios` y `auth_log` son las de `libraauth`, que el
#: motor comparte, igual que en Contalibra.
URL_CORE = URL
os.environ["LIBRACARGO_LIBRACORE_DATABASE_URL"] = URL_CORE


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
    """El `Config` de la suite: la misma URL para el dominio y el core.

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
def _schema_de_libracore(engine):
    """Crea el schema del motor una vez para toda la suite.

    En producción esto lo hace `libracore-migrar upgrade --prefijo libracargo`,
    declarado en el deploy; acá se llama al DDL directo para no arrastrar
    alembic a cada corrida. Es la baseline de esa misma cadena, así que crea lo
    mismo.

    🔑 **Después de `engine`**, que pide la fixture: con una sola base, el
    `DROP SCHEMA public` de `engine` se llevaría puestas las tablas del motor.
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


@pytest.fixture(autouse=True)
def _pdfs_de_comprobantes_en_tmp(tmp_path):
    """Los PDF que se guardan al emitir caen en la carpeta del test, no en la del paquete del motor.

    Desde ADR-034 emitir un comprobante genera y guarda su PDF (`pdf_generator.FACTURAS_PDF_DIR`, que sin
    `DATA_DIR` es una carpeta adentro de `site-packages/libracore`). Sin esto cada corrida ensucia el venv, y un
    PDF viejo de otro test podría ser el que un endpoint encuentre en disco.

    `MonkeyPatch()` propio y no el fixture `monkeypatch`, por lo mismo que `_terminos_ya_aceptados`: un
    `monkeypatch.undo()` en el cuerpo de un test deshace también este parche.
    """
    mp = pytest.MonkeyPatch()
    mp.setattr(pdf_generator, "FACTURAS_PDF_DIR", str(tmp_path / "facturas_pdf"))
    yield
    mp.undo()


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
    # 🔴 La base sale de la cadena de Alembic, no de `create_all`. Con
    # `create_all` las tablas quedaban sin `alembic_version_libracargo`, y una base así,
    # respaldada y restaurada, vuelve a correr la baseline encima de sus propias
    # tablas: `alembic upgrade head` muere con `DuplicateObject` sobre el primer
    # ENUM (`accion_auditoria`). Es la forma que tiene en producción.
    with eng.begin() as con:
        con.execute(text("DROP SCHEMA public CASCADE"))
        con.execute(text("CREATE SCHEMA public"))
    # 🔑 **El schema del motor va ANTES que la cadena de acá**, como en el deploy
    # (`libracore-migrar` y después `alembic upgrade head`): desde la `0016` el
    # comprobante vive en `facturas` del motor y la cadena le pone FK.
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        init_core_schema(conn)
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
        cfg.set_main_option("script_location", str(RAIZ / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        if previo is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previo
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
    # Las del motor que escribe este producto: el comprobante vive en `facturas`, y la pre factura en
    # la bandeja de comprobantes por facturar (ADR-032: su número interno `PF-0001` arranca de cero).
    s.execute(text("TRUNCATE TABLE facturas RESTART IDENTITY CASCADE"))
    s.execute(text("TRUNCATE TABLE comprobantes_pendientes RESTART IDENTITY CASCADE"))
    # Y la cuenta corriente vive en el libro de terceros del motor (`0017`).
    s.execute(text("TRUNCATE TABLE cc_asientos RESTART IDENTITY CASCADE"))
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


# ── Captcha ALTCHA: aprobado para el resto de la suite ──────────────────────
#
# Desde libraauth v0.40.0 el router (`captcha=True` en `app/routers/auth.py`)
# exige la solución de un desafío en el login y en forgot-password. La suite
# postea al login en muchos lugares —cada fixture `cliente`, cada test que arma
# su propia app— y el captcha no es lo que miden: lo prueba libraauth. Acá sólo
# se cablea, y eso lo mide `test_captcha_login.py` con la función real puesta.

#: La función real de libraauth, para que un test pueda volver a ponerla.
CAPTCHA_DE_ORIGINAL = _session_auth._captcha_de


class _CaptchaQueAprueba:
    """Doble del `Captcha` de libraauth: aprueba cualquier payload.

    `emitir()` delega en un `Captcha` real y barato, así `GET /auth/captcha`
    sigue devolviendo un desafío con la forma de siempre.
    """

    def __init__(self):
        self._real = Captcha("clave-de-prueba", costo=1, contador_min=1, contador_rango=5)

    def emitir(self) -> dict:
        return self._real.emitir()

    def verificar(self, payload: str) -> bool:
        return True


_CAPTCHA_DE_PRUEBA = _CaptchaQueAprueba()


@pytest.fixture(autouse=True)
def _captcha_aprobado():
    """Todo login y forgot-password de la suite pasa el captcha.

    Se parchea la función de módulo `libraauth.session_auth._captcha_de` y no
    `app.state.captcha`: el router la resuelve por nombre en cada request, y la
    app se arma en muchos lugares (`crear_app(cfg)`, `crear_app(cfg,
    sembrar_admin=False)`), así que un parche por app se olvidaría en alguno.

    `MonkeyPatch()` propio y no el fixture `monkeypatch`, por la misma razón que
    `_terminos_ya_aceptados`: un `monkeypatch.undo()` en el cuerpo de un test
    desharía también este parche y el siguiente login daría 400.
    """
    mp = pytest.MonkeyPatch()
    mp.setattr(_session_auth, "_captcha_de", lambda request: _CAPTCHA_DE_PRUEBA)
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
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    cfg = config_de_prueba()
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    vaciar_auth(engine)


def vaciar_auth(engine):
    """Deja las tablas de `libraauth` vacías, sin borrarlas.

    🔴 **Vaciar y no `drop_all`**: con una sola base, `usuarios` la referencian
    las FK del motor (`facturas.usuario_id`, `caja_movimientos.usuario_id`...),
    así que no se puede borrar.

    🔴 **`DELETE` y no `TRUNCATE ... CASCADE`.** Desde la `0016` el comprobante vive
    en `facturas`, y `ordenes_carga` y `movimientos_cuenta` la referencian: la
    cascada desde `usuarios` llegaba hasta las tablas del dominio y pedía un lock
    exclusivo sobre ellas. Con la `sesion` del test todavía abierta (se cierra
    después que `cliente`), esperaba para siempre. Las FK del motor hacia
    `usuarios` son `ON DELETE SET NULL`, así que el `DELETE` no se lleva nada más.
    """
    from sqlalchemy import inspect

    existentes = set(inspect(engine).get_table_names())
    tablas = [t for t in reversed(AuthBase.metadata.sorted_tables) if t.name in existentes]
    if tablas:
        with engine.begin() as con:
            for tabla in tablas:
                con.execute(text(f'DELETE FROM "{tabla.name}"'))
                for columna in tabla.primary_key.columns:
                    secuencia = con.execute(text("SELECT pg_get_serial_sequence(:t, :c)"),
                                            {"t": tabla.name, "c": columna.name}).scalar()
                    if secuencia:
                        con.execute(text("SELECT setval(:s, 1, false)"), {"s": secuencia})


def _crear(c, ruta, datos):
    r = c.post(ruta, json=datos)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def datos(cliente):
    """Los maestros mínimos para que una orden exista."""
    return {
        "cliente": _crear(cliente, "/api/terceros",
                          {"razon_social": "Agro Norte", "es_cliente": True,
                           # Un CUIT con dígito verificador válido: emitir por ARCA una
                           # clase A a un receptor sin CUIT no sale (ver `emision_arca`).
                           "cuit": "30-12345678-1"}),
        "otro_cliente": _crear(cliente, "/api/terceros",
                               {"razon_social": "Molino Sur", "es_cliente": True}),
        "origen": _crear(cliente, "/api/localidades", {"nombre": "Suipacha"}),
        "destino": _crear(cliente, "/api/localidades", {"nombre": "Rosario"}),
        "razon": _crear(cliente, "/api/razones-sociales", {"nombre": "Suitrans"}),
        "otra_razon": _crear(cliente, "/api/razones-sociales", {"nombre": "Juan Pérez"}),
    }


# ── Facturar: pre factura → ARCA ────────────────────────────────────────────
#
# Desde ADR-032 no hay forma de registrar un comprobante a mano: se genera una pre factura y se la factura
# por ARCA. Los tests que necesitan «un comprobante» lo hacen así, con ARCA simulada.

#: El CUIT de la razón social que emite en los tests. Ficticio, con dígito verificador válido.
CUIT_EMISOR = "20-12345678-6"


def configurar_arca(cliente, *, cuit, punto_venta=5, ambiente="produccion", empresa=None):
    """Deja la instancia lista para emitir: el par en disco y el CUIT cargado.

    Es **una configuración por instancia**, no una por razón social: así la guarda el motor. Cuál de las
    razones sociales emite lo dice el CUIT.

    ⚠️ **El `PUT` va primero, y no es indistinto.** El upload también crea la fila si no existe, pero con
    el slug por defecto del producto; un `PUT` posterior con otro `empresa` crea una **segunda** fila en vez
    de renombrar la primera. Guardando primero, el upload encuentra la fila activa y escribe en ésa.
    """
    from app.servicios import emision_arca

    r = cliente.put("/api/arca", json={
        "empresa": empresa or emision_arca.EMPRESA_ARCA, "cuit": cuit, "punto_venta": punto_venta,
        "ambiente": ambiente, "alias": "",
    })
    assert r.status_code == 200, r.text
    certificado, clave = par_de_arca()
    for tramo, archivo in (("certificado", certificado), ("clave", clave)):
        r = cliente.post(f"/api/arca/{tramo}", params={"ambiente": ambiente},
                         files={"archivo": (f"c.{tramo}", archivo, "text/plain")})
        assert r.status_code == 200, r.text


def arca_responde(monkeypatch, *, ultimo=0, cae="75123456789012", cae_vto="20261231",
                  falla_numero=None, falla_cae=None):
    """Simula a ARCA: da el número que sigue por (punto de venta, tipo) y autoriza. Devuelve lo que se le pidió.

    A diferencia de un doble que contesta siempre lo mismo, **lleva la cuenta**: cada CAE autorizado
    adelanta el último número de su (punto de venta, tipo), como el WSFE. Dos facturas seguidas no chocan.
    """
    from app.servicios import emision_arca

    pedidos = []
    ultimos: dict[tuple[int, int], int] = {}

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        pedidos.append(("autenticar", ambiente, cert, key))
        return {"token": "TKN", "sign": "SGN"}

    async def ultimo_numero(pv, tipo, cuit, token, sign, ambiente):
        pedidos.append(("ultimo", pv, tipo, cuit))
        if falla_numero:
            raise RuntimeError(falla_numero)
        return ultimos.get((pv, tipo), ultimo)

    async def solicitar_cae(factura, cuit, token, sign, ambiente):
        pedidos.append(("cae", factura))
        if falla_cae:
            raise RuntimeError(falla_cae)
        ultimos[(factura["punto_venta"], factura["tipo"])] = factura["numero"]
        return {"cae": cae, "cae_vto": cae_vto}

    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "ultimo_numero_autorizado", ultimo_numero)
    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", solicitar_cae)
    return pedidos


@pytest.fixture
def emisor(cliente, datos, monkeypatch):
    """`datos["razon"]` lista para emitir por ARCA, con ARCA simulada (punto de venta 1, el último número es 0).

    Devuelve la lista de lo que se le pidió a ARCA. Los tests que usan sólo `facturar()` la piden con la marca
    `con_emisor` (ver `_emisor_listo`) en vez de declararla en cada firma.
    """
    r = cliente.put(f"/api/razones-sociales/{datos['razon']}", json={
        "nombre": "Suitrans", "cuit": CUIT_EMISOR, "punto_venta": 1})
    assert r.status_code == 200, r.text
    configurar_arca(cliente, cuit=CUIT_EMISOR, punto_venta=1)
    return arca_responde(monkeypatch)


@pytest.fixture(autouse=True)
def _emisor_listo(request, _terminos_ya_aceptados, _captcha_aprobado, _secreto_de_sesion):
    """Los tests marcados `con_emisor` arrancan con la razón social lista para emitir.

    Pide **a mano** las autouse que `cliente` necesita (términos, captcha y secreto de sesión): entre
    autouse el orden no es el de definición, y sin esto el login de `cliente` corre antes que ellas.
    """
    # Sólo si el test usa `cliente`: uno que mide el 401 de una app sin sesión no la necesita.
    if request.node.get_closest_marker("con_emisor") and "cliente" in request.fixturenames:
        request.getfixturevalue("emisor")
    yield


def comprobante_de_prueba(sesion, *, cae: str | None = None, comprobante_asociado_id: int | None = None,
                          **campos):
    """Un comprobante ya guardado, creado por la única puerta que tiene (`servicios.comprobantes`).

    Desde la `0016` el comprobante es una fila de `facturas` del motor, así que un test no
    lo arma con el ORM: lo crea el motor y, si se pide, le guarda el CAE. Los importes
    pueden venir como texto, como los devuelve la API.
    """
    from datetime import date as _date
    from decimal import Decimal as _Decimal

    from app.models import Comprobante
    from app.servicios import comprobantes

    for clave in ("neto", "iva", "total"):
        campos[clave] = _Decimal(str(campos[clave]))
    asociado = sesion.get(Comprobante, comprobante_asociado_id) if comprobante_asociado_id else None
    comp = comprobantes.crear(sesion, items=[], asociado=asociado, **campos)
    if cae:
        vto = campos.get("fecha", _date.today())
        comprobantes.guardar_cae(sesion, comp, cae, vto.strftime("%Y%m%d"))
    sesion.commit()
    return comp


def rearmar_en(revision: str) -> None:
    """La base de la suite, rearmada de cero hasta `revision` de esta cadena.

    🔑 **Para mirar una base «de antes» no se baja la cadena**: desde la `0018` (que
    borra las tablas viejas) bajar no tiene vuelta atrás. Se tira el schema, se
    crea el del motor —como en el deploy— y se sube hasta la revisión pedida.
    Después, `rearmar_en("head")` o un `upgrade` la deja como estaba.
    """
    eng = create_engine(URL)
    with eng.begin() as con:
        con.execute(text("DROP SCHEMA public CASCADE"))
        con.execute(text("CREATE SCHEMA public"))
    eng.dispose()
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        init_core_schema(conn)
        conn.commit()
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
        cfg.set_main_option("script_location", str(RAIZ / "migrations"))
        command.upgrade(cfg, revision)
    finally:
        if previo is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previo
