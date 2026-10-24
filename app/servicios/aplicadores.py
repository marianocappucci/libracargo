"""El central aplica lo que sube el nodo de la oficina (ADR-056).

Es la mitad del central de las operaciones `cargo.*` (`cargo_ops.py` es el vocabulario y `subida.py` la mitad del nodo),
más las de la caja y la cola que son del motor. Se registran en el `Despachador` de `routers/sincronizacion_offline.py`.

## Lo que tiene que cumplir todo aplicador

- **Idempotente.** El outbox entrega al menos una vez y la revisión manual puede reintentar: aplicar dos veces la misma
  operación deja el mismo estado. Las fotos de fila se aplican por upsert; la caja, los asientos y las facturas se
  reconocen por su origen o por su número ante ARCA.
- **En la transacción de `conn`, sin confirmar.** Si algo falla no queda nada de la operación. Lo que falta o choca se
  dice con un `ValueError` (la jerarquía `SinMapeo`, `FacturaEnConflicto`, `CajaDelNodoError` lo es): el receptor de
  LibraEdge manda esa operación a revisión manual y la cola sigue; cualquier otra excepción es un fallo de transporte y
  corta la tanda.
- **Los ids definitivos son del central.** Una fila que nace en el nodo con un id negativo se inserta con el siguiente
  id del central y se anota el mapeo `(nodo, tabla, id_nodo) -> id_central` (`libraedge_mapeo`); las operaciones
  siguientes que la referencian se traducen con él (`traducir_id`: sin mapeo, `SinMapeo`).

## Lo que se aplica y cómo se reconoce

| Operación | Reconocimiento en el central |
|---|---|
| `caja.movimiento`, `caja.movimiento_anulado` | `caja_movimientos.origen`/`origen_id` (libracore ADR-076 y ADR-080) |
| `cargo.asiento` | `movimientos_cuenta_cargo.origen_nodo`/`origen_nodo_id` (`0034`) |
| `cargo.comprobante` | el número ante ARCA: `(emisor, ambiente, tipo, punto de venta, número)` |
| `cargo.orden`, `.gasto`, `.adjunto`, `.carta_porte`, `.carta_porte_pdf`, `.tercero` | el mapeo del id negativo |
| `cola.pedido` | `(producto, instancia, tipo, origen)` y su `revision` (libracore ADR-079) |

Un id **positivo** en una referencia es de una fila que el central ya tenía al vincular el nodo (la carga inicial la
bajó con su id): pasa tal cual. Los ids que el nodo genera por su cuenta empiezan después del último que bajó
(`servicios/carga_inicial.py` adelanta las secuencias), así que un id positivo del nodo que el central no conoce por
origen es, sin ambigüedad, uno de los que ya tenía.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from libracore.caja_del_nodo import aplicar_anulacion_del_nodo, aplicar_movimiento_del_nodo
from libracore.cola_arca import aplicar_pedido_del_nodo
from libracore.cuit import solo_digitos
from libracore.db import facturas as db_facturas
from libracore.db import libro_de_terceros as libro
from libracore.db.caja import get_movimiento_de_origen
from libracore.facturas_del_nodo import aplicar_factura_del_nodo
from libraedge.mapeo import anotar_mapeo, es_provisorio, traducir_id

from app.servicios import cargo_ops
from app.servicios.cargo_ops import ENTIDADES, Entidad, de_base64

_log = logging.getLogger(__name__)

_IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]*$")


class OperacionInvalida(ValueError):
    """Una operación `cargo.*` que el central no puede aplicar. Es un `ValueError` a propósito: el receptor la manda a
    revisión manual (`libraedge-central revision`) y la cola del nodo sigue."""


class NoSincronizado(OperacionInvalida):
    """La operación se refiere a algo del nodo que el central todavía no tiene (su operación no llegó o está en
    revisión). Al resolver aquella, se reintenta ésta."""


def _version(payload: Mapping, que: str) -> None:
    if payload.get("version") != cargo_ops.VERSION:
        raise OperacionInvalida(
            f"versión {payload.get('version')!r} de {que} desconocida (se entiende {cargo_ops.VERSION})")


# ── Tablas y columnas ─────────────────────────────────────────────────────────────────────────────────────────────────


def _columnas(conn, tabla: str) -> set[str]:
    """Las columnas que tiene `tabla` en esta base. El payload trae las del nodo; sólo se escriben las que el central
    también tiene (los dos corren el mismo esquema: LibraEdge frena la subida si no, pero lo que se interpola en el SQL
    nunca sale del payload sin pasar por acá)."""
    filas = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
        (tabla,)).fetchall()
    return {f[0] for f in filas}


def _escribibles(conn, tabla: str, valores: Mapping[str, Any]) -> dict[str, Any]:
    columnas = _columnas(conn, tabla)
    return {c: v for c, v in valores.items() if c in columnas and _IDENTIFICADOR.match(c)}


def _insertar(conn, tabla: str, valores: Mapping[str, Any]) -> Any:
    """`INSERT` de `valores` y el `lastrowid` (si la tabla tiene `id`)."""
    campos = _escribibles(conn, tabla, valores)
    nombres = ", ".join(campos)
    marcas = ", ".join("?" for _ in campos)
    return conn.execute(f"INSERT INTO {tabla} ({nombres}) VALUES ({marcas})", tuple(campos.values())).lastrowid


def _actualizar(conn, tabla: str, pk: str, id_: Any, valores: Mapping[str, Any]) -> None:
    campos = _escribibles(conn, tabla, valores)
    campos.pop(pk, None)
    if not campos:
        return
    asignaciones = ", ".join(f"{c} = ?" for c in campos)
    conn.execute(f"UPDATE {tabla} SET {asignaciones} WHERE {pk} = ?", (*campos.values(), id_))


def _existe(conn, tabla: str, pk: str, id_: Any) -> bool:
    return conn.execute(f"SELECT 1 FROM {tabla} WHERE {pk} = ?", (id_,)).fetchone() is not None


# ── Resolver ids ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _traducir(conn, node_id: str, tabla: str, id_nodo: Any) -> Any:
    """El id del central de un id del nodo en una tabla de este producto: `None` pasa, un positivo pasa (es del
    central) y un negativo se busca en el mapeo (`SinMapeo`, un `ValueError`, si no está)."""
    return traducir_id(conn, node_id, tabla, id_nodo)


def _factura_central(conn, clave: Mapping) -> int:
    """El id de `facturas` del central de un comprobante, por su número ante ARCA."""
    factura = db_facturas.get_factura_por_tipo_pv_nro(
        int(clave["tipo"]), int(clave["punto_venta"]), int(clave["numero"]),
        emisor_id=clave.get("emisor_id"), ambiente=clave.get("ambiente"), conn=conn)
    if factura is None:
        raise NoSincronizado(
            f"el comprobante {int(clave['punto_venta']):04d}-{int(clave['numero']):08d} (tipo {clave['tipo']}) "
            "no está en el central: falta aplicar su cargo.comprobante")
    return factura["id"]


def _asiento_central(conn, node_id: str, id_nodo: Any) -> int | None:
    """El asiento del central que corresponde al `id_nodo`, o `None` si no está.

    Primero por el origen (los que el central aplicó desde este nodo); si no, un asiento que el central ya tenía al
    vincular, que el nodo conserva con el mismo id (`origen_nodo` en `NULL`)."""
    fila = conn.execute(
        "SELECT asiento_id FROM movimientos_cuenta_cargo WHERE origen_nodo = ? AND origen_nodo_id = ?",
        (node_id, id_nodo)).fetchone()
    if fila is not None:
        return fila[0]
    fila = conn.execute(
        "SELECT a.id FROM cc_asientos a LEFT JOIN movimientos_cuenta_cargo c ON c.asiento_id = a.id "
        "WHERE a.id = ? AND c.origen_nodo IS NULL", (id_nodo,)).fetchone()
    return None if fila is None else fila[0]


def _movimiento_de_caja_central(conn, node_id: str, id_nodo: Any) -> int | None:
    """El movimiento de caja del central de un id del nodo: por `origen`/`origen_id`, o uno que el central ya tenía."""
    if id_nodo is None:
        return None
    propio = get_movimiento_de_origen(node_id, id_nodo, conn=conn)
    if propio is not None:
        return propio["id"]
    fila = conn.execute("SELECT id FROM caja_movimientos WHERE id = ? AND origen IS NULL", (id_nodo,)).fetchone()
    if fila is None:
        raise NoSincronizado(
            f"el movimiento de caja {id_nodo} del nodo {node_id} no está en el central: falta aplicar su "
            "caja.movimiento")
    return fila[0]


# ── La caja ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def _crear_la_hija(node_id: str):
    """El gancho del central (libracore ADR-080): la fila propia del movimiento, con el mismo id que la del motor y lo
    que el nodo llevó en `extra`: el tercero (traducido si es uno que se dio de alta en el nodo), la descripción y
    el recibo."""

    def crear(conn, mov_id: int, datos: dict) -> None:
        extra = datos.get("extra") or {}
        conn.execute(
            "INSERT INTO movimientos_caja_cargo (movimiento_id, descripcion, tercero_id, recibo) VALUES (?, ?, ?, ?)",
            (mov_id, extra.get("descripcion"), _traducir(conn, node_id, "terceros", extra.get("tercero_id")),
             extra.get("recibo")))

    return crear


def aplicar_caja_movimiento(conn, operacion) -> None:
    aplicar_movimiento_del_nodo(conn, operacion.node_id, operacion.payload,
    al_aplicar=_crear_la_hija(operacion.node_id))


def aplicar_caja_anulacion(conn, operacion) -> None:
    # La reversión en la cuenta corriente llega por su cuenta como `cargo.asiento`: el nodo la escribió al anular.
    aplicar_anulacion_del_nodo(conn, operacion.node_id, operacion.payload)


# ── La cola de ARCA ───────────────────────────────────────────────────────────────────────────────────────────────────


def aplicar_cola_pedido(conn, operacion) -> None:
    aplicar_pedido_del_nodo(operacion.payload, conn=conn)


# ── Fotos de fila: órdenes, gastos, adjuntos, cartas de porte, terceros ───────────────────────────────────────────────


def _valores_de(conn, node_id: str, spec: Entidad, valores: Mapping) -> dict:
    """Los valores de la foto listos para escribir en el central: referencias traducidas y binarios decodificados."""
    resultado = dict(valores)
    # El id del nodo nunca se escribe: manda el del central (o el mapeo).
    resultado.pop(spec.pk, None)
    for columna, tabla in spec.refs.items():
        if columna in resultado:
            resultado[columna] = _traducir(conn, node_id, tabla, resultado[columna])
    for columna in spec.binarias:
        if columna in resultado:
            resultado[columna] = de_base64(resultado[columna])
    return resultado


def _id_central(conn, node_id: str, spec: Entidad, id_nodo: Any) -> Any:
    """El id del central de la fila del nodo, o `None` si es una alta nueva (provisorio sin mapeo)."""
    if es_provisorio(id_nodo):
        return traducir_id(conn, node_id, spec.tabla, id_nodo, exigir=False)
    if not _existe(conn, spec.tabla, spec.pk, id_nodo):
        raise NoSincronizado(f"{spec.tabla} {id_nodo} no está en el central y no es una alta del nodo "
                             "(¿la carga inicial no la trajo?)")
    return id_nodo


def _adoptar(conn, spec: Entidad, valores: Mapping) -> Any:
    """Una fila que el central ya tiene con la misma clave natural (el CTG de una carta de porte), o `None`."""
    for columna in spec.naturales:
        if valores.get(columna) is None:
            continue
        fila = conn.execute(f"SELECT {spec.pk} FROM {spec.tabla} WHERE {columna} = ?", (valores[columna],)).fetchone()
        if fila is not None:
            return fila[0]
    return None


def aplicar_fila(conn, operacion, spec: Entidad) -> int | None:
    """Aplica la foto de una fila: la inserta con un id del central (y anota el mapeo) o la actualiza. Devuelve el id
    del central, o `None` si era una baja."""
    payload, node_id = operacion.payload, operacion.node_id
    _version(payload, spec.tipo)
    id_nodo = payload["id"]
    if spec.pk_ref is not None:
        return _aplicar_dependiente(conn, operacion, spec)
    central = _id_central(conn, node_id, spec, id_nodo) if not payload.get("baja") else (
        traducir_id(conn, node_id, spec.tabla, id_nodo, exigir=False) if es_provisorio(id_nodo) else id_nodo)
    if payload.get("baja"):
        if central is not None:
            conn.execute(f"DELETE FROM {spec.tabla} WHERE {spec.pk} = ?", (central,))
        return None
    valores = _valores_de(conn, node_id, spec, payload["valores"])
    if spec.nombre == "orden" and "comprobante" in payload:
        clave = payload["comprobante"]
        valores["comprobante_id"] = None if clave is None else _factura_central(conn, clave)
    if central is None:
        central = _adoptar(conn, spec, valores)
    if central is not None:
        _actualizar(conn, spec.tabla, spec.pk, central, valores)
    else:
        central = _insertar(conn, spec.tabla, valores)
    if es_provisorio(id_nodo):
        anotar_mapeo(conn, node_id, spec.tabla, id_nodo, central)
    return central


def _aplicar_dependiente(conn, operacion, spec: Entidad) -> int | None:
    """Una fila cuya clave es la de otra (`cartas_porte_pdf.carta_porte_id`): se traduce la clave y se hace el
    upsert."""
    payload, node_id = operacion.payload, operacion.node_id
    central = _traducir(conn, node_id, spec.pk_ref, payload["id"])
    if payload.get("baja"):
        conn.execute(f"DELETE FROM {spec.tabla} WHERE {spec.pk} = ?", (central,))
        return None
    valores = _valores_de(conn, node_id, spec, payload["valores"])
    if _existe(conn, spec.tabla, spec.pk, central):
        _actualizar(conn, spec.tabla, spec.pk, central, valores)
    else:
        _insertar(conn, spec.tabla, {**valores, spec.pk: central})
    return central


def _aplicador_de_fila(spec: Entidad):
    def aplicar(conn, operacion) -> None:
        aplicar_fila(conn, operacion, spec)

    aplicar.__name__ = f"aplicar_{spec.nombre}"
    return aplicar


# ── Los terceros dados de alta en el nodo ───────────────────────────────────────────────────────────────────────

_ROLES = ("es_cliente", "es_fletero", "es_proveedor")


def _tercero_con_el_mismo_cuit(conn, cuit: str | None) -> int | None:
    """El tercero del central con ese CUIT de 11 dígitos, o `None`. Sólo cuenta un CUIT completo: el legado dejó CUIT de
    relleno («1») que no identifican a nadie y no se comparan (la misma regla que `maestros._cuit_no_repetido`)."""
    digitos = solo_digitos(cuit)
    if len(digitos) != 11:
        return None
    fila = conn.execute(
        "SELECT id FROM terceros WHERE replace(replace(coalesce(cuit, ''), '-', ''), '.', '') = ? ORDER BY id LIMIT 1",
        (digitos,)).fetchone()
    return None if fila is None else fila[0]


def aplicar_tercero(conn, operacion) -> int | None:
    """Un tercero que se dio de alta en el nodo (libraedge ADR-021). El central le asigna su id y el nodo lo recibe
    por el espejo; las operaciones que lo referencian (una orden, un cobro) se traducen con el mapeo.

    🔑 **El central deduplica por CUIT**, como la web (ADR-040: una persona o empresa es una sola entidad con roles): si
    ya hay un tercero con ese CUIT —lo dio de alta otro, o el espejo del nodo todavía no lo traía— el alta **se adopta**
    en vez de duplicarse: se anota el mapeo al que existe y se le suman los roles. El nodo reapunta a ése cuando
    baja."""
    payload, node_id = operacion.payload, operacion.node_id
    _version(payload, cargo_ops.TIPO_TERCERO)
    id_nodo = payload["id"]
    if payload.get("baja"):
        raise OperacionInvalida(f"un tercero no se borra: se da de baja (tercero {id_nodo} del nodo {node_id})")
    spec = ENTIDADES["tercero"]
    valores = dict(payload["valores"])
    valores.pop(spec.pk, None)
    central = _id_central(conn, node_id, spec, id_nodo)
    if central is None:
        existente = _tercero_con_el_mismo_cuit(conn, valores.get("cuit"))
        if existente is not None:
            roles = ", ".join(f"{r} = ({r} OR ?)" for r in _ROLES)
            conn.execute(f"UPDATE terceros SET {roles}, activo = TRUE WHERE id = ?",
                         (*[bool(valores.get(r)) for r in _ROLES], existente))
            anotar_mapeo(conn, node_id, "terceros", id_nodo, existente)
            return existente
        central = _insertar(conn, "terceros", valores)
        anotar_mapeo(conn, node_id, "terceros", id_nodo, central)
        return central
    _actualizar(conn, "terceros", "id", central, valores)
    return central


# ── El comprobante ────────────────────────────────────────────────────────────────────────────────────────────────────


def aplicar_comprobante(conn, operacion) -> int:
    """`facturas` con el número y el CAE del nodo (libracore ADR-074, idempotente por el número ante ARCA) y la fila
    propia de `comprobantes_cargo`. Devuelve el id de `facturas` del central.

    Un comprobante emitido por el nodo **no** se vuelve a emitir ni a numerar acá: el central lo recibe tal cual
    (`FacturaEnConflicto`, un `ValueError`, si ya tiene ese número con otro total u otro CAE)."""
    payload, node_id = operacion.payload, operacion.node_id
    _version(payload, cargo_ops.TIPO_COMPROBANTE)
    if payload.get("baja"):
        raise OperacionInvalida("un comprobante no se borra: se anula (el nodo avisó la baja de la factura "
                                f"{payload.get('id')})")
    factura_id, _creada = aplicar_factura_del_nodo(payload["factura"], conn=conn)
    extra = payload.get("factura_extra") or {}
    _actualizar(conn, "facturas", "id", factura_id, {
        campo: ("" if valor is None and campo != "anulada_en" else valor) for campo, valor in extra.items()
    })
    cargo = dict(payload.get("cargo") or {})
    cargo["cliente_id"] = _traducir(conn, node_id, "terceros", cargo.get("cliente_id"))
    cargo["comprobante_asociado_id"] = (
        None if payload.get("asociado") is None else _factura_central(conn, payload["asociado"]))
    if _existe(conn, "comprobantes_cargo", "factura_id", factura_id):
        _actualizar(conn, "comprobantes_cargo", "factura_id", factura_id, cargo)
    else:
        _insertar(conn, "comprobantes_cargo", {**cargo, "factura_id": factura_id})
    return factura_id


# ── El asiento ────────────────────────────────────────────────────────────────────────────────────────────────────────

#: Lo que `libro.corregir` deja cambiar de un asiento ya escrito (libracore ADR-026): el resto es otro asiento.
_CORREGIBLES = ("fecha", "tercero_id", "rol", "concepto", "descripcion", "debe", "haber", "factura_id")


def aplicar_asiento(conn, operacion) -> int | None:
    """El asiento del libro de terceros del central, con su fila propia y de dónde vino. Devuelve su id en el
    central."""
    payload, node_id = operacion.payload, operacion.node_id
    _version(payload, cargo_ops.TIPO_ASIENTO)
    id_nodo = payload["id"]
    actual = _asiento_central(conn, node_id, id_nodo)
    if payload.get("baja"):
        if actual is not None:
            conn.execute("DELETE FROM movimientos_cuenta_cargo WHERE asiento_id = ?", (actual,))
            libro.borrar(actual, conn=conn)
        return None
    valores, refs = payload["valores"], payload["refs"]
    contrapartida = None
    if refs.get("contrapartida_de") is not None:
        contrapartida = _asiento_central(conn, node_id, refs["contrapartida_de"])
        if contrapartida is None:
            raise NoSincronizado(f"el asiento {refs['contrapartida_de']} del nodo {node_id} (el que éste revierte) "
                                 "no está en el central")
    campos = {
        "fecha": valores["fecha"], "tercero_id": _traducir(conn, node_id, "terceros", valores["tercero_id"]),
        "rol": valores["rol"], "concepto": valores["concepto"], "descripcion": valores.get("descripcion"),
        "debe": valores["debe"], "haber": valores["haber"],
        "factura_id": None if refs.get("comprobante") is None else _factura_central(conn, refs["comprobante"]),
    }
    propios = {
        "orden_id": _traducir(conn, node_id, "ordenes_carga", refs.get("orden_id")),
        "gasto_id": _traducir(conn, node_id, "gastos_de_proveedor", refs.get("gasto_id")),
        "movimiento_caja_id": _movimiento_de_caja_central(conn, node_id, refs.get("movimiento_caja_id")),
    }
    if actual is not None:
        _actualizar(conn, "cc_asientos", "id", actual, {k: campos[k] for k in _CORREGIBLES})
        _actualizar(conn, "movimientos_cuenta_cargo", "asiento_id", actual, propios)
        return actual
    nuevo = _insertar(conn, "cc_asientos", {
        **campos, "contrapartida_de": contrapartida, "origen_legado": valores.get("origen_legado"),
        "usuario_id": valores.get("usuario_id")})
    _insertar(conn, "movimientos_cuenta_cargo", {
        **propios, "asiento_id": nuevo, "origen_nodo": node_id, "origen_nodo_id": id_nodo})
    return nuevo


# ── El despachador ────────────────────────────────────────────────────────────────────────────────────────────────────


def registrar_en(despachador) -> Any:
    """Registra en `despachador` todo lo que el nodo de LibraCargo sabe subir, y lo devuelve."""
    from app import offline

    version = offline.SCHEMA_VERSION
    despachador.registrar(offline.TIPO_CAJA_MOVIMIENTO, version, aplicar_caja_movimiento)
    despachador.registrar(offline.TIPO_CAJA_ANULADO, version, aplicar_caja_anulacion)
    despachador.registrar(offline.TIPO_COLA_PEDIDO, version, aplicar_cola_pedido)
    despachador.registrar(cargo_ops.TIPO_COMPROBANTE, version, aplicar_comprobante)
    despachador.registrar(cargo_ops.TIPO_ASIENTO, version, aplicar_asiento)
    despachador.registrar(cargo_ops.TIPO_TERCERO, version, aplicar_tercero)
    for spec in ENTIDADES.values():
        if spec.tipo != cargo_ops.TIPO_TERCERO:
            despachador.registrar(spec.tipo, version, _aplicador_de_fila(spec))
    return despachador
