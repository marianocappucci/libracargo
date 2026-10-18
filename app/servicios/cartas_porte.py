"""Traer Cartas de Porte Electrónicas de ARCA por su CTG y guardarlas (ADR-036).

El protocolo es del motor (`libracore.arca_wscpe`, ADR-034): acá está sólo lo de este producto —dónde se guarda,
contra qué maestros se cruza y con qué orden se vincula—.

🔑 **Por quién se consulta lo elige el operador en cada pedido** (`cuit_representada`), entre los CUIT que el ticket
de WSAA deja operar (`representados`). No hay valor por defecto: el certificado es de una persona que actúa por
Suitrans, y cada titular que le delegue la emisión suma un CUIT más.

🔑 **El ambiente es el del certificado `wscpe` que esté cargado, producción primero.** En homologación no existen las
CPE reales; si sólo hay par de homologación, se consulta ahí (sirve para probar). Cada CPE guarda de qué ambiente
salió y se actualiza siempre contra ése.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from libracore import arca_credenciales, arca_wscpe
from libracore.cuit import solo_digitos
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccionAuditoria, OrdenCarga, Tercero
from app.models.cartas_porte import CartaPorte, CartaPortePdf
from app.servicios import auditoria, catalogo_cpe
from app.servicios.emision_arca import EMPRESA_ARCA

logger = logging.getLogger(__name__)

#: Los estados en los que una CPE ya no cambia: no se vuelve a consultar al «actualizar las abiertas».
ESTADOS_CERRADOS = frozenset({"AN", "RE", "DE"})

#: Lo que cambia con **cada** consulta aunque ARCA conteste lo mismo: la hora y el XML entero. No va a la auditoría,
#: o el refresco programado dejaría un asiento por carta por corrida con un diff que no dice nada (ADR-051).
RUIDO_DE_AUDITORIA = frozenset({"consultada_en", "respuesta_arca"})

#: Tope de CTG por pedido. Cada uno es una llamada a ARCA dentro del mismo request.
MAX_POR_LOTE = 50


class Rechazo(Exception):
    """Un pedido que no se puede cumplir, con el status HTTP que le corresponde."""

    def __init__(self, status: int, detalle: str):
        super().__init__(detalle)
        self.status = status
        self.detalle = detalle


# ── Ambiente y ticket ──────────────────────────────────────────────────────

def ambiente() -> str | None:
    """El ambiente con el par de `wscpe` completo: producción si está, si no homologación. `None` si ninguno."""
    for amb in ("produccion", "homologacion"):
        cert, clave = arca_credenciales.paths_en_disco_de_servicio(EMPRESA_ARCA, arca_wscpe.SERVICIO, amb)
        if cert and clave:
            return amb
    return None


def _ambiente_o_rechazo() -> str:
    amb = ambiente()
    if amb is None:
        raise Rechazo(409, "No hay certificado de «CTG y Carta de Porte» cargado: cargalo en Configuración / ARCA.")
    return amb


def _ticket(amb: str) -> dict:
    try:
        return asyncio.run(arca_wscpe.autenticar(EMPRESA_ARCA, amb))
    except arca_wscpe.SinCredenciales as e:
        raise Rechazo(409, str(e)) from None
    except RuntimeError as e:
        raise Rechazo(502, f"ARCA no dio acceso al servicio de Carta de Porte: {e}") from None


def nombres_por_cuit(sesion: Session, cuits) -> dict[str, str]:
    """`cuit -> razón social` de los terceros cargados. Compara sólo los dígitos: en `terceros` hay CUIT con guiones."""
    buscados = {c for c in cuits if c}
    if not buscados:
        return {}
    limpio = func.replace(func.replace(Tercero.cuit, "-", ""), ".", "")
    filas = sesion.execute(select(limpio, Tercero.razon_social).where(limpio.in_(buscados))).all()
    return {cuit: nombre for cuit, nombre in filas}


def representados(sesion: Session) -> dict:
    """Por quién se puede consultar: el ambiente y los CUIT del ticket, con el nombre si el tercero está cargado."""
    amb = _ambiente_o_rechazo()
    cuits = arca_wscpe.cuits_habilitados(_ticket(amb))
    nombres = nombres_por_cuit(sesion, cuits)
    return {"ambiente": amb, "cuits": [{"cuit": c, "nombre": nombres.get(c)} for c in cuits]}


# ── Consultar ──────────────────────────────────────────────────────────────

def _exigir_cuit(cuit_representada: str) -> str:
    cuit = solo_digitos(cuit_representada)
    if len(cuit) != 11:
        raise Rechazo(422, "Elegí por qué CUIT se consulta (11 dígitos).")
    return cuit


def consultar(ctg: int, cuit_representada: str, *, amb: str | None = None,
              ticket: dict | None = None) -> tuple[arca_wscpe.CartaDePorte, str]:
    """La CPE `ctg` tal como la tiene ARCA, sin guardar nada. Devuelve la CPE y el ambiente."""
    cuit = _exigir_cuit(cuit_representada)
    amb = amb or _ambiente_o_rechazo()
    ticket = ticket or _ticket(amb)
    try:
        cpe = asyncio.run(arca_wscpe.consultar_cpe(cuit, ticket["token"], ticket["sign"], ctg=ctg, ambiente=amb))
    except arca_wscpe.CpeNoEncontrada:
        raise Rechazo(404, f"ARCA no tiene la CPE con CTG {ctg} para el CUIT {cuit}: revisá el número, o que ese "
                           "CUIT intervenga en la carta de porte.") from None
    except arca_wscpe.CuitNoRelacionado as e:
        raise Rechazo(409, str(e)) from None
    except arca_wscpe.ErrorWscpe as e:
        raise Rechazo(502, str(e)) from None
    except RuntimeError as e:
        raise Rechazo(502, f"ARCA no contestó: {e}") from None
    return cpe, amb


# ── Guardar ────────────────────────────────────────────────────────────────

def _volcar(fila: CartaPorte, cpe: arca_wscpe.CartaDePorte, cuit: str, amb: str) -> None:
    fila.nro_ctg = cpe.nro_ctg
    fila.tipo_cpe, fila.sucursal, fila.nro_orden = cpe.tipo_cpe, cpe.sucursal, cpe.nro_orden
    fila.estado = cpe.estado or "?"
    fila.fecha_emision, fila.fecha_vencimiento = cpe.fecha_emision, cpe.fecha_vencimiento
    fila.fecha_inicio_estado = cpe.fecha_inicio_estado
    t, c = cpe.transporte, cpe.carga
    fila.fecha_partida = t.fecha_hora_partida
    fila.cuit_representada, fila.ambiente = cuit, amb
    fila.cuit_transportista, fila.cuit_pagador_flete, fila.cuit_chofer = (
        t.cuit_transportista, t.cuit_pagador_flete, t.cuit_chofer)
    fila.cuit_origen, fila.cuit_destino = cpe.origen.cuit, cpe.destino.cuit
    fila.cuit_destinatario = cpe.destino.cuit_destinatario
    fila.dominios = ",".join(t.dominios) or None
    fila.cod_grano, fila.cosecha = c.cod_grano, c.cosecha
    fila.peso_bruto, fila.peso_tara = c.peso_bruto, c.peso_tara
    fila.peso_bruto_descarga, fila.peso_tara_descarga = c.peso_bruto_descarga, c.peso_tara_descarga
    fila.cod_provincia_origen, fila.cod_localidad_origen = cpe.origen.cod_provincia, cpe.origen.cod_localidad
    fila.cod_provincia_destino, fila.cod_localidad_destino = cpe.destino.cod_provincia, cpe.destino.cod_localidad
    fila.planta_destino = cpe.destino.planta
    fila.km, fila.tarifa = t.km, t.tarifa
    fila.respuesta_arca = cpe.respuesta_xml
    fila.consultada_en = datetime.now(UTC)


def _guardar_pdf(sesion: Session, fila: CartaPorte, pdf: bytes | None) -> None:
    if not pdf:
        return
    existente = sesion.get(CartaPortePdf, fila.id)
    if existente is None:
        sesion.add(CartaPortePdf(carta_porte_id=fila.id, contenido=pdf))
    else:
        existente.contenido = pdf


def _usuario_id(usuario: dict | None) -> int | None:
    valor = str((usuario or {}).get("id", ""))
    return int(valor) if valor.isdigit() else None


def guardar(sesion: Session, usuario: dict | None, cpe: arca_wscpe.CartaDePorte, cuit: str, amb: str,
            orden_carga_id: int | None = None) -> CartaPorte:
    """Alta o actualización por CTG. **No commitea.** Una CPE ya guardada conserva su orden si no se pide otra."""
    fila = sesion.scalar(select(CartaPorte).where(CartaPorte.nro_ctg == cpe.nro_ctg).with_for_update())
    if orden_carga_id is not None:
        _exigir_orden(sesion, orden_carga_id)
    if fila is None:
        fila = CartaPorte(created_by=_usuario_id(usuario))
        _volcar(fila, cpe, cuit, amb)
        fila.orden_carga_id = orden_carga_id
        sesion.add(fila)
        sesion.flush()
        auditoria.registrar(sesion, usuario, "carta_porte", fila.id, AccionAuditoria.ALTA, despues=fila)
    else:
        antes = auditoria.instantanea(fila)
        _volcar(fila, cpe, cuit, amb)
        if orden_carga_id is not None:
            fila.orden_carga_id = orden_carga_id
        fila.updated_by = _usuario_id(usuario)
        sesion.flush()
        # 🔑 Se relee: ARCA manda las fechas con -03:00 y la base las devuelve en UTC. Es el mismo instante, pero
        # como texto (el diff de la auditoría) es otro, y cada consulta parecía una modificación de tres fechas.
        sesion.refresh(fila)
        auditoria.registrar(sesion, usuario, "carta_porte", fila.id, AccionAuditoria.MODIFICACION,
                            antes=_sin_ruido(antes), despues=_sin_ruido(auditoria.instantanea(fila)))
    _guardar_pdf(sesion, fila, cpe.pdf)
    return fila


def _sin_ruido(instantanea: dict) -> dict:
    return {k: v for k, v in instantanea.items() if k not in RUIDO_DE_AUDITORIA}


def _exigir_orden(sesion: Session, orden_carga_id: int) -> None:
    if sesion.get(OrdenCarga, orden_carga_id) is None:
        raise Rechazo(404, f"no existe la orden {orden_carga_id}")


def traer(sesion: Session, usuario: dict | None, ctgs: list[int], cuit_representada: str,
          orden_carga_id: int | None = None) -> list[dict]:
    """Trae de ARCA y guarda cada CTG. Un CTG que falla no frena a los demás: el resultado dice cuál y por qué.

    Cada CTG se commitea por separado, así un error de ARCA en el quinto no se lleva los cuatro primeros.
    """
    unicos = list(dict.fromkeys(int(c) for c in ctgs))
    if not unicos:
        raise Rechazo(422, "Pegá al menos un CTG.")
    if len(unicos) > MAX_POR_LOTE:
        raise Rechazo(422, f"Hasta {MAX_POR_LOTE} CTG por vez.")
    if orden_carga_id is not None and len(unicos) > 1:
        raise Rechazo(422, "Una orden se vincula con una sola carta de porte a la vez.")
    cuit = _exigir_cuit(cuit_representada)
    amb = _ambiente_o_rechazo()
    ticket = _ticket(amb)
    resultados = []
    for ctg in unicos:
        try:
            cpe, _ = consultar(ctg, cuit, amb=amb, ticket=ticket)
            fila = guardar(sesion, usuario, cpe, cuit, amb, orden_carga_id)
            sesion.commit()
            resultados.append({"ctg": ctg, "id": fila.id, "error": None})
        except Rechazo as e:
            sesion.rollback()
            if e.status == 409:
                # Sin delegación falla igual para todos: no tiene sentido pedir los demás.
                raise
            resultados.append({"ctg": ctg, "id": None, "error": e.detalle})
    completar_catalogo(sesion, [r["id"] for r in resultados if r["id"] is not None], lambda _amb: ticket)
    return resultados


def actualizar(sesion: Session, usuario: dict | None, fila: CartaPorte, ticket: dict | None = None) -> CartaPorte:
    """Vuelve a consultar la CPE con el mismo CUIT y el mismo ambiente con que se trajo. **No commitea.**"""
    cpe, _ = consultar(fila.nro_ctg, fila.cuit_representada, amb=fila.ambiente,
                       ticket=ticket or _ticket(fila.ambiente))
    return guardar(sesion, usuario, cpe, fila.cuit_representada, fila.ambiente)


def abiertas(sesion: Session) -> list[CartaPorte]:
    """Las CPE que todavía pueden cambiar: sin kilos de descarga y en un estado que no es final."""
    return list(sesion.scalars(
        select(CartaPorte)
        .where(CartaPorte.peso_bruto_descarga.is_(None), CartaPorte.estado.not_in(ESTADOS_CERRADOS))
        .order_by(CartaPorte.id)))


def actualizar_abiertas(sesion: Session, usuario: dict | None, filas: list[CartaPorte] | None = None) -> dict:
    """Refresca las abiertas (o las `filas` que se pasen), cada una en su transacción. Devuelve el resumen.

    Una que falla no frena a las demás: ARCA caída, una delegación que falta, un corte de red o una respuesta rara se
    anotan en `errores` y se sigue. Si no se pudo ni sacar el ticket de un ambiente, no se vuelve a intentar para cada
    carta de ese ambiente: es el mismo error para todas.
    """
    filas = abiertas(sesion) if filas is None else filas
    # Los datos de cada una se toman antes: un `rollback` vence los objetos y releerlos fuera del `try` rompería todo.
    pendientes = [(f.id, f.nro_ctg, f.ambiente) for f in filas]
    tickets: dict[str, dict] = {}
    sin_ticket: dict[str, Rechazo] = {}
    actualizadas, errores = 0, []
    for id_, ctg, ambiente in pendientes:
        try:
            fila = sesion.get(CartaPorte, id_)
            if fila is None:  # la borraron mientras tanto
                continue
            if ambiente in sin_ticket:
                raise sin_ticket[ambiente]
            if ambiente not in tickets:
                try:
                    tickets[ambiente] = _ticket(ambiente)
                except Rechazo as e:
                    sin_ticket[ambiente] = e
                    raise
            actualizar(sesion, usuario, fila, tickets[ambiente])
            sesion.commit()
            actualizadas += 1
        except Rechazo as e:
            sesion.rollback()
            errores.append({"ctg": ctg, "error": e.detalle})
        except Exception as e:  # un corte de red o un XML raro en una carta no se lleva a las demás
            sesion.rollback()
            logger.exception("CPE %s: no se pudo actualizar", ctg)
            errores.append({"ctg": ctg, "error": f"no se pudo actualizar: {e}"})
    completar_catalogo(sesion, [i for i, _, _ in pendientes], lambda amb: tickets.get(amb) or _ticket(amb))
    return {"actualizadas": actualizadas, "errores": errores}


def completar_catalogo(sesion: Session, ids, ticket_de=None) -> int:
    """Pide a ARCA los nombres de grano, provincia y localidad que le falten a las cartas `ids` (ADR-051).

    Se llama después de traer o actualizar, cuando ya hay un ticket en la mano (`ticket_de(ambiente)`; sin él, el que
    está en la caché de disco del motor). Mejor esfuerzo: nunca levanta.
    """
    ids = [i for i in ids if i is not None]
    if not ids:
        return 0
    try:
        filas = list(sesion.scalars(select(CartaPorte).where(CartaPorte.id.in_(ids))))
        return catalogo_cpe.completar(sesion, filas, ticket_de or _ticket)
    except Exception:  # los nombres son un adorno: la carta ya quedó guardada
        sesion.rollback()
        logger.exception("CPE: no se completó el catálogo de códigos")
        return 0


def vincular_orden(sesion: Session, usuario: dict | None, fila: CartaPorte, orden_carga_id: int | None) -> None:
    """Vincula la CPE con una orden, o la desvincula con `None`. **No commitea.**"""
    if orden_carga_id is not None:
        _exigir_orden(sesion, orden_carga_id)
    antes = auditoria.instantanea(fila)
    fila.orden_carga_id = orden_carga_id
    fila.updated_by = _usuario_id(usuario)
    sesion.flush()
    auditoria.registrar(sesion, usuario, "carta_porte", fila.id, AccionAuditoria.MODIFICACION,
                        antes=antes, despues=fila)
