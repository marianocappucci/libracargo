"""El nodo sube lo que escribe: avisa cada cambio de una entidad y, al confirmar, encola la foto de la fila (ADR-056).

Es la mitad del nodo de las operaciones `cargo.*` (`cargo_ops.py` es el vocabulario y `aplicadores.py` la mitad del
central). Un nodo de LibraCargo escribe órdenes, gastos, comprobantes, cartas de porte y asientos por **muchos** caminos
—los routers, la emisión de la cola, el refresco de las CPE, las notas—, y que uno solo se olvide de avisar es una orden
que el central nunca ve. Por eso el aviso no depende de que cada camino se acuerde:

- las entidades que son un **modelo del ORM** se avisan solas, con un `after_flush` de la sesión (nuevo, modificado o
  borrado);
- las que escribe **el motor** con SQL propio (el CAE de una factura, los asientos) las avisa quien las escribe con
  `tocar(sesion, "comprobante", id)`: son cuatro funciones (`servicios/comprobantes.py` y `servicios/cuentas.py`).

Lo avisado se junta en la sesión y se encola **al confirmar** (`before_commit`), en la misma transacción, **una vez por
entidad** y en el orden en que una operación puede referirse a otra (`cargo_ops.prioridad_de`). Se lee la fila como
quedó: si cambió tres veces en la transacción, sube una foto. Si la transacción se deshace, el aviso se va con ella y el
outbox también (viven en la misma conexión).

🔑 **Un fallo acá frena el cambio**, igual que un gancho de la caja del motor (libracore ADR-076): una orden que se
carga en el nodo y no sube es una orden que el central no ve. Mejor que la persona vea el error.

Fuera de un nodo (`offline.nodo()` es `None`: el central, Suitrans hoy) los oyentes no hacen nada.

## Los ids provisorios

Lo que nace en el nodo (órdenes, gastos, adjuntos, cartas de porte, terceros) toma un id **negativo** antes de
insertarse (`before_insert`): ver `cargo_ops`.
"""

from __future__ import annotations

import logging
from typing import Any

from libracore.db import facturas as db_facturas
from libracore.db.migraciones import conexion_libracore
from libracore.facturas_del_nodo import payload_factura
from libraedge.mapeo import siguiente_id_provisorio
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import offline
from app.servicios import cargo_ops
from app.servicios.cargo_ops import ENTIDADES, TIPOS, VERSION, a_json, foto_de_fila, prioridad_de, seleccion_exacta

_log = logging.getLogger(__name__)

#: Dónde la sesión junta lo avisado: `{(entidad, id): True}`, en el orden en que se avisó.
CLAVE = "libracargo.subida"

#: Las columnas de `facturas` que `payload_factura` no lleva y el central necesita (la cuenta de cobro de una FCE, la
#: marca de anulada, el motivo del rechazo de ARCA): viajan aparte y el central las pone con un `UPDATE`.
EXTRA_DE_FACTURA = ("fce_cbu", "fce_transmision", "fce_anulacion", "cbte_asoc_fecha", "cae_error", "anulada_en",
                    "anulacion_motivo")

#: Cómo se reconoce un comprobante ante ARCA (y en el central): `(emisor, ambiente, tipo, punto de venta, número)`.
CLAVE_DE_FACTURA = ("tipo", "punto_venta", "numero", "ambiente", "emisor_id")


# ── Avisar ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def tocar(sesion: Session, entidad: str, id_: Any) -> None:
    """Avisa que la entidad `entidad` con ese id cambió en esta transacción, para subirla al confirmar. Fuera de un nodo
    no hace nada. `entidad` es una de `cargo_ops.TIPOS`."""
    if entidad not in TIPOS:
        raise ValueError(f"no sé subir {entidad!r} (sé {sorted(TIPOS)})")
    if id_ is None or offline.nodo() is None:
        return
    sesion.info.setdefault(CLAVE, {})[(entidad, id_)] = True


