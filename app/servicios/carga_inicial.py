"""La carga inicial del nodo: al vincular, trae todo lo que el central ya tenía; desde ahí manda el nodo (ADR-056).

Con un nodo vinculado la oficina **opera** y la web **consulta**: órdenes, caja, asientos, facturas y cartas de porte se
escriben sólo en el nodo y no se espejan (libraedge ADR-002). Pero un nodo recién vinculado arranca con esas tablas
vacías, y la oficina tiene que poder **consultar todo** sin internet: las ≈4.300 órdenes, la caja, las cuentas
corrientes, los comprobantes. Eso es lo que baja esta carga, **una sola vez** (`LIBRAEDGE_CARGA_INICIAL`, libraedge
ADR-023), con los **ids del central**: el nodo conserva las filas tal cual y desde ahí sólo agrega las suyas, con ids
que no se cruzan (negativos para lo que se reescribe en el central; los de las secuencias, adelantados, para lo que el
motor numera). Es la misma idea que la carga de las existencias de LibraCommerce.

## Cómo viaja, y por qué en una sola respuesta

`GET /sync/v1/carga-inicial` devuelve **un** objeto JSON (libraedge no pagina: `traer()` no recibe cursor, y el
transporte tiene 30 s de plazo). Se midió con el volumen de Suitrans (≈4.300 órdenes, 22.600 asientos, 8.400
movimientos de caja, 2.800 gastos: `tests/test_carga_inicial.py::test_el_volumen_de_suitrans_entra_en_una_respuesta`):

- **En columnas** (`{"columnas": [...], "filas": [[...], ...]}`) y no una lista de objetos: los nombres de las columnas
  van una vez por tabla y no una por fila.
- **Comprimida** (`zlib` y base64 dentro del JSON): el texto repetido de las descripciones comprime unas 8 a 10 veces.

Resultado: unos pocos MB y menos de un segundo de armado, un orden de magnitud por debajo del plazo. Con 10 veces más
datos sigue entrando; si algún día no entrara, lo que hace falta es un cursor en `traer()` (anotado para libraedge), no
cambiar esto.

## Lo que se baja y lo que no

Baja lo de **autoridad del nodo** que ya existía: `facturas` y `comprobantes_cargo`, `ordenes_carga` y sus adjuntos, los
gastos, la caja (`caja_movimientos` y `movimientos_caja_cargo`), los asientos (`cc_asientos` y
`movimientos_cuenta_cargo`), las cartas de porte con su PDF, la plantilla de cada titular y el comprobante de apertura
del legado. **No** baja el log de auditoría (el nodo empieza el suyo; el historial queda en el central) ni nada de lo
que ya espeja (terceros, localidades, usuarios...). Las columnas que dicen de qué nodo vino una fila (`origen`,
`origen_id`, `origen_nodo`) **no se copian**: en el nodo todo lo que bajó es «del central» y la fila propia del nodo
todavía no subió.

## Lo que tiene que cumplir

- **Una sola transacción con la marca** (libraedge ADR-023): o baja todo o no baja nada. Si falta algo que el espejo
  todavía no trajo (un tercero, un usuario), `hecha: False` y se reintenta en el ciclo siguiente.
- **Sólo en un nodo recién vinculado.** Si alguna de las tablas ya tiene filas, se niega: pisar lo que el nodo ya cargó
  sería perder datos. (`libraedge-nodo carga-inicial --forzar` quita la marca; vaciar las tablas es de soporte.)
- **Las secuencias, adelantadas.** Después de cargar con ids explícitos, la secuencia de cada tabla sigue al id más alto
  (y al `origen_id` más alto de este nodo, si el central ya había recibido de él): lo que el nodo numere después no
  choca con lo que bajó ni con lo que el central ya tenía de un nodo anterior.
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import psycopg

from app.servicios.cargo_ops import a_json, de_base64, seleccion_exacta

_log = logging.getLogger(__name__)

#: La versión de la forma de lo que baja. Si cambia, sube: el nodo rechaza lo que no entiende.
VERSION = 1
FORMATO = "zlib+base64"


@dataclass(frozen=True)
class Tabla:
    """Una tabla de autoridad del nodo que baja con la carga.

    `pk` es la columna clave (la que ordena y la que adelanta la secuencia, si tiene una); `sin` las columnas que no se
    copian; `binarias` las `bytea` (viajan en base64); `secuencia` si su clave sale de una secuencia de la base."""

    nombre: str
    pk: str = "id"
    sin: tuple[str, ...] = ()
    binarias: tuple[str, ...] = ()
    secuencia: bool = True
    #: Otras columnas con el id del nodo que también obligan a adelantar la secuencia (el origen de lo que subió).
    origen_id: str | None = None


#: En el orden en que se pueden insertar (las claves foráneas apuntan hacia arriba).
TABLAS: tuple[Tabla, ...] = (
    Tabla("comprobante_de_apertura"),
    Tabla("facturas"),
    Tabla("comprobantes_cargo", pk="factura_id", secuencia=False),
    Tabla("ordenes_carga"),
    Tabla("ordenes_adjuntos", binarias=("contenido",)),
    Tabla("gastos_de_proveedor"),
    Tabla("caja_movimientos", sin=("origen", "origen_id"), origen_id="origen_id"),
    Tabla("movimientos_caja_cargo", pk="movimiento_id", secuencia=False),
    Tabla("cc_asientos"),
    Tabla("movimientos_cuenta_cargo", pk="asiento_id", sin=("origen_nodo", "origen_nodo_id"), secuencia=False),
    Tabla("cartas_porte"),
    Tabla("cartas_porte_pdf", pk="carta_porte_id", binarias=("contenido",), secuencia=False),
    Tabla("plantillas_cpe", pk="cuit_titular", secuencia=False),
)


class CargaInicialInvalida(ValueError):
    """Lo que bajó no se entiende (otra versión, otro formato). Es un error: se reintenta cuando se actualice."""


# ── En el central ───────────────────────────────────────────────────────────────────────────────────────────────


def _filas(conn, tabla: Tabla) -> tuple[list[str], list[list]]:
    cursor = conn.execute(f"SELECT {seleccion_exacta(conn, tabla.nombre)} FROM {tabla.nombre} ORDER BY {tabla.pk}")
    columnas = [d[0] for d in cursor.description if d[0] not in tabla.sin]
    posiciones = [i for i, d in enumerate(cursor.description) if d[0] not in tabla.sin]
    filas = [[a_json(fila[i]) for i in posiciones] for fila in cursor.fetchall()]
    return columnas, filas


def _hasta_donde_numera(conn, tabla: Tabla) -> int:
    """El id más alto que el central ya vio en `tabla`: el mayor de su clave y, si la tabla lo tiene, del `origen_id`
    de lo que le subió un nodo (un nodo anterior numeró con ids propios que no se copian). Lo que el nodo numere
    después tiene que estar por encima."""
    candidatos = [f"COALESCE(MAX({tabla.pk}), 0)"]
    if tabla.origen_id:
        candidatos.append(f"COALESCE(MAX({tabla.origen_id}), 0)")
    return int(conn.execute(f"SELECT GREATEST({', '.join(candidatos)}) FROM {tabla.nombre}").fetchone()[0])


def armar(conn) -> dict:
    """Lo que se baja, sin comprimir: `{"version", "tablas": {nombre: {"columnas", "filas"}}, "secuencias": {...}}`."""
    tablas, secuencias = {}, {}
    for tabla in TABLAS:
        columnas, filas = _filas(conn, tabla)
        tablas[tabla.nombre] = {"columnas": columnas, "filas": filas}
        if tabla.secuencia:
            secuencias[tabla.nombre] = _hasta_donde_numera(conn, tabla)
    return {"version": VERSION, "tablas": tablas, "secuencias": secuencias}


def comprimir(contenido: Mapping) -> dict:
    """El cuerpo que viaja: comprimido, con los conteos a la vista (para el log y para el soporte)."""
    crudo = json.dumps(contenido, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "version": VERSION, "formato": FORMATO,
        "conteos": {nombre: len(t["filas"]) for nombre, t in contenido["tablas"].items()},
        "datos": base64.b64encode(zlib.compress(crudo, 6)).decode("ascii"),
    }


def carga_inicial_del_central(conexion, node_id: str, branch_id) -> dict:
    """`carga_inicial=` de `create_sync_router`: todo lo de autoridad del nodo que el central ya tiene, para el nodo
    `node_id`. La oficina es la única «sucursal» (`offline.SUCURSAL_UNICA`): no hay nada que filtrar por ella."""
    cuerpo = comprimir(armar(conexion))
    _log.info("Carga inicial para el nodo %s: %s filas, %s bytes", node_id, sum(cuerpo["conteos"].values()),
              len(cuerpo["datos"]))
    return cuerpo


# ── En el nodo ──────────────────────────────────────────────────────────────────────────────────────────────────


def descomprimir(cuerpo: Mapping) -> dict:
    """Lo contrario de `comprimir`. Levanta `CargaInicialInvalida` si no es una carga que este nodo entienda."""
    if cuerpo.get("version") != VERSION or cuerpo.get("formato") != FORMATO:
        raise CargaInicialInvalida(
            f"la carga inicial es de otra versión ({cuerpo.get('version')!r}, {cuerpo.get('formato')!r}) y este nodo "
            f"entiende la {VERSION} ({FORMATO}): actualizar el nodo")
    contenido = json.loads(zlib.decompress(base64.b64decode(cuerpo["datos"])).decode("utf-8"))
    if contenido.get("version") != VERSION:
        raise CargaInicialInvalida("el contenido de la carga inicial es de otra versión: actualizar el nodo")
    return contenido


def _tipos_de(conn, tabla: str) -> dict[str, str]:
    filas = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?", (tabla,)).fetchall()
    return {f[0]: f[1] for f in filas}


def _insertar(conn, tabla: Tabla, columnas: list[str], filas: list[list]) -> None:
    tipos = _tipos_de(conn, tabla.nombre)
    desconocidas = [c for c in columnas if c not in tipos]
    if desconocidas:
        raise CargaInicialInvalida(f"{tabla.nombre} no tiene las columnas {desconocidas}: el nodo está en otro esquema")
    marcas = ", ".join("CAST(? AS JSONB)" if tipos[c] == "jsonb" else "?" for c in columnas)
    sql = f"INSERT INTO {tabla.nombre} ({', '.join(columnas)}) VALUES ({marcas})"

    def valor(columna: str, dato):
        if columna in tabla.binarias:
            return de_base64(dato)
        if tipos[columna] == "jsonb" and dato is not None:
            return json.dumps(dato, ensure_ascii=False)
        return dato

    conn.executemany(sql, [tuple(valor(c, v) for c, v in zip(columnas, fila, strict=True)) for fila in filas])


def _adelantar_secuencia(conn, tabla: Tabla, hasta: int) -> None:
    """Que la secuencia de la tabla siga al id más alto que vio el central (`hasta`) y al que bajó, sin retroceder."""
    local = conn.execute(f"SELECT COALESCE(MAX({tabla.pk}), 0) FROM {tabla.nombre}").fetchone()[0]
    maximo = max(int(hasta or 0), int(local))
    secuencia = conn.execute("SELECT pg_get_serial_sequence(?, ?)", (tabla.nombre, tabla.pk)).fetchone()[0]
    if secuencia is None or not maximo:
        return
    conn.execute("SELECT setval(?, GREATEST(?, (SELECT last_value FROM " + secuencia + ")), true)", (secuencia, maximo))


def _con_filas(conn) -> list[str]:
    return [t.nombre for t in TABLAS if conn.execute(f"SELECT 1 FROM {t.nombre} LIMIT 1").fetchone() is not None]


def aplicar(conn, contenido: Mapping) -> dict:
    """Escribe en la base del nodo lo que bajó, en el orden de las claves foráneas, y adelanta las secuencias. No
    confirma: la marca y esto viven en la misma transacción (libraedge ADR-023).

    Devuelve `{"hecha": True, "conteos": {...}}`, o `{"hecha": False, "motivo": ...}` si todavía no se puede."""
    ocupadas = _con_filas(conn)
    if ocupadas:
        return {"hecha": False, "motivo": (
            f"las tablas {ocupadas} ya tienen filas: la carga inicial es para un nodo recién vinculado (si el nodo ya "
            "cargó algo, hay que vaciarlas antes; ver `libraedge-nodo carga-inicial --forzar`)")}
    tablas = contenido["tablas"]
    for tabla in TABLAS:
        datos = tablas.get(tabla.nombre)
        if not datos or not datos["filas"]:
            continue
        try:
            _insertar(conn, tabla, datos["columnas"], datos["filas"])
        except (sqlite3.IntegrityError, psycopg.errors.IntegrityError) as e:
            # Lo más probable: el espejo todavía no trajo lo que la fila referencia (un tercero, un usuario, la
            # configuración de ARCA). Se espera al ciclo siguiente en vez de fallar.
            conn.rollback()
            return {"hecha": False, "motivo": f"el espejo todavía no trajo lo que {tabla.nombre} referencia: {e}"}
    secuencias = contenido.get("secuencias") or {}
    for tabla in TABLAS:
        if tabla.secuencia:
            _adelantar_secuencia(conn, tabla, secuencias.get(tabla.nombre, 0))
    return {"hecha": True, "conteos": {n: len(d["filas"]) for n, d in tablas.items()}}


def aplicar_carga_inicial(conexion, traer: Callable[[], dict]) -> dict:
    """`LIBRAEDGE_CARGA_INICIAL=app.servicios.carga_inicial:aplicar_carga_inicial` (libraedge ADR-023): el nodo trae la
    carga del central (`traer()`) y la aplica en la transacción del worker, que la confirma junto con la marca."""
    return aplicar(conexion, descomprimir(traer()))


__all__ = ["TABLAS", "aplicar", "aplicar_carga_inicial", "armar", "carga_inicial_del_central", "comprimir",
           "descomprimir"]
