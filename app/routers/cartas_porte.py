"""Cartas de Porte Electrónicas: traerlas de ARCA por su CTG, verlas y vincularlas a una orden (ADR-036).

🔴 **`def` y no `async def`**, como `comprobantes.facturar`: la sesión y `openssl` (la firma del pedido de acceso a
WSAA) son sincrónicos y bloquearían el loop de uvicorn. Lo asincrónico va con `asyncio.run` en el hilo del pedido
(ver `servicios.cartas_porte`).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from libracore import arca_wscpe
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin, require_staff
from app.db import obtener_sesion
from app.models.cartas_porte import CartaPorte, CartaPortePdf
from app.schemas.cartas_porte import (
    CartaPorteOut,
    ConsultaIn,
    Parte,
    PlantillaPut,
    RepresentadosOut,
    ResultadoTraer,
    ResumenActualizar,
    TitularEdicion,
    TitularIn,
    TraerIn,
    VincularIn,
)
from app.servicios import cartas_porte as servicio
from app.servicios import emision_cpe, titulares_cpe

router = APIRouter(prefix="/api/cartas-porte", tags=["cartas-porte"],
                   dependencies=[Depends(require_staff)])


def _rechazo(e: servicio.Rechazo) -> HTTPException:
    return HTTPException(e.status, e.detalle)


def _neto(bruto, tara):
    return None if bruto is None or tara is None else bruto - tara


def _numero(sucursal, nro_orden) -> str:
    return "" if sucursal is None or nro_orden is None else f"{sucursal:05d}-{nro_orden:08d}"


def _partes(sesion: Session, cuits: dict[str, str | None]) -> dict[str, Parte]:
    nombres = servicio.nombres_por_cuit(sesion, cuits.values())
    return {k: Parte(cuit=c, nombre=nombres.get(c) if c else None) for k, c in cuits.items()}


def _de_fila(sesion: Session, fila: CartaPorte, tiene_pdf: bool) -> CartaPorteOut:
    partes = _partes(sesion, {
        "transportista": fila.cuit_transportista, "pagador_flete": fila.cuit_pagador_flete,
        "chofer": fila.cuit_chofer, "origen": fila.cuit_origen, "destino": fila.cuit_destino,
        "destinatario": fila.cuit_destinatario,
    })
    return CartaPorteOut(
        id=fila.id, nro_ctg=fila.nro_ctg, numero=_numero(fila.sucursal, fila.nro_orden), estado=fila.estado,
        estado_descripcion=arca_wscpe.ESTADOS.get(fila.estado, fila.estado),
        fecha_emision=fila.fecha_emision, fecha_vencimiento=fila.fecha_vencimiento, fecha_partida=fila.fecha_partida,
        fecha_inicio_estado=fila.fecha_inicio_estado,
        cuit_representada=fila.cuit_representada, ambiente=fila.ambiente, **partes,
        dominios=[d for d in (fila.dominios or "").split(",") if d],
        cod_grano=fila.cod_grano, cosecha=fila.cosecha,
        peso_bruto=fila.peso_bruto, peso_tara=fila.peso_tara, peso_neto=_neto(fila.peso_bruto, fila.peso_tara),
        peso_bruto_descarga=fila.peso_bruto_descarga, peso_tara_descarga=fila.peso_tara_descarga,
        peso_neto_descarga=_neto(fila.peso_bruto_descarga, fila.peso_tara_descarga),
        cod_provincia_origen=fila.cod_provincia_origen, cod_localidad_origen=fila.cod_localidad_origen,
        cod_provincia_destino=fila.cod_provincia_destino, cod_localidad_destino=fila.cod_localidad_destino,
        planta_destino=fila.planta_destino, km=fila.km, tarifa=fila.tarifa, tiene_pdf=tiene_pdf,
        tiene_descarga=fila.peso_bruto_descarga is not None, consultada_en=fila.consultada_en,
        orden_carga_id=fila.orden_carga_id, emitida=bool(fila.emitida),
    )


def _de_arca(sesion: Session, cpe: arca_wscpe.CartaDePorte, cuit: str, amb: str) -> CartaPorteOut:
    t, c = cpe.transporte, cpe.carga
    partes = _partes(sesion, {
        "transportista": t.cuit_transportista, "pagador_flete": t.cuit_pagador_flete, "chofer": t.cuit_chofer,
        "origen": cpe.origen.cuit, "destino": cpe.destino.cuit, "destinatario": cpe.destino.cuit_destinatario,
    })
    guardada = sesion.scalar(select(CartaPorte.id).where(CartaPorte.nro_ctg == cpe.nro_ctg))
    return CartaPorteOut(
        nro_ctg=cpe.nro_ctg, numero=cpe.numero, estado=cpe.estado, estado_descripcion=cpe.estado_descripcion,
        fecha_emision=cpe.fecha_emision, fecha_vencimiento=cpe.fecha_vencimiento,
        fecha_partida=t.fecha_hora_partida, fecha_inicio_estado=cpe.fecha_inicio_estado,
        cuit_representada=cuit, ambiente=amb, **partes,
        dominios=list(t.dominios), cod_grano=c.cod_grano, cosecha=c.cosecha,
        peso_bruto=c.peso_bruto, peso_tara=c.peso_tara, peso_neto=c.peso_neto,
        peso_bruto_descarga=c.peso_bruto_descarga, peso_tara_descarga=c.peso_tara_descarga,
        peso_neto_descarga=c.peso_neto_descarga,
        cod_provincia_origen=cpe.origen.cod_provincia, cod_localidad_origen=cpe.origen.cod_localidad,
        cod_provincia_destino=cpe.destino.cod_provincia, cod_localidad_destino=cpe.destino.cod_localidad,
        planta_destino=cpe.destino.planta, km=t.km, tarifa=t.tarifa, tiene_pdf=cpe.pdf is not None,
        tiene_descarga=cpe.tiene_descarga, guardada_id=guardada,
    )


def _con_pdf(sesion: Session, ids) -> set[int]:
    ids = list(ids)
    if not ids:
        return set()
    return set(sesion.scalars(select(CartaPortePdf.carta_porte_id).where(CartaPortePdf.carta_porte_id.in_(ids))))


def _traer(sesion: Session, id_: int) -> CartaPorte:
    fila = sesion.get(CartaPorte, id_)
    if fila is None:
        raise HTTPException(404, f"no existe la carta de porte {id_}")
    return fila


@router.get("/representados", response_model=RepresentadosOut)
def representados(sesion: Session = Depends(obtener_sesion)):
    """El ambiente y los CUIT por los que el certificado deja consultar (las delegaciones que ve ARCA)."""
    try:
        return servicio.representados(sesion)
    except servicio.Rechazo as e:
        raise _rechazo(e) from None


@router.post("/consultar", response_model=CartaPorteOut)
def consultar(datos: ConsultaIn, sesion: Session = Depends(obtener_sesion)):
    """La vista previa: lo que ARCA tiene de ese CTG, cruzado con los terceros cargados. **No guarda nada.**"""
    try:
        cpe, amb = servicio.consultar(datos.ctg, datos.cuit_representada)
    except servicio.Rechazo as e:
        raise _rechazo(e) from None
    return _de_arca(sesion, cpe, servicio.digitos(datos.cuit_representada), amb)


@router.post("", response_model=list[ResultadoTraer])
def traer(datos: TraerIn, sesion: Session = Depends(obtener_sesion), actual: dict = Depends(get_current_user)):
    """Trae de ARCA y guarda uno o varios CTG. Cada uno dice si quedó guardado o por qué no."""
    try:
        return servicio.traer(sesion, actual, datos.ctgs, datos.cuit_representada, datos.orden_carga_id)
    except servicio.Rechazo as e:
        raise _rechazo(e) from None


@router.get("", response_model=list[CartaPorteOut])
def listar(
    sesion: Session = Depends(obtener_sesion),
    abiertas: bool = Query(default=False, description="sólo las que todavía no tienen descarga ni estado final"),
    orden_carga_id: int | None = None,
    ctg: int | None = None,
):
    if abiertas:
        filas = servicio.abiertas(sesion)
    else:
        consulta = select(CartaPorte).order_by(CartaPorte.fecha_emision.desc().nulls_last(), CartaPorte.id.desc())
        filas = list(sesion.scalars(consulta))
    if orden_carga_id is not None:
        filas = [f for f in filas if f.orden_carga_id == orden_carga_id]
    if ctg is not None:
        filas = [f for f in filas if f.nro_ctg == ctg]
    con_pdf = _con_pdf(sesion, (f.id for f in filas))
    return [_de_fila(sesion, f, f.id in con_pdf) for f in filas]


@router.post("/actualizar-abiertas", response_model=ResumenActualizar)
def actualizar_abiertas(sesion: Session = Depends(obtener_sesion), actual: dict = Depends(get_current_user)):
    """Vuelve a consultar todas las abiertas, hasta que ARCA informe la descarga."""
    return servicio.actualizar_abiertas(sesion, actual)


# ── Emitir desde la orden (ADR-043) ─────────────────────────────────────────
# 🔑 Rutas de dos segmentos: una de uno (`/emision`) chocaría con `GET /{id_}` y daría 422.


class _HabilitadaIn(BaseModel):
    habilitada: bool


class _EmitirIn(BaseModel):
    orden_id: int
    #: Obligatorio en producción: «sí, es una Carta de Porte real».
    confirmo: bool = False
    datos: dict


class _AnularIn(BaseModel):
    observaciones: str | None = Field(default=None, max_length=100)


def _o_http(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except servicio.Rechazo as e:
        raise _rechazo(e) from None


@router.get("/emision/estado")
def estado_de_emision(sesion: Session = Depends(obtener_sesion)):
    """En qué ambiente se emitiría y si la emisión real está habilitada."""
    return emision_cpe.estado(sesion)


@router.put("/emision/habilitada", dependencies=[Depends(require_admin)])
def habilitar_emision(datos: _HabilitadaIn, sesion: Session = Depends(obtener_sesion),
                      actual: dict = Depends(get_current_user)):
    """Prende o apaga la emisión de Cartas de Porte **reales**. Sólo un administrador; queda en la auditoría."""
    return _o_http(emision_cpe.habilitar, sesion, actual, datos.habilitada)


@router.get("/emision/propuesta")
def propuesta_de_emision(orden_id: int, cuit_titular: str, sesion: Session = Depends(obtener_sesion)):
    """Lo que la orden y la plantilla del titular proponen para emitir, con lo que falta completar."""
    return _o_http(emision_cpe.propuesta, sesion, orden_id, cuit_titular)


@router.post("/emision/emitir", response_model=CartaPorteOut, status_code=201)
def emitir(datos: _EmitirIn, sesion: Session = Depends(obtener_sesion), actual: dict = Depends(get_current_user)):
    """Emite la Carta de Porte de la orden a nombre del titular, la guarda vinculada y devuelve su CTG y su PDF."""
    fila = _o_http(emision_cpe.emitir, sesion, actual, datos.orden_id, datos.datos, confirmo=datos.confirmo)
    return _de_fila(sesion, fila, bool(_con_pdf(sesion, [fila.id])))


@router.get("/catalogos/granos")
def catalogo_granos(cuit_titular: str):
    return [{"codigo": c, "nombre": n} for c, n in sorted(_o_http(emision_cpe.granos, cuit_titular).items(),
                                                          key=lambda x: x[1])]


@router.get("/catalogos/provincias")
def catalogo_provincias(cuit_titular: str):
    return [{"codigo": c, "nombre": n} for c, n in sorted(
        _o_http(emision_cpe.provincias_arca, cuit_titular).items(), key=lambda x: x[1])]


@router.get("/catalogos/localidades")
def catalogo_localidades(cuit_titular: str, provincia: int):
    return [{"codigo": c, "nombre": n} for c, n in sorted(
        _o_http(emision_cpe.localidades_arca, cuit_titular, provincia).items(), key=lambda x: x[1])]


@router.get("/catalogos/plantas")
def catalogo_plantas(cuit_titular: str, cuit: str):
    return _o_http(emision_cpe.plantas, cuit_titular, cuit)


# ── Titulares (ADR-044) ─────────────────────────────────────────────────────
# 🔑 Antes de `/{id_}`: `/titulares` es de un solo segmento y chocaría con `GET /{id_}` (422 por el entero).
# Ver es de staff; cargar, editar y borrar —y la plantilla— son de un administrador, como el resto de la emisión.


@router.get("/titulares")
def listar_titulares(sesion: Session = Depends(obtener_sesion)):
    """Los titulares con el estado de su delegación según el ticket de ARCA, y los CUIT delegados sin cargar.

    Si no se puede verificar (sin certificado, ARCA no contesta) igual contesta 200, con `verificado: false` y el
    motivo.
    """
    return titulares_cpe.listar(sesion)


@router.get("/titulares/instrucciones")
def instrucciones_de_delegacion():
    """El alias del computador fiscal y el CUIT del representante, del certificado cargado, para el titular."""
    return titulares_cpe.instrucciones()


@router.get("/titulares/de-tercero/{tercero_id}")
def titular_de_tercero(tercero_id: int, sesion: Session = Depends(obtener_sesion)):
    """El titular de esa entidad (para la ficha del cliente); `null` si no es titular."""
    return _o_http(titulares_cpe.de_tercero, sesion, tercero_id)


@router.post("/titulares", status_code=201, dependencies=[Depends(require_admin)])
def crear_titular(datos: TitularIn, sesion: Session = Depends(obtener_sesion),
                  actual: dict = Depends(get_current_user)):
    return titulares_cpe.como_fila(sesion, _o_http(titulares_cpe.crear, sesion, actual, datos))


@router.put("/titulares/{titular_id}", dependencies=[Depends(require_admin)])
def editar_titular(titular_id: int, datos: TitularEdicion, sesion: Session = Depends(obtener_sesion),
                   actual: dict = Depends(get_current_user)):
    return titulares_cpe.como_fila(sesion, _o_http(titulares_cpe.editar, sesion, actual, titular_id, datos))


@router.delete("/titulares/{titular_id}", status_code=204, dependencies=[Depends(require_admin)])
def borrar_titular(titular_id: int, sesion: Session = Depends(obtener_sesion),
                   actual: dict = Depends(get_current_user)):
    _o_http(titulares_cpe.borrar, sesion, actual, titular_id)
    return Response(status_code=204)


@router.get("/titulares/{titular_id}/plantilla")
def ver_plantilla(titular_id: int, sesion: Session = Depends(obtener_sesion)):
    """Los datos habituales del titular que usa «Emitir carta de porte»: `{datos, existe, actualizada}`."""
    return _o_http(titulares_cpe.plantilla, sesion, titular_id)


@router.put("/titulares/{titular_id}/plantilla", dependencies=[Depends(require_admin)])
def guardar_plantilla(titular_id: int, cuerpo: PlantillaPut, sesion: Session = Depends(obtener_sesion),
                      actual: dict = Depends(get_current_user)):
    return _o_http(titulares_cpe.guardar_plantilla, sesion, actual, titular_id, cuerpo.datos)


@router.delete("/titulares/{titular_id}/plantilla", status_code=204, dependencies=[Depends(require_admin)])
def borrar_plantilla(titular_id: int, sesion: Session = Depends(obtener_sesion),
                     actual: dict = Depends(get_current_user)):
    _o_http(titulares_cpe.borrar_plantilla, sesion, actual, titular_id)
    return Response(status_code=204)


@router.post("/{id_}/anular", response_model=CartaPorteOut, dependencies=[Depends(require_admin)])
def anular(id_: int, datos: _AnularIn, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    """Anula en ARCA una CPE emitida desde acá. Sólo un administrador."""
    fila = _traer(sesion, id_)
    fila = _o_http(emision_cpe.anular, sesion, actual, fila, datos.observaciones)
    return _de_fila(sesion, fila, bool(_con_pdf(sesion, [fila.id])))


@router.get("/{id_}/enlace")
def enlace(id_: int, request: Request, sesion: Session = Depends(obtener_sesion)):
    """Un enlace al PDF que se le puede pasar al chofer (no tiene usuario): firmado, vence a los 7 días."""
    fila = _traer(sesion, id_)
    if not _con_pdf(sesion, [fila.id]):
        raise HTTPException(404, "ARCA no devolvió el PDF de esta carta de porte")
    ruta, vence = _o_http(emision_cpe.enlace, fila.id)
    return {"url": str(request.base_url).rstrip("/") + "/api/publico" + ruta, "vence": vence}


@router.get("/{id_}", response_model=CartaPorteOut)
def ver(id_: int, sesion: Session = Depends(obtener_sesion)):
    fila = _traer(sesion, id_)
    return _de_fila(sesion, fila, bool(_con_pdf(sesion, [fila.id])))


@router.post("/{id_}/actualizar", response_model=CartaPorteOut)
def actualizar(id_: int, sesion: Session = Depends(obtener_sesion), actual: dict = Depends(get_current_user)):
    """Vuelve a consultar esta CPE con el mismo CUIT y ambiente con que se trajo."""
    fila = _traer(sesion, id_)
    try:
        servicio.actualizar(sesion, actual, fila)
    except servicio.Rechazo as e:
        sesion.rollback()
        raise _rechazo(e) from None
    sesion.commit()
    return _de_fila(sesion, fila, bool(_con_pdf(sesion, [fila.id])))


@router.put("/{id_}/orden", response_model=CartaPorteOut)
def vincular(id_: int, datos: VincularIn, sesion: Session = Depends(obtener_sesion),
             actual: dict = Depends(get_current_user)):
    """Vincula la CPE con una orden de carga (o la desvincula con `null`)."""
    fila = _traer(sesion, id_)
    try:
        servicio.vincular_orden(sesion, actual, fila, datos.orden_carga_id)
    except servicio.Rechazo as e:
        sesion.rollback()
        raise _rechazo(e) from None
    sesion.commit()
    return _de_fila(sesion, fila, bool(_con_pdf(sesion, [fila.id])))


@router.get("/{id_}/pdf")
def pdf(id_: int, sesion: Session = Depends(obtener_sesion)):
    """El PDF que devolvió ARCA, tal cual."""
    fila = _traer(sesion, id_)
    doc = sesion.get(CartaPortePdf, fila.id)
    if doc is None:
        raise HTTPException(404, "ARCA no devolvió el PDF de esta carta de porte")
    nombre = f"CPE-{fila.nro_ctg}.pdf"
    return Response(doc.contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}"'})


#: Sin sesión: el chofer abre el PDF desde el enlace que le mandan por WhatsApp. La firma es la autorización.
publico = APIRouter(prefix="/api/publico", tags=["cartas-porte"])


@publico.get("/cpe/{id_}/{vence}/{firma}.pdf")
def pdf_publico(id_: int, vence: int, firma: str, sesion: Session = Depends(obtener_sesion)):
    try:
        valido = emision_cpe.verificar_enlace(id_, vence, firma)
    except servicio.Rechazo:
        valido = False
    if not valido:
        raise HTTPException(404, "el enlace no existe o venció")
    doc = sesion.get(CartaPortePdf, id_)
    if doc is None:
        raise HTTPException(404, "el enlace no existe o venció")
    return Response(doc.contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="CPE-{id_}.pdf"', "Cache-Control": "no-store"})
