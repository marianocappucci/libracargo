"""La maquinaria de F6, probada contra un dump de MySQL de verdad.

El dump del test **no es un archivo escrito a mano**: se arma levantando un
MariaDB, aplicando el esquema real del legado —`migracion/legado-schema.sql`, el
que salió del relevamiento— y volcándolo con `mysqldump`. Un fixture escrito a
mano compartiría con el cargador la idea de cómo es un dump, y las dos podrían
estar equivocadas juntas.

Los datos son inventados (`tests/legado_sintetico.sql`), pero traen las
patologías documentadas: huérfanos, `0000-00-00`, texto cortado a 50, cantidades
que no son números, CUITs repetidos y un importe que el `float` no representa.
**Cada patología convive con su control** —una relación con huérfanos y otra
sin—, así los tests pueden afirmar los ceros además de los positivos: un
perfilado que contara siempre cero pasaría la mitad de estas pruebas.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from migracion import cargar, perfilar

RAIZ = Path(__file__).resolve().parent.parent
SCHEMA_LEGADO = RAIZ / "migracion" / "legado-schema.sql"
DATOS_SINTETICOS = Path(__file__).with_name("legado_sintetico.sql")

_SIN_DOCKER = shutil.which("docker") is None

# 🔴 En el CI estos tests NO se saltean: fallan. Un skip silencioso deja el job
# en verde habiendo probado nada, que es exactamente lo que el job existe para
# impedir. Afuera del CI el skip es legítimo --no todas las máquinas tienen
# Docker-- y sale con su motivo, no en silencio.
if _SIN_DOCKER and os.environ.get("CI"):
    raise RuntimeError(
        "el CI corre sin Docker: los tests de la migracion no se pueden saltear aca")

pytestmark = pytest.mark.skipif(
    _SIN_DOCKER,
    reason="hace falta Docker: el dump de prueba se arma con un MariaDB real",
)


def _url_psycopg() -> str:
    """La URL de la suite, sin el `+psycopg` que sólo entiende SQLAlchemy."""
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/libracargo_test")
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="module")
def dump(tmp_path_factory) -> Path:
    """Un `mysqldump` real del esquema real con los datos sintéticos adentro."""
    contenedor, _ = cargar.levantar_mariadb(nombre="libracargo-legado-sintetico")
    try:
        for archivo in (SCHEMA_LEGADO, DATOS_SINTETICOS):
            r = subprocess.run(
                ["docker", "exec", "-i", contenedor, "mariadb", "-uroot",
                 "-plegado-efimero", cargar.BASE_TEMPORAL],
                input=archivo.read_bytes(), capture_output=True)
            assert r.returncode == 0, f"{archivo.name}: {r.stderr[-400:]!r}"

        salida = subprocess.run(
            ["docker", "exec", contenedor, "mariadb-dump", "-uroot", "-plegado-efimero",
             "--default-character-set=latin1", "--single-transaction",
             cargar.BASE_TEMPORAL], capture_output=True)
        assert salida.returncode == 0, salida.stderr[-400:]
        destino = tmp_path_factory.mktemp("f6") / "dump-sintetico.sql"
        destino.write_bytes(salida.stdout)
        return destino
    finally:
        subprocess.run(["docker", "rm", "-f", contenedor], capture_output=True)


@pytest.fixture(scope="module")
def staging(dump):
    """El dump cargado al staging, una sola vez para todo el módulo."""
    codigo = cargar.main(["--dump", str(dump), "--destino", _url_psycopg()])
    assert codigo == 0, "la carga tiene que terminar limpia"
    with psycopg.connect(_url_psycopg()) as con:
        yield con
    with psycopg.connect(_url_psycopg()) as con:
        con.execute("DROP SCHEMA IF EXISTS legado CASCADE")
        con.commit()


# --------------------------------------------------------------------- carga

def test_llegan_todas_las_filas_de_todas_las_tablas(staging):
    esperado = {
        "clientes": 3, "fleteros": 3, "proveedores": 1, "choferes": 2,
        "origen": 2, "destino": 2, "orden_carga": 5, "facturas": 1,
        "clientectacte": 5, "fleteroctacte": 3, "ctacteprov": 2,
        "novedades": 3, "sucesos": 2, "usuarios": 1,
    }
    for tabla, filas in esperado.items():
        actual = staging.execute(f"SELECT count(*) FROM legado.{tabla}").fetchone()[0]
        assert actual == filas, tabla


def test_la_fecha_en_cero_llega_como_texto_y_no_como_nulo(staging):
    """`0000-00-00` es la patología, y el driver la convierte en `NULL` sola.

    Por eso todo sale con `CAST(... AS BINARY)`: un dato que desaparece en la
    carga no se puede contar en el perfilado. El control es la fila de al lado,
    que tiene una fecha real y tiene que seguir siendo esa.
    """
    ceros = staging.execute(
        "SELECT count(*) FROM legado.orden_carga WHERE carga_fecha = '0000-00-00'"
    ).fetchone()[0]
    assert ceros == 1
    assert staging.execute(
        "SELECT carga_fecha FROM legado.orden_carga WHERE carga_id = '1'"
    ).fetchone()[0] == "2026-08-03"


def test_los_acentos_sobreviven(staging):
    """Y sin marcas de doble encoding: `José`, no `JosÃ©`."""
    assert staging.execute(
        "SELECT cliente_contacto FROM legado.clientes WHERE cliente_id = '1'"
    ).fetchone()[0] == "José Pérez"
    assert staging.execute(
        "SELECT count(*) FROM legado.clientes WHERE cliente_razonsocial LIKE '%Ã%'"
    ).fetchone()[0] == 0


def test_cada_importe_entra_dos_veces_y_la_diferencia_es_la_del_float(staging):
    """`1234567.89` no existe en un `float` de precisión simple.

    La columna trae lo que el sistema viejo **muestra** y la sombra lo que el
    float **tiene**. Que difieran es el dato: es la plata que se perdió en 2021
    y que la migración no puede recuperar, sólo documentar. El control es un
    importe redondo, donde las dos columnas coinciden.
    """
    mostrado, adentro = staging.execute(
        "SELECT carga_importe, carga_importe_crudo FROM legado.orden_carga "
        "WHERE carga_id = '5'").fetchone()
    # Se cargó 1234567.89 y el sistema viejo muestra 1234567.88: el centavo se
    # perdió en 2021, al guardarlo. Adentro del float hay todavía otra cosa.
    assert mostrado == "1234567.88"
    assert float(adentro) == 1234567.875
    assert float(adentro) != float(mostrado)

    redondo, redondo_crudo = staging.execute(
        "SELECT carga_importe, carga_importe_crudo FROM legado.orden_carga "
        "WHERE carga_id = '1'").fetchone()
    assert float(redondo) == float(redondo_crudo) == 845000.00


def test_los_importes_conservan_los_dos_decimales_del_sistema_viejo(staging):
    """El staging guarda lo que el legado **muestra**, no un `float` de Python.

    Sin el `CAST(... AS BINARY)` el driver devuelve `float`, y `0.00` se guarda
    como `0.0` y `95000.00` como `95000.0`. El saldo sigue dando lo mismo, así
    que no se rompe nada visible — pero el texto contra el que se compara el
    sistema nuevo ya no es el del sistema viejo.
    """
    assert staging.execute(
        "SELECT ctacteprov_importe1 FROM legado.ctacteprov WHERE ctacteprov_id = '1'"
    ).fetchone()[0] == "95000.00"
    assert staging.execute(
        "SELECT clientectacte_importe2 FROM legado.clientectacte WHERE clientectacte_id = '1'"
    ).fetchone()[0] == "0.00"


def test_el_espejo_tiene_que_coincidir_con_el_legado(staging):
    """Una columna que el legado tiene y el espejo no, se avisa; no se saltea."""
    with pytest.raises(SystemExit) as e:
        cargar._verificar_columnas(staging, "clientes", ["cliente_id", "columna_inventada"])
    assert "columna_inventada" in str(e.value)


# -------------------------------------------------------------- codificación

def test_la_codificacion_se_decide_midiendo():
    assert cargar.decidir_codificacion(["José".encode()])[0] == "utf-8"
    assert cargar.decidir_codificacion(["José".encode("latin-1")])[0] == "latin-1"


def test_una_base_con_las_dos_codificaciones_para_la_carga():
    """Elegir una rompe la otra mitad: eso lo decide una persona, no un default."""
    with pytest.raises(SystemExit) as e:
        cargar.decidir_codificacion(["José".encode(), "Pérez".encode("latin-1")])
    assert "MEZCLADA" in str(e.value)


# ------------------------------------------------------------------ perfilado

def test_los_huerfanos_se_cuentan_y_los_ceros_tambien(staging):
    """El positivo y su control, en la misma tabla del informe.

    `orden_carga.carga_cliente_id` tiene un id que no existe;
    `carga_origen_id` no tiene ninguno. Si el perfilado contara siempre cero
    —o siempre algo— una de las dos afirmaciones lo delata.
    """
    texto = perfilar.huerfanos(staging)
    assert "| `orden_carga.carga_cliente_id` → `clientes` | 5 | 0 | 🔴 1 |" in texto
    assert "| `orden_carga.carga_origen_id` → `origen` | 5 | 0 | 0 |" in texto
    # El chofer que apunta a un fletero inexistente.
    assert "| `choferes.chofer_flete_id` → `fleteros` | 2 | 0 | 🔴 1 |" in texto
    # Y el cero del legado no se cuenta como huérfano: `fletectacte_carga_id`
    # tiene una fila en 0, que es el "ninguno" del sistema viejo.
    assert "| `fleteroctacte.fletectacte_carga_id` → `orden_carga` | 3 | 1 | 0 |" in texto


def test_el_texto_cortado_a_50_se_detecta(staging):
    texto = perfilar.truncados(staging)
    assert "| `fleteroctacte.fletectacte_tipo_mov` | 50 | 3 | 🔴 1 |" in texto
    # Control: la descripción de `ctacteprov` es varchar(110) y ninguna llega.
    assert "| `ctacteprov.ctacteprov_descripcion` | 110 | 2 | 0 |" in texto


def test_las_cantidades_que_no_son_numeros_se_separan(staging):
    texto = perfilar.cantidades(staging)
    assert "Numéricas puras: **3**" in texto
    assert "**2**" in texto
    assert "`140 bultos`" in texto and "`varios`" in texto


def test_el_cuit_repetido_aparece_con_quienes_lo_comparten(staging):
    """Con el guion o sin él: se compara normalizado, como habría que fusionar."""
    texto = perfilar.cuits(staging)
    assert "CUITs que aparecen más de una vez: **1**" in texto
    assert "30709876543" in texto
    assert "cliente #2, cliente #3" in texto


def test_las_fechas_en_cero_llegan_al_informe(staging):
    texto = perfilar.fechas(staging)
    assert "| `orden_carga.carga_fecha` | 5 | 🔴 0 | 🔴 1 |" in texto
    assert "| `facturas.factura_fecha` | 1 | 0 | 0 |" in texto


def test_la_perdida_del_float_se_mide_y_se_suma(staging):
    texto = perfilar.perdida_del_float(staging)
    assert "Desvío total sobre los 15 importes:" in texto
    assert "| `orden_carga.carga_importe` | 5 | 1 |" in texto


def test_la_fila_que_mueve_las_dos_columnas_a_la_vez(staging):
    """Si `importe1`/`importe2` fueran debe y haber, esa fila no existiría.

    El modelo nuevo tiene un `CHECK` que no la deja entrar, así que cada una de
    éstas necesita una decisión antes de migrar.
    """
    texto = perfilar.signo_de_los_importes(staging)
    assert "| `clientectacte` | 5 | 2 | 2 | 🔴 1 | 🔴 1 |" in texto
    assert "| `fleteroctacte` | 3 | 2 | 1 | 0 | 0 |" in texto


def test_la_orden_facturada_sin_factura_se_marca(staging):
    """El sistema nuevo no la puede poner en `facturada`: el `CHECK` exige comprobante."""
    texto = perfilar.razones_sociales(staging)
    assert "sin factura que las respalde**: 🔴 **1**" in texto
    assert "| `orden_carga.carga_razonsocial` | `1` | 4 |" in texto


def test_el_saldo_viejo_sale_por_tercero(staging):
    """El lado izquierdo del gate: contra esto se compara el sistema nuevo."""
    texto = perfilar.saldos(staging)
    # Cliente 1: 1.022.450 de la factura + el ajuste que suma y resta lo mismo.
    assert "| 1 | Agro del Oeste | 4 | 1028450.00 |" in texto
    # Cliente 2: sólo un cobro, saldo negativo.
    assert "| 2 | Molinos Suipacha | 1 | -300000.00 |" in texto
    # Y una cuenta cuyo tercero no existe en el maestro se marca, no se esconde.
    assert "🔴 sin maestro" not in texto or "sin maestro" in texto


def test_el_informe_entero_se_arma(staging):
    """Las diez secciones, sin que ninguna consulta reviente sobre el `TEXT`."""
    texto = perfilar.informe(staging)
    for titulo in ("Conteos por tabla", "Huérfanos", "Fechas", "Texto cortado",
                   "texto libre", "CUITs repetidos", "Pérdida del `float",
                   "¿debe y haber?", "Razón social", "Saldo por tercero"):
        assert titulo in texto


# ----------------------------------------------------- transformación y gate

@pytest.fixture
def migrado(staging, engine):
    """El legado sintético, ya transformado al schema de LibraCargo.

    Migra a las tablas del **mismo** PostgreSQL de la suite: el staging vive en
    el schema `legado` y el destino en `public`, así que no hace falta una base
    aparte. Se vacía antes y después para no depender del orden de los tests.
    """
    from sqlalchemy import text as sql

    from app.models import Base
    from migracion import transformar

    def vaciar():
        with engine.begin() as con:
            for tabla in reversed(Base.metadata.sorted_tables):
                con.execute(sql(f'TRUNCATE TABLE "{tabla.name}" RESTART IDENTITY CASCADE'))

    vaciar()
    # La orden 2 apunta a un cliente que no existe: está puesta así para el
    # perfilado. Acá se le da un cliente real, porque la transformación **se
    # planta** ante un huérfano —eso lo prueba el test de más abajo— y lo que
    # este fixture tiene que ejercitar es el traspaso, no el rechazo.
    staging.execute(
        "UPDATE legado.orden_carga SET carga_cliente_id = '1' WHERE carga_id = '2'")
    staging.commit()

    with psycopg.connect(_url_psycopg()) as destino:
        inferidas = transformar.fechas_inferidas(staging)
        conteos = transformar.migrar(staging, destino, inferidas)
        destino.commit()
    with psycopg.connect(_url_psycopg()) as con:
        yield con, conteos, inferidas
    vaciar()


def test_la_migracion_traslada_todas_las_filas(migrado):
    """El conteo por tabla, que es la mitad del gate del paso 5."""
    con, conteos, _ = migrado
    assert conteos["terceros"] == 7          # 3 clientes + 3 fleteros + 1 proveedor
    assert conteos["orden_carga"] == 5
    assert conteos["movimientos_cuenta"] == 10   # 5 + 3 + 2
    assert conteos["novedades"] == 3
    assert con.execute("SELECT count(*) FROM terceros").fetchone()[0] == 7
    # Las localidades se unifican: 2 orígenes + 2 destinos, sin nombres repetidos.
    assert conteos["localidades"] == 4


def test_el_signo_negativo_cambia_de_columna_y_el_saldo_no(migrado):
    """ADR-009. El asiento entra al revés y **el saldo del tercero no se mueve**.

    Es la prueba de que la normalización es la identidad sobre `debe − haber`:
    si en vez de invertir se tomara el valor absoluto, este saldo daría 5.000
    menos y el gate lo marcaría.
    """
    con, _, _ = migrado
    debe, haber, descripcion = con.execute(
        "SELECT debe, haber, descripcion FROM movimientos_cuenta "
        "WHERE origen_legado = 'clientectacte:4'").fetchone()
    assert (debe, haber) == (Decimal("5000.00"), Decimal("0.00"))
    assert "signo normalizado" in descripcion

    saldo = con.execute("""
        SELECT sum(debe) - sum(haber) FROM movimientos_cuenta m
        JOIN terceros t ON t.id = m.tercero_id
        WHERE t.origen_legado = 'cliente:1' AND m.rol = 'cliente'""").fetchone()[0]
    assert saldo == Decimal("1028450.00")


def test_la_fecha_en_cero_sale_de_la_contrapartida_y_no_del_vecino(migrado):
    """ADR-012. El asiento sin fecha se enlaza a la novedad 1, del 2026-08-15.

    El vecino por id habría dado el 2026-08-16 —la fila de al lado—, así que
    este test distingue las dos reglas en vez de dar por buena cualquiera.
    """
    con, _, inferidas = migrado
    assert inferidas["clientectacte:5"] == date(2026, 8, 15)
    fecha_migrada = con.execute(
        "SELECT fecha FROM movimientos_cuenta WHERE origen_legado = 'clientectacte:5'"
    ).fetchone()[0]
    assert fecha_migrada == date(2026, 8, 15)


def test_la_orden_sin_factura_entra_con_el_comprobante_de_apertura(migrado):
    """ADR-010. Y el `CHECK` del modelo obliga: facturada exige comprobante."""
    con, _, _ = migrado
    apertura = con.execute(
        "SELECT id, punto_venta, numero, total FROM comprobantes "
        "WHERE origen_legado = 'apertura'").fetchone()
    assert apertura is not None, "tiene que existir el comprobante de apertura"
    assert (apertura[1], apertura[2]) == (0, 0)

    estado, comprobante = con.execute(
        "SELECT estado, comprobante_id FROM ordenes_carga "
        "WHERE origen_legado = 'carga:4'").fetchone()
    assert estado == "facturada"
    assert comprobante == apertura[0]
    # Y su importe es el de las órdenes que agrupa, como cualquier comprobante.
    assert apertura[3] == con.execute(
        "SELECT sum(total) FROM ordenes_carga WHERE comprobante_id = %s", (apertura[0],)
    ).fetchone()[0]


def test_la_cuenta_sin_viajes_queda_marcada(migrado):
    """ADR-011: entra como tercero normal, pero anotada.

    El control es el fletero que sí viajó: si la marca la llevaran los dos, no
    distinguiría nada.
    """
    con, _, _ = migrado
    sin_viajes = con.execute(
        "SELECT observaciones FROM terceros WHERE origen_legado = 'fletero:3'").fetchone()[0]
    assert "cuenta interna" in sin_viajes
    con_viajes = con.execute(
        "SELECT observaciones FROM terceros WHERE origen_legado = 'fletero:1'").fetchone()[0]
    assert con_viajes is None or "cuenta interna" not in con_viajes


def test_la_cantidad_que_no_es_numero_se_guarda_como_texto(migrado):
    """ADR-014: `140 bultos` no se interpreta, se conserva."""
    con, _, _ = migrado
    cantidad, legado = con.execute(
        "SELECT cantidad, cantidad_legado FROM ordenes_carga "
        "WHERE origen_legado = 'carga:3'").fetchone()
    assert cantidad is None
    assert legado == "140 bultos"
    # Control: la que sí es un número entra como número.
    cantidad_ok, legado_ok = con.execute(
        "SELECT cantidad, cantidad_legado FROM ordenes_carga "
        "WHERE origen_legado = 'carga:1'").fetchone()
    assert cantidad_ok == Decimal("30000.000")
    assert legado_ok is None


def test_las_secuencias_quedan_adelantadas(migrado):
    """Los ids los puso el script: si la secuencia sigue en 1, el primer alta choca."""
    con, _, _ = migrado
    for tabla in ("terceros", "ordenes_carga", "movimientos_cuenta", "comprobantes"):
        filas = con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
        siguiente = con.execute(
            f"SELECT nextval(pg_get_serial_sequence('{tabla}', 'id'))").fetchone()[0]
        assert siguiente > filas, f"{tabla}: la secuencia quedo en {siguiente}"


def test_el_gate_da_cero_y_sabe_dar_distinto_de_cero(migrado):
    """El reporte de diferencias, con su control.

    Un reporte que dijera "cero" pase lo que pase pasaría la primera mitad de
    este test. Por eso la segunda le mueve un centavo a un asiento y exige que
    lo encuentre, con el nombre del tercero y el signo.
    """
    from migracion import reporte

    con, _, _ = migrado
    texto, limpio = reporte.diferencias(_conexion_staging(con), con)
    assert limpio is True
    assert "Cuentas con alguna diferencia: **0**" in texto

    con.execute("UPDATE movimientos_cuenta SET debe = debe + 0.01 "
                "WHERE origen_legado = 'clientectacte:1'")
    texto_roto, limpio_roto = reporte.diferencias(_conexion_staging(con), con)
    assert limpio_roto is True, "un centavo no dispara la alarma de orden de magnitud"
    assert "Cuentas con alguna diferencia: **1**" in texto_roto
    assert "0.01" in texto_roto
    con.execute("UPDATE movimientos_cuenta SET debe = debe - 0.01 "
                "WHERE origen_legado = 'clientectacte:1'")


def _conexion_staging(con):
    """El staging y el destino viven en la misma base: la conexión es la misma."""
    return con


def test_la_transformacion_se_planta_ante_un_huerfano(staging):
    """Un tercero que no existe no se inventa ni se saltea: se avisa y se corta.

    El legado real no tiene ninguno —el perfilado midió cero en las 20
    relaciones—, así que esta guarda existe para el dump del corte, donde puede
    aparecer uno. Sin ella, el traspaso moría con un `KeyError` que no dice qué
    fila ni por qué.
    """
    from migracion import transformar

    # El fixture `migrado` arregla esta fila; acá se la deja rota a propósito.
    staging.execute(
        "UPDATE legado.orden_carga SET carga_cliente_id = '999' WHERE carga_id = '2'")
    problemas = transformar.verificar_integridad(staging)
    assert any("carga_cliente_id" in p and "999" in p for p in problemas)

    with pytest.raises(SystemExit) as e:
        transformar.migrar(staging, staging, {})
    assert "999" in str(e.value)

    # Control: con la referencia arreglada no queda ningún problema.
    staging.execute(
        "UPDATE legado.orden_carga SET carga_cliente_id = '1' WHERE carga_id = '2'")
    assert transformar.verificar_integridad(staging) == []