def _entidad_de(obj: Any) -> tuple[str, Any] | None:
    """La entidad que subir cuando cambia `obj` (un modelo del ORM), o `None` si no se sube."""
    from app.models import cartas_porte, cuentas, maestros, operacion

    if isinstance(obj, operacion.OrdenCarga):
        return "orden", obj.id
    if isinstance(obj, operacion.GastoDeProveedor):
        return "gasto", obj.id
    if isinstance(obj, operacion.AdjuntoDeOrden):
        return "adjunto", obj.id
    if isinstance(obj, cartas_porte.CartaPorte):
        return "carta_porte", obj.id
    if isinstance(obj, cartas_porte.CartaPortePdf):
        return "carta_porte_pdf", obj.carta_porte_id
    if isinstance(obj, operacion.Comprobante):
        return "comprobante", obj.id
    if isinstance(obj, operacion.ComprobanteCargo):
        return "comprobante", obj.factura_id
    if isinstance(obj, maestros.Tercero):
        return "tercero", obj.id
    if isinstance(obj, cuentas.MovimientoCuentaCargo):
        return "asiento", obj.asiento_id
    return None


def _al_flushear(sesion: Session, _contexto) -> None:
    if offline.nodo() is None:
        return
    for obj in (*sesion.new, *sesion.dirty, *sesion.deleted):
        entidad = _entidad_de(obj)
        if entidad is not None:
            tocar(sesion, *entidad)


def _al_deshacer(sesion: Session, *_args) -> None:
    sesion.info.pop(CLAVE, None)


def _antes_de_confirmar(sesion: Session) -> None:
    if offline.nodo() is None:
        sesion.info.pop(CLAVE, None)
        return
    # Lo que todavía no se mandó a la base: el `flush` avisa lo último que cambió.
    sesion.flush()
    avisadas = sesion.info.pop(CLAVE, None)
    if not avisadas:
        return
    conn = conexion_libracore(sesion.connection())
    # Un orden estable por prioridad: `sorted` conserva el orden en que se avisó dentro de cada una.
    for entidad, id_ in sorted(avisadas, key=lambda par: prioridad_de(par[0])):
        subir(conn, entidad, id_)


def subir(conn, entidad: str, id_: Any) -> None:
    """Encola la foto de la entidad tal como está ahora en `conn`. Es lo que corre al confirmar, y lo que usa la carga o
    un reproceso para reencolar algo (`tocar` + confirmar es el camino normal)."""
    payload = payload_de(conn, entidad, id_)
    offline.encolar_operacion(conn, TIPOS[entidad], entidad, id_, payload)


# ── Los ids provisorios
# ────────────────────────────────────────────────────────────────────────────────────────────────


def _con_id_provisorio(columna: str):
    def antes_de_insertar(_mapper, connection, objetivo) -> None:
        if offline.nodo() is None or getattr(objetivo, columna) is not None:
            return
        setattr(objetivo, columna, siguiente_id_provisorio(conexion_libracore(connection)))

    return antes_de_insertar


# ── La foto de cada entidad
# ────────────────────────────────────────────────────────────────────────────────────────────


def clave_de_factura(factura: dict | None) -> dict | None:
    """Cómo se reconoce un comprobante fuera de la base del nodo: el número que le dio ARCA. Los ids de `facturas` del
    nodo no son los del central, pero esto sí."""
    if factura is None:
        return None
    return {campo: factura.get(campo) for campo in CLAVE_DE_FACTURA}


def _factura(conn, factura_id: Any) -> dict | None:
    return None if factura_id is None else db_facturas.get_factura(int(factura_id), conn=conn)


