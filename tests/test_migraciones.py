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
from sqlalchemy.exc import IntegrityError

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
            # 13 del dominio + alembic_version. Sube cuando entra una tabla nueva,
        # y ese es el punto: el numero se toca a mano al agregarla, asi una
        # tabla que aparece sin querer --por un modelo importado de mas-- se ve.
        # Subio a 14 con la 0006 (`configuracion_arca`) y a 15 con la 0007
        # (`gastos_de_proveedor`), y **bajo a 14** con la 0011: la
        # configuracion de ARCA paso a `arca_config` de LibraCore, que vive
        # en otra base. Que el numero BAJE es el punto de tenerlo a mano:
        # una tabla que se va sin querer se ve igual que una que aparece.
        assert tablas == 14
        eng.dispose()
    finally:
        if original:
            os.environ["DATABASE_URL"] = original


def test_la_cadena_escribe_su_version_en_una_tabla_PROPIA(base_limpia):
    """🔴 Dos cadenas en la misma base no pueden compartir `alembic_version`.

    Desde el 2026-09-02 este repo tiene **dos** bases: el esquema de LibraCore
    se mudó a `libracargo_core`, como en LibraClub, Gestiolibra y MedLibra,
    porque no puede convivir con el del dominio —los dos declaran `usuarios` y
    `auth_log`—. O sea que hoy las dos cadenas ya no comparten base y el nombre
    propio dejó de ser lo único que las separa.

    **Se mantiene igual**, y no es por costumbre: el nombre por defecto es lo
    que haría que un `libracore-migrar` apuntado por error a la base del
    dominio —un `--prefijo` olvidado, y `DATABASE_URL` está ahí mismo— pisara
    la revisión de este repo en vez de fallar. Con un nombre propio, ese error
    deja las dos versiones a la vista en vez de una sola equivocada.

    **No se aserta el valor de `VERSION_TABLE`.** Importar la constante y
    compararla contra el literal que uno escribió en `env.py` se cumple por
    construcción: pasaría igual si `context.configure()` no la recibiera. Lo
    que se mide es la base **después de migrar de verdad** — qué tabla existe y
    cuál no.
    """
    command.upgrade(_alembic(base_limpia), "head")
    eng = create_engine(base_limpia)
    with eng.connect() as con:
        tablas = set(con.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'alembic_version%'"
        )).scalars().all())
    eng.dispose()

    assert "alembic_version_libracargo" in tablas, (
        f"la cadena de este producto no escribió su tabla propia: {sorted(tablas)}")
    # 🔑 La otra mitad, que es la que importa: el nombre genérico tiene que
    # quedar LIBRE para la cadena de LibraCore. Sin este assert el test pasaría
    # con las dos tablas presentes, que es exactamente el estado a medias.
    assert "alembic_version" not in tablas, (
        "quedó también la tabla genérica: la cadena del motor no puede usarla "
        f"sin chocar. Tablas: {sorted(tablas)}")


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


def test_la_0008_agrega_anulado_sobre_una_tabla_CON_filas(base_limpia):
    """🔴 Es el defecto que sólo aparece en producción.

    Alembic autogenera `sa.Column("anulado", sa.Boolean(), nullable=False)` **sin
    default**, y eso falla en una tabla que ya tiene filas: PostgreSQL no sabe
    qué poner en las que están. La instancia del cliente tiene **8.387**
    movimientos de caja migrados.

    Una base vacía —la de los tests de siempre— pasa sin ruido, así que el
    defecto viaja hasta el deploy y ahí no hay dónde esconderlo. Por eso este
    test siembra **antes** de correr la migración.
    """
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "0007")

        eng = create_engine(base_limpia)
        with eng.begin() as con:
            con.execute(text(
                "INSERT INTO movimientos_caja (fecha, tipo, concepto, importe, medio_pago) "
                "VALUES ('2026-08-21', 'ingreso', 'Cobro viejo', 1000, 'efectivo')"))

        command.upgrade(cfg, "head")

        with eng.connect() as con:
            anulados = con.execute(
                text("SELECT anulado FROM movimientos_caja")).scalars().all()
        # Lo que ya existía queda VIGENTE: en el sistema viejo anular era borrar,
        # así que nada de lo migrado estaba anulado.
        assert anulados == [False]
        eng.dispose()
    finally:
        if original:
            os.environ["DATABASE_URL"] = original


