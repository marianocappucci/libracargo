"""Los emisores de la cola de ARCA del nodo: la factura y la carta de porte, con el ticket que presta el central
(ADR-056).

Sin internet, las facturas y las CPE **quedan en cola y se emiten solas al volver la conexión** (decisión del humano,
2026-10-22). La cola es del motor (`libracore.cola_arca`, ADR-079): guarda el pedido, lo emite una sola vez con su
candado, decide qué hacer con cada error y avisa al central. Lo que es de este producto es el **emisor**, la función que
sabe armar el comprobante desde su entidad, y el contrato que el motor le pide:

- **Idempotente.** Si lo que el pedido iba a hacer ya está hecho, devuelve lo hecho sin emitir otro.
- **Nunca numera local.** El número lo pide con `ctx.numerar` (el ticket prestado), y si no puede, levanta `SinConexion`
  o `NodoSinArca`: el pedido sigue esperando y no gasta un intento.
- **Una CPE incierta no se reintenta.** El emisor de `cpe` no atrapa `EmisionIncierta`: sube tal cual y el motor deja el
  pedido `incierto` hasta que una persona consulte a ARCA.
- **Respeta el interruptor.** La emisión real de CPE está apagada por interruptor en Suitrans (ADR-043): con el
  interruptor apagado el pedido **queda esperando**, no se emite y no se pierde (`EmisionApagada`).

## Por qué el trabajo se hace en un hilo

La emisión de este producto es sincrónica (la `Session` de SQLAlchemy, `openssl`, `asyncio.run` en los bordes de red;
ver `servicios/facturacion.py`) y la cola corre el emisor dentro de su propio loop. `asyncio.to_thread` le da a la
emisión un hilo propio, donde `asyncio.run` abre un loop nuevo sin chocar con el de la cola.

Fuera de un nodo estos emisores no se usan: `libracore.cola_arca.encolar` se rehúsa en el central.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from decimal import Decimal

from libracore import cola_arca
from libracore.cuit import solo_digitos
from libracore.db import cola_arca as db_cola
from libracore.nodo_offline import NodoSinArca
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import db, offline
from app.models.enums import CODIGO_ARCA, EstadoOrden, TipoComprobante
from app.models.maestros import Tercero
from app.models.operacion import Comprobante, OrdenCarga
from app.schemas.comprobantes import ConceptoIn
from app.servicios import cartas_porte as cpe_servicio
from app.servicios import comprobantes, emision_arca, emision_cpe, facturacion

_log = logging.getLogger(__name__)

CLASE_ORDENES = "ordenes"
CLASE_DIRECTA = "directa"


class EmisionRechazada(Exception):
    """El pedido no se pudo cumplir y no se arregla esperando: ARCA rechazó, un dato no sirve, la orden ya no está
    pendiente. La cola lo deja `a_revisar` con este mensaje, y una persona lo corrige o lo descarta."""

    def __init__(self, mensaje: str, status: int = 422):
        super().__init__(mensaje)
        self.status = status


class EnsayoSinGuardar(EmisionRechazada):
    """Se emitió contra homologación: se corrió todo y se revirtió, como en la web (`Ensayo`). No hay comprobante."""


# ── El pedido ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def nuevo_origen(prefijo: str) -> str:
    """El `origen_id` de un pedido nuevo. Único a propósito: la clave de la cola es `(producto, nodo, tipo, origen_id)`,
    y un pedido `descartado` o `emitido` con el mismo origen no se puede volver a encolar. Que no se facture dos veces
    lo mismo lo cuidan las órdenes (`cargar_ordenes`, `exigir_que_no_esten_en_cola`) y el candado por cliente."""
    return f"{prefijo}:{uuid.uuid4().hex}"


def datos_de_ordenes(usuario: dict | None, *, cliente_id: int, orden_ids: list[int], tipo: TipoComprobante,
                     vencimiento: date | None, cuenta: str | None, observaciones: str) -> dict:
    """Los `datos` (JSON estricto) del pedido «Facturar pendientes». Poco: los ids y lo que no se puede releer."""
    return {
        "clase": CLASE_ORDENES, "usuario": _usuario(usuario), "cliente_id": cliente_id, "orden_ids": sorted(orden_ids),
        "tipo": tipo.value, "vencimiento": vencimiento.isoformat() if vencimiento else None, "cuenta": cuenta,
        "observaciones": observaciones or "",
    }


def datos_directa(usuario: dict | None, *, cliente_id: int, conceptos: list[ConceptoIn], tipo: TipoComprobante,
                  vencimiento: date | None, cuenta: str | None, observaciones: str) -> dict:
    """Los `datos` del pedido «Nueva factura»: los conceptos, con los importes como texto (sin `Decimal`)."""
    return {
        "clase": CLASE_DIRECTA, "usuario": _usuario(usuario), "cliente_id": cliente_id,
        "conceptos": [{"descripcion": c.descripcion, "cantidad": str(c.cantidad),
                       "precio_unitario": str(c.precio_unitario), "alicuota_iva": str(c.alicuota_iva)}
                      for c in conceptos],
        "tipo": tipo.value, "vencimiento": vencimiento.isoformat() if vencimiento else None, "cuenta": cuenta,
        "observaciones": observaciones or "",
    }


def _usuario(actual: dict | None) -> dict:
    """Quién lo pidió, para la auditoría: el pedido puede salir horas después, en un hilo sin sesión web."""
    actual = actual or {}
    return {"id": actual.get("id"), "username": actual.get("username")}


# ── La factura ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _ya_emitido(sesion, datos: dict) -> dict | None:
    """Si las órdenes del pedido ya salieron en **un** comprobante con CAE (el pedido se emitió y el nodo no llegó a
    anotarlo), lo devuelve sin emitir otro. Sólo vale para «Facturar pendientes»: una factura directa no tiene entidad
    que lo diga, y ahí lo cubre el estado `emitiendo` → `incierto` de la cola."""
    if datos["clase"] != CLASE_ORDENES:
        return None
    ordenes = list(sesion.scalars(select(OrdenCarga).where(OrdenCarga.id.in_(datos["orden_ids"]))))
    if not ordenes or any(o.estado is not EstadoOrden.FACTURADA or o.comprobante_id is None for o in ordenes):
        return None
    ids = {o.comprobante_id for o in ordenes}
    if len(ids) != 1:
        return None
    comprobante = sesion.get(Comprobante, ids.pop())
    if comprobante is None or not comprobante.cae:
        return None
    return _resultado(comprobante)


def _cliente_vigente(sesion, cliente_id: int) -> int:
    """El id que tiene hoy el cliente de un pedido. Un tercero dado de alta en el nodo tiene un id provisorio
    (negativo) hasta que baja el definitivo; LibraEdge reapunta lo que lo referenciaba, pero el pedido de la cola lo
    guardó **dentro de su JSON** y no se entera. Si el provisorio ya no existe, se busca su definitivo en el mapeo que
    bajó del central."""
    if cliente_id >= 0 or sesion.get(Tercero, cliente_id) is not None:
        return cliente_id
    fila = sesion.execute(
        text("SELECT id_central FROM libraedge_mapeo WHERE node_id = :nodo AND tabla = 'terceros' AND id_nodo = :id"),
        {"nodo": offline.nodo(), "id": cliente_id}).first()
    return cliente_id if fila is None else int(fila[0])


def _resultado(comprobante) -> dict:
    return {"factura_id": comprobante.id, "cae": comprobante.cae, "tipo": comprobante.tipo.value,
            "punto_venta": comprobante.punto_venta, "numero": comprobante.numero}


def _emitir_documento(pedido: dict, ctx) -> dict:
    """El cuerpo del emisor `documento`, en un hilo propio (ver el docstring del módulo)."""
    datos = pedido["datos"]
    tipo = TipoComprobante(datos["tipo"])
    vencimiento = date.fromisoformat(datos["vencimiento"]) if datos.get("vencimiento") else None
    with db.fabrica_de_sesiones()() as sesion:
        ya = _ya_emitido(sesion, datos)
        if ya is not None:
            return ya
        cfg = emision_arca.configuracion_de_la_instancia()
        if cfg is None:
            raise NodoSinArca("Este equipo no tiene la configuración de ARCA del central (falta espejar arca_config).")
        # La fecha del hecho si ARCA todavía la admite, si no la de hoy, y nunca antes que el último comprobante de la
        # serie (libracore ADR-074 y ADR-079): una factura que esperó horas sin red no sale con una fecha que ARCA
        # rechaza.
        fecha = ctx.fecha_de_la_factura(int(cfg["punto_venta"]), CODIGO_ARCA[tipo], cfg["ambiente"],
                                        emisor_id=cfg.get("id"))
        actual = datos.get("usuario") or {}
        cliente_id = _cliente_vigente(sesion, datos["cliente_id"])
        try:
            if datos["clase"] == CLASE_ORDENES:
                comprobante = facturacion.facturar_ordenes(
                    sesion, actual, cliente_id=cliente_id, orden_ids=datos["orden_ids"], tipo=tipo,
                    fecha=fecha, vencimiento=vencimiento, cuenta=datos.get("cuenta"),
                    observaciones=datos.get("observaciones") or "", numerar=ctx.numerar)
            else:
                conceptos = [ConceptoIn(
                    descripcion=c["descripcion"], cantidad=Decimal(c["cantidad"]),
                    precio_unitario=Decimal(c["precio_unitario"]), alicuota_iva=Decimal(c["alicuota_iva"]))
                    for c in datos["conceptos"]]
                comprobante = facturacion.facturar_directa(
                    sesion, actual, cliente_id=cliente_id, conceptos=conceptos, tipo=tipo, fecha=fecha,
                    vencimiento=vencimiento, cuenta=datos.get("cuenta"),
                    observaciones=datos.get("observaciones") or "", numerar=ctx.numerar)
            sesion.commit()
        except facturacion.Ensayo as e:
            raise EnsayoSinGuardar(
                "Se emitió contra homologación (ensayo): se corrió todo y no se guardó nada "
                f"(CAE de prueba {e.respuesta.get('cae')})."
            ) from None
        except facturacion.Rechazo as e:
            sesion.rollback()
            raise EmisionRechazada(e.detalle, e.status) from None
        except Exception:
            sesion.rollback()
            raise
        resultado = _resultado(comprobante)
        # El PDF va después de confirmar y un fallo suyo no deshace nada (ver `comprobantes.guardar_pdf`).
        comprobantes.guardar_pdf(sesion, comprobante)
        return resultado


async def emitir_documento(pedido: dict, ctx) -> dict:
    """El emisor `documento` de la cola: una factura desde órdenes, o una factura directa. Ver el docstring del
    módulo."""
    return await asyncio.to_thread(_emitir_documento, pedido, ctx)


# ── La carta de porte ─────────────────────────────────────────────────────────────────────────────────────────────────


def datos_de_cpe(usuario: dict | None, *, orden_id: int, datos: dict, confirmo: bool) -> dict:
    """Los `datos` del pedido de una CPE: la solicitud tal como la armó la persona y su confirmación explícita de que es
    una carta de porte real (que se pidió **ahora**, aunque salga horas después)."""
    return {"usuario": _usuario(usuario), "orden_id": orden_id, "solicitud": datos, "confirmo": bool(confirmo)}


def _emitir_cpe(pedido: dict, ticket: dict) -> dict:
    datos = pedido["datos"]
    with db.fabrica_de_sesiones()() as sesion:
        try:
            fila = emision_cpe.emitir(
                sesion, datos.get("usuario"), datos["orden_id"], datos["solicitud"], confirmo=datos["confirmo"],
                ticket=ticket)
        except cpe_servicio.Rechazo as e:
            # `EmisionApagada` y `EmitidaSinGuardar` llevan sus marcas y la cola las lee; el resto es un pedido
            # que no se puede cumplir: a revisar, con el mensaje.
            if hasattr(e, "rechazo_del_central") or hasattr(e, "emision_incierta"):
                raise
            raise EmisionRechazada(e.detalle, e.status) from None
        return {"ctg": fila.nro_ctg, "carta_porte_id": fila.id, "numero": f"{fila.sucursal:05d}-{fila.nro_orden:08d}",
                "ambiente": fila.ambiente}


async def emitir_cpe(pedido: dict, ctx) -> dict:
    """El emisor `cpe` de la cola: pide el ticket de `wscpe` al central y emite con él. **No atrapa `EmisionIncierta`**:
    sube y el motor deja el pedido `incierto` (libracore ADR-079)."""
    ticket, _arca = await ctx.ticket("wscpe")
    return await asyncio.to_thread(_emitir_cpe, pedido, ticket)


# ── Pedir una emisión desde la web del nodo ─────────────────────────────────────────────────────────────────────
#
# En un nodo la persona no emite "ya": **pide**, y el pedido pasa siempre por la cola (libracore ADR-079). Con
# conexión sale en el momento; sin ella queda esperando y sale solo al volver. Quien llama (el router) traduce el
# pedido a una respuesta.

#: Los estados en los que un pedido todavía ocupa sus órdenes: no se puede pedir otra factura por ellas.
_ABIERTOS = (db_cola.ESTADO_ESPERANDO, db_cola.ESTADO_EMITIENDO, db_cola.ESTADO_A_REVISAR, db_cola.ESTADO_INCIERTO)

MENSAJE_APAGADA = "La emisión de Cartas de Porte reales está apagada: la habilita un administrador."


def _id_de_usuario(actual: dict | None) -> int | None:
    valor = str((actual or {}).get("id", ""))
    return int(valor) if valor.isdigit() else None


def exigir_que_no_esten_en_cola(orden_ids: list[int]) -> None:
    """Una orden en un pedido de factura abierto no se pide dos veces: la cola no las reserva (la orden sigue
    «pendiente» hasta que sale) y sin esto un doble clic dejaría dos pedidos por lo mismo. Levanta `Rechazo` 409."""
    cola = offline.cola()
    pedidos = db_cola.listar(estados=_ABIERTOS, origen_producto=cola.producto, origen_instancia=cola.instancia(),
                             origen_tipo=db_cola.ORIGEN_DOCUMENTO)
    for pedido in pedidos:
        repetidas = sorted(set(pedido["datos"].get("orden_ids") or ()) & set(orden_ids))
        if repetidas:
            raise facturacion.Rechazo(
                409, f"las órdenes {repetidas} ya están en un pedido de factura ({pedido['estado']}, pedido "
                     f"{pedido['id']}): esperá a que salga o resolvelo en la cola")


def pedir_factura(sesion: Session, actual: dict | None, *, clase: str, entrada) -> dict:
    """Valida el pedido de factura (lo mismo que `facturar_*` antes de ir a ARCA), lo deja en la cola y, si hay
    conexión, lo emite. Devuelve el pedido como quedó (`emitido`, `esperando`, `a_revisar` o `incierto`). Levanta
    `facturacion.Rechazo` si el pedido ya se sabe inválido: ese no se encola."""
    tipo, fecha, vencimiento = entrada.tipo, entrada.fecha, entrada.fecha_vencimiento_pago
    if clase == CLASE_ORDENES:
        facturacion.validar_de_ordenes(sesion, cliente_id=entrada.cliente_id, orden_ids=entrada.orden_ids, tipo=tipo,
                                       fecha=fecha, vencimiento=vencimiento)
        exigir_que_no_esten_en_cola(entrada.orden_ids)
        datos = datos_de_ordenes(actual, cliente_id=entrada.cliente_id, orden_ids=entrada.orden_ids, tipo=tipo,
                                 vencimiento=vencimiento, cuenta=entrada.fce_cbu, observaciones=entrada.observaciones)
    else:
        facturacion.validar_directa(sesion, cliente_id=entrada.cliente_id, conceptos=entrada.conceptos, tipo=tipo,
                                    fecha=fecha, vencimiento=vencimiento)
        datos = datos_directa(actual, cliente_id=entrada.cliente_id, conceptos=entrada.conceptos, tipo=tipo,
                              vencimiento=vencimiento, cuenta=entrada.fce_cbu, observaciones=entrada.observaciones)
    # La validación bloqueó las órdenes (`FOR UPDATE`): se sueltan antes de emitir, que las vuelve a leer y bloquear.
    sesion.rollback()
    return asyncio.run(cola_arca.encolar_y_emitir(
        offline.cola(), db_cola.ORIGEN_DOCUMENTO, nuevo_origen(clase), datos=datos, fecha_ref=fecha.isoformat(),
        concepto=1, usuario_id=_id_de_usuario(actual)))


def pedir_cpe(sesion: Session, actual: dict | None, *, orden_id: int, datos: dict, confirmo: bool) -> dict:
    """Valida lo que se sabe sin ARCA, deja el pedido de la CPE en la cola y, si hay conexión, la emite. Devuelve el
    pedido como quedó.

    🔑 **El interruptor se respeta en las dos puntas.** Con conexión y el interruptor apagado en producción, se contesta
    409 como en la web y **no se encola nada**. Sin conexión no se sabe en qué ambiente cae (lo dice el ticket), así que
    se encola y el emisor lo vuelve a mirar al emitir: apagado, el pedido espera con ese motivo (`EmisionApagada`).
    """
    if sesion.get(OrdenCarga, orden_id) is None:
        raise cpe_servicio.Rechazo(404, f"no existe la orden {orden_id}")
    emision_cpe._exigir_que_emitamos_nosotros(sesion, solo_digitos(datos.get("cuit_titular", "")))
    try:
        emision_cpe._solicitud({**datos, "cuit_titular": solo_digitos(datos.get("cuit_titular", ""))})
    except (KeyError, TypeError, ValueError) as e:
        raise cpe_servicio.Rechazo(422, f"Falta o no sirve un dato de la carta de porte: {e}") from None
    if not offline.CONEXION.sin_conexion():
        # Con conexión se sabe el ambiente (lo dice el ticket) y el interruptor se mira ya, como en la web: apagado,
        # 409 y nada en la cola. Sin conexión no se sabe, y lo mira el emisor al emitir.
        est = emision_cpe.estado(sesion)
        if est["ambiente"] is not None and not est["puede_emitir"]:
            raise emision_cpe.EmisionApagada(409, MENSAJE_APAGADA)
    sesion.rollback()
    partida = (datos.get("transporte") or {}).get("fecha_hora_partida")
    return asyncio.run(cola_arca.encolar_y_emitir(
        offline.cola(), db_cola.ORIGEN_CPE, nuevo_origen(f"orden{orden_id}"),
        datos=datos_de_cpe(actual, orden_id=orden_id, datos=datos, confirmo=confirmo),
        fecha_ref=str(partida or ""), usuario_id=_id_de_usuario(actual)))