def payload_de(conn, entidad: str, id_: Any) -> dict:
    """El payload de la operación de `entidad`/`id_`: la foto de la fila, o `{"baja": True}` si ya no existe."""
    if entidad == "comprobante":
        return _payload_comprobante(conn, id_)
    if entidad == "asiento":
        return _payload_asiento(conn, id_)
    spec = ENTIDADES[entidad]
    columnas = seleccion_exacta(conn, spec.tabla)
    fila = conn.execute(f"SELECT {columnas} FROM {spec.tabla} WHERE {spec.pk} = ?", (id_,)).fetchone()
    if fila is None:
        return {"version": VERSION, "id": id_, "baja": True}
    valores = foto_de_fila(fila, spec)
    payload = {"version": VERSION, "id": id_}
    if entidad == "orden":
        # El comprobante de una orden es una fila de `facturas` con un id del nodo: viaja su número ante ARCA.
        payload["comprobante"] = clave_de_factura(_factura(conn, valores.pop("comprobante_id", None)))
    payload["valores"] = valores
    return payload


def _payload_comprobante(conn, factura_id: Any) -> dict:
    factura = _factura(conn, factura_id)
    if factura is None:
        return {"version": VERSION, "id": factura_id, "baja": True}
    cargo = conn.execute("SELECT * FROM comprobantes_cargo WHERE factura_id = ?", (factura["id"],)).fetchone()
    cargo = {k: a_json(v) for k, v in dict(cargo).items() if k != "factura_id"} if cargo else {}
    asociado = cargo.pop("comprobante_asociado_id", None)
    return {
        "version": VERSION, "id": factura["id"],
        "factura": payload_factura(factura),
        "factura_extra": {campo: a_json(factura.get(campo)) for campo in EXTRA_DE_FACTURA},
        "cargo": cargo,
        "asociado": clave_de_factura(_factura(conn, asociado)),
    }


_ASIENTO = (
    "SELECT a.id, a.fecha, a.tercero_id, a.rol, a.concepto, a.descripcion, a.debe::text AS debe, "
    "a.haber::text AS haber, a.factura_id, a.contrapartida_de, a.origen_legado, a.usuario_id, c.orden_id, "
    "c.movimiento_caja_id, c.gasto_id "
    "FROM cc_asientos a LEFT JOIN movimientos_cuenta_cargo c ON c.asiento_id = a.id WHERE a.id = ?"
)


def _payload_asiento(conn, asiento_id: Any) -> dict:
    fila = conn.execute(_ASIENTO, (asiento_id,)).fetchone()
    if fila is None:
        return {"version": VERSION, "id": asiento_id, "baja": True}
    d = dict(fila)
    return {
        "version": VERSION, "id": d["id"],
        "valores": {k: a_json(d[k]) for k in ("fecha", "tercero_id", "rol", "concepto", "descripcion", "debe", "haber",
                                              "origen_legado", "usuario_id")},
        "refs": {
            "orden_id": d["orden_id"], "movimiento_caja_id": d["movimiento_caja_id"], "gasto_id": d["gasto_id"],
            "contrapartida_de": d["contrapartida_de"],
            "comprobante": clave_de_factura(_factura(conn, d["factura_id"])),
        },
    }


# ── Instalar los oyentes
# ───────────────────────────────────────────────────────────────────────────────────────────────

_instalado = False


def instalar() -> None:
    """Engancha los oyentes a la sesión y a los modelos. Una vez por proceso (`crear_app()` la llama y puede correr
    varias veces en una suite); fuera de un nodo no hacen nada, así que se instala siempre, igual en las dos puntas."""
    global _instalado
    if _instalado:
        return
    _instalado = True
    from app.models import cartas_porte, maestros, operacion

    event.listen(Session, "after_flush", _al_flushear)
    event.listen(Session, "before_commit", _antes_de_confirmar)
    event.listen(Session, "after_rollback", _al_deshacer)
    event.listen(Session, "after_soft_rollback", _al_deshacer)
    for modelo, columna in (
        (operacion.OrdenCarga, "id"), (operacion.GastoDeProveedor, "id"), (operacion.AdjuntoDeOrden, "id"),
        (cartas_porte.CartaPorte, "id"), (maestros.Tercero, "id"),
    ):
        event.listen(modelo, "before_insert", _con_id_provisorio(columna))


__all__ = ["CLAVE", "ENTIDADES", "cargo_ops", "clave_de_factura", "instalar", "payload_de", "subir", "tocar"]