def _sembrar_arca(base_limpia, *, con_par: bool):
    """Deja una fila en `configuracion_arca`, con o sin el par cargado."""
    eng = create_engine(base_limpia)
    with eng.begin() as con:
        rs = con.execute(text(
            "INSERT INTO razones_sociales (nombre, condicion_iva, punto_venta, activa) "
            "VALUES ('Suitrans', 'responsable_inscripto', 1, true) RETURNING id"
        )).scalar_one()
        if con_par:
            con.execute(text(
                "INSERT INTO configuracion_arca "
                "(razon_social_id, ambiente, certificado, clave, habilitado) "
                "VALUES (:rs, 'homologacion', :c, :k, false)"),
                {"rs": rs, "c": b"-----BEGIN CERTIFICATE-----",
                 "k": b"-----BEGIN PRIVATE KEY-----"})
        else:
            # Tal cual la creaba el router viejo al abrir la pantalla: la fila
            # existe y las dos columnas del par estan en NULL.
            con.execute(text(
                "INSERT INTO configuracion_arca "
                "(razon_social_id, ambiente, habilitado) "
                "VALUES (:rs, 'homologacion', false)"), {"rs": rs})
    eng.dispose()


def test_la_0011_NO_frena_por_una_fila_vacia(base_limpia):
    """🔴 La primera version contaba filas, y freno el deploy de `dev`.

    El router viejo creaba la fila **al abrir la pantalla** —"se crea al primer
    uso y no en una migracion"— asi que cualquier instancia donde alguien entro
    una vez a Configuracion → ARCA tiene una fila con el par en NULL. Contar
    filas convertia ese estado, que es el normal, en un deploy abortado, con un
    mensaje que hablaba de credenciales que no existian.

    Lo que se protege son las credenciales, asi que eso es lo que se cuenta.
    """
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "0010")
        _sembrar_arca(base_limpia, con_par=False)

        command.upgrade(cfg, "head")  # no tiene que levantar

        eng = create_engine(base_limpia)
        with eng.connect() as con:
            quedan = con.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = 'configuracion_arca'")).scalar_one()
        eng.dispose()
        assert quedan == 0, "la tabla tenia que irse"
    finally:
        if original:
            os.environ["DATABASE_URL"] = original


def test_la_0011_SI_frena_por_una_fila_con_credenciales(base_limpia):
    """La otra mitad, y la que hace que la de arriba signifique algo.

    Sin este par de tests, aflojar la guarda hasta que no frene nunca pasaria
    verde. Lo que se aserta no es que levante: es que **no borro nada** — la
    tabla, la fila y la version siguen donde estaban.
    """
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "0010")
        _sembrar_arca(base_limpia, con_par=True)

        with pytest.raises(RuntimeError, match="CON credenciales"):
            command.upgrade(cfg, "head")

        eng = create_engine(base_limpia)
        with eng.connect() as con:
            filas = con.execute(
                text("SELECT count(*) FROM configuracion_arca")).scalar_one()
            version = con.execute(text(
                "SELECT version_num FROM alembic_version_libracargo")).scalar_one()
        eng.dispose()
        assert filas == 1, "borro la fila igual"
        assert version == "0010", f"la version quedo en {version}"
    finally:
        if original:
            os.environ["DATABASE_URL"] = original


