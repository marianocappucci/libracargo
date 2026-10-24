"""Las operaciones `cargo.*`: lo que comparten el nodo, que las arma, y el central, que las aplica (ADR-056).

Con un nodo vinculado, lo que LibraCargo escribe en la oficina sube al central como **operaciones** del outbox de
LibraEdge. Una operación `cargo.<entidad>` lleva la **foto de la fila** tal como quedó en el nodo (no el evento que la
produjo): el central la aplica por upsert, así que el reenvío del outbox (al menos una vez) no duplica nada y una foto
más nueva reemplaza a la anterior. Es lo que hace posible subir todo sin reescribir en el central la lógica de cada
hecho (una orden que se factura, una anulación, un gasto de dos patas): el nodo ya la corrió, y lo que sube es su
resultado.

Este módulo es el vocabulario común: los tipos, las entidades con sus referencias y la conversión a JSON. Quién arma las
operaciones es `servicios/subida.py` (nodo) y quién las aplica es `servicios/aplicadores.py` (central).

## Los ids

- Lo que **nace en el nodo** (órdenes, gastos, adjuntos, cartas de porte) toma un **id provisorio negativo**
  (`libraedge.mapeo.siguiente_id_provisorio`): no se puede cruzar nunca con uno del central, que es siempre positivo.
  El central le asigna el suyo al aplicar el alta y anota el mapeo `(nodo, tabla, id_nodo) -> id_central`
  (`libraedge_mapeo`); lo que llega después con una referencia a ese id negativo se traduce con él.
- Un id **positivo** que viaja es de una fila que el central ya tenía al vincular (la carga inicial la bajó con su id):
  se aplica por ese id.
- Lo que escribe el **motor** con ids propios (la caja, los asientos, las facturas) no usa ese mecanismo: la caja lleva
  `origen`/`origen_id` (libracore ADR-076), los asientos `origen_nodo`/`origen_nodo_id` (`0034`) y la factura se
  reconoce por su número ante ARCA (libracore ADR-074). Ver `aplicadores.py`.
"""

from __future__ import annotations

import base64
import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

#: La versión de la forma de todos los payloads de este módulo. Si cambia, sube: el central rechaza lo que no entiende
#: (va a revisión manual, no se pierde).
VERSION = 1

TIPO_TERCERO = "cargo.tercero"
TIPO_ORDEN = "cargo.orden"
TIPO_GASTO = "cargo.gasto"
TIPO_ADJUNTO = "cargo.adjunto"
TIPO_CARTA_PORTE = "cargo.carta_porte"
TIPO_CARTA_PORTE_PDF = "cargo.carta_porte_pdf"
TIPO_COMPROBANTE = "cargo.comprobante"
TIPO_ASIENTO = "cargo.asiento"


@dataclass(frozen=True)
class Entidad:
    """Una cosa que el nodo sube como foto de fila.

    - `nombre`: cómo la llama `tocar` y el `aggregate_type` de la operación.
    - `tabla` y `pk`: dónde vive y su clave (`id` salvo en las que cuelgan de otra).
    - `refs`: `{columna: tabla}`: las columnas que guardan un id de otra tabla **de este producto**. Un id negativo se
      traduce con el mapeo del central; uno positivo (o `None`) pasa tal cual.
    - `pk_ref`: si la clave es a la vez una referencia (`cartas_porte_pdf.carta_porte_id`), la tabla a la que apunta.
    - `binarias`: columnas `bytea`, que viajan en base64.
    - `naturales`: columnas que identifican a la fila aunque tenga otro id (el CTG de una carta de porte): si el central
      ya tiene una con el mismo valor, la adopta en vez de duplicarla.
    - `prioridad`: el orden en que se encolan las que cambiaron en una misma transacción. Una operación sólo puede
      referirse a lo que llegó antes: los terceros, los comprobantes (de los que cuelgan las órdenes), las órdenes…
    """

    nombre: str
    tipo: str
    tabla: str
    prioridad: int
    pk: str = "id"
    refs: Mapping[str, str] = field(default_factory=dict)
    pk_ref: str | None = None
    binarias: tuple[str, ...] = ()
    naturales: tuple[str, ...] = ()


#: Los terceros (clientes, fleteros, proveedores) que se dan de alta en el nodo (libraedge ADR-021): la única tabla de
#: referencia donde el nodo crea filas. El central deduplica por CUIT.
TERCERO = Entidad("tercero", TIPO_TERCERO, "terceros", prioridad=0)
ORDEN = Entidad("orden", TIPO_ORDEN, "ordenes_carga", prioridad=20,
                refs={"cliente_id": "terceros", "fletero_id": "terceros"})