def test_la_0009_convierte_el_gasto_del_legado_sin_mover_el_saldo(base_limpia):
    """🔑 Lo que la migración promete es que **no inserta plata**.

    Crea el documento y le apunta los dos asientos que ya estaban, en vez de
    asentar de nuevo. Se siembra el par que dejaba un gasto viejo —proveedor al
    debe, fletero al haber, con sus marcas de `origen_legado`— y se mide el
    saldo de las dos cuentas antes y después.

    El par que se usa es el **primero del archivo de pares real**, así que si
    ese archivo no viajara en la imagen el test lo diría en vez de pasar en
    verde sobre cero conversiones.
    """
    import json
    from pathlib import Path

    pares = json.loads(
        (Path("migrations/datos/pares_gastos_legado.json")).read_text(encoding="utf-8"))["pares"]
    ctacteprov_id, fleteroctacte_id = next(iter(pares.items()))

    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "0008")

        eng = create_engine(base_limpia)
        with eng.begin() as con:
            con.execute(text(
                "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, "
                "es_fletero, es_proveedor, activo) VALUES "
                "(1, 'Gomeria', 'consumidor_final', false, false, true, true), "
                "(2, 'Fletes', 'consumidor_final', false, true, false, true)"))
            con.execute(text(
                "INSERT INTO movimientos_cuenta "
                "(fecha, tercero_id, rol, concepto, descripcion, debe, haber, origen_legado) "
                "VALUES ('2025-03-04', 1, 'proveedor', 'Remito', '2 cubiertas', "
                "150000, 0, :a), "
                "('2025-03-04', 2, 'fletero', 'Remito', '2 cubiertas', 0, 150000, :b)"),
                {"a": f"ctacteprov:{ctacteprov_id}", "b": f"fleteroctacte:{fleteroctacte_id}"})

        def saldos():
            with eng.connect() as con:
                return dict(con.execute(text(
                    "select tercero_id, coalesce(sum(debe),0) - coalesce(sum(haber),0) "
                    "from movimientos_cuenta group by tercero_id")).all())

        antes = saldos()
        command.upgrade(cfg, "head")
        despues = saldos()

        # Lo que importa: los saldos, idénticos.
        assert antes == despues, f"la conversion movio saldos: {antes} -> {despues}"

        with eng.connect() as con:
            gastos = con.execute(text(
                "select proveedor_id, fletero_id, importe, origen_legado "
                "from gastos_de_proveedor")).all()
            enlazados = con.execute(text(
                "select count(*) from movimientos_cuenta where gasto_id is not null")).scalar_one()

        assert len(gastos) == 1, "tenia que crear exactamente un documento"
        assert gastos[0][0] == 1 and gastos[0][1] == 2
        assert gastos[0][3] == f"ctacteprov:{ctacteprov_id}"
        # Los DOS asientos apuntan al documento: uno solo seria un comprobante
        # que explica una cuenta y deja la otra huerfana.
        assert enlazados == 2
        eng.dispose()
    finally:
        if original:
            os.environ["DATABASE_URL"] = original


def test_la_0009_deja_pasar_al_mismo_tercero_en_las_dos_partes_si_es_del_legado(base_limpia):
    """El `CHECK` se relaja para lo migrado, no para lo nuevo (ADR-015).

    En los datos reales el mismo tercero es proveedor y fletero **43 veces**. La
    restriccion sigue rigiendo para un alta nueva.
    """
    original = os.environ.get("DATABASE_URL")
    try:
        cfg = _alembic(base_limpia)
        command.upgrade(cfg, "head")
        eng = create_engine(base_limpia)
        with eng.begin() as con:
            con.execute(text(
                "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, "
                "es_fletero, es_proveedor, activo) VALUES "
                "(1, 'Mixto', 'consumidor_final', false, true, true, true)"))
            # Del legado: pasa.
            con.execute(text(
                "INSERT INTO gastos_de_proveedor (fecha, proveedor_id, fletero_id, "
                "descripcion, importe, anulado, origen_legado) VALUES "
                "('2025-01-01', 1, 1, 'del legado', 100, false, 'ctacteprov:99999')"))

        # Nuevo: lo rechaza la base. `IntegrityError` y no `Exception`: con
        # `Exception` el test pasaria tambien si el INSERT fallara por un typo
        # en el SQL, o sea por cualquier motivo menos el CHECK.
        with pytest.raises(IntegrityError):
            with eng.begin() as con:
                con.execute(text(
                    "INSERT INTO gastos_de_proveedor (fecha, proveedor_id, fletero_id, "
                    "descripcion, importe, anulado) VALUES "
                    "('2025-01-01', 1, 1, 'nuevo', 100, false)"))
        eng.dispose()
    finally:
        if original:
            os.environ["DATABASE_URL"] = original