GASTO = Entidad("gasto", TIPO_GASTO, "gastos_de_proveedor", prioridad=30,
                refs={"proveedor_id": "terceros", "fletero_id": "terceros"})
ADJUNTO = Entidad("adjunto", TIPO_ADJUNTO, "ordenes_adjuntos", prioridad=40,
                  refs={"orden_id": "ordenes_carga"}, binarias=("contenido",))
CARTA_PORTE = Entidad("carta_porte", TIPO_CARTA_PORTE, "cartas_porte", prioridad=50,
                      refs={"orden_carga_id": "ordenes_carga"}, naturales=("nro_ctg",))
CARTA_PORTE_PDF = Entidad("carta_porte_pdf", TIPO_CARTA_PORTE_PDF, "cartas_porte_pdf", prioridad=60,
                          pk="carta_porte_id", pk_ref="cartas_porte", binarias=("contenido",))

#: Las que son una foto de fila común. El comprobante (`facturas` más `comprobantes_cargo`) y el asiento (el libro del
#: motor más su fila propia) tienen su propio armado y su propio aplicador.
ENTIDADES: dict[str, Entidad] = {e.nombre: e for e in (TERCERO, ORDEN, GASTO, ADJUNTO, CARTA_PORTE, CARTA_PORTE_PDF)}

#: Las que no son foto de fila común, con su prioridad. El comprobante va antes que las órdenes (que lo referencian) y
#: el asiento al final (referencia órdenes, gastos, comprobantes y movimientos de caja).
PRIORIDAD_COMPROBANTE = 10
PRIORIDAD_ASIENTO = 90

#: Los nombres de lo que se puede `tocar` y el tipo de operación de cada uno.
TIPOS: dict[str, str] = {**{n: e.tipo for n, e in ENTIDADES.items()},
                         "comprobante": TIPO_COMPROBANTE, "asiento": TIPO_ASIENTO}


def prioridad_de(nombre: str) -> int:
    if nombre == "comprobante":
        return PRIORIDAD_COMPROBANTE
    if nombre == "asiento":
        return PRIORIDAD_ASIENTO
    return ENTIDADES[nombre].prioridad


# ── JSON ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def a_json(valor: Any) -> Any:
    """Un valor de una fila como JSON estricto. Los importes viajan como texto (`Decimal`, sin pasar por `float`), las
    fechas en ISO y los binarios en base64: el central los recibe como texto y la base los convierte al tipo de la
    columna."""
    if valor is None or isinstance(valor, (bool, int, str)):
        return valor
    if isinstance(valor, float):
        return repr(valor)
    if isinstance(valor, Decimal):
        return format(valor, "f")
    if isinstance(valor, (dt.datetime, dt.date, dt.time)):
        return valor.isoformat()
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(valor)).decode("ascii")
    if isinstance(valor, Mapping):
        return {str(k): a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [a_json(v) for v in valor]
    raise TypeError(f"no sé pasar a JSON un {type(valor).__name__}")


def de_base64(texto: str | None) -> bytes | None:
    return None if texto is None else base64.b64decode(texto)


def foto_de_fila(fila: Mapping, entidad: Entidad) -> dict:
    """`{columna: valor JSON}` de la fila de la entidad, sin su clave. Las binarias van en base64."""
    return {columna: a_json(valor) for columna, valor in dict(fila).items() if columna != entidad.pk}


def seleccion_exacta(conn, tabla: str) -> str:
    """La lista de columnas de un `SELECT` que lee `tabla` **sin pasar los importes por `float`**.

    El adaptador de la familia devuelve las columnas `NUMERIC` como `float`; para una foto que viaja al central (o una
    carga que baja al nodo) eso cambia el texto de un importe y, con tantos dígitos, lo puede redondear. Cada
    `numeric` se pide `::text` y llega tal cual lo guarda la base (`1000.00`)."""
    filas = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ? ORDER BY ordinal_position", (tabla,)).fetchall()
    if not filas:
        raise ValueError(f"no existe la tabla {tabla!r}")
    return ", ".join(f'"{c}"::text AS "{c}"' if tipo == "numeric" else f'"{c}"' for c, tipo in filas)


def es_provisorio(id_: Any) -> bool:
    """Si `id_` es un id provisorio del nodo (un entero negativo)."""
    return isinstance(id_, int) and not isinstance(id_, bool) and id_ < 0
