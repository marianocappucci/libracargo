"""Cartas de Porte Electrónicas: traerlas de ARCA por su CTG, verlas y vincularlas a una orden (ADR-036).

🔴 **`def` y no `async def`**, como `comprobantes.facturar`: la sesión y `openssl` (la firma del pedido de acceso a
WSAA) son sincrónicos y bloquearían el loop de uvicorn. Lo asincrónico va con `asyncio.run` en el hilo del pedido
(ver `servicios.cartas_porte`).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from libracore import arca_wscpe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.cartas_porte import CartaPorte, CartaPortePdf
from app.schemas.cartas_porte import (
    CartaPorteOut,
    ConsultaIn,
    Parte,
    RepresentadosOut,
    ResultadoTraer,
    ResumenActualizar,
    TraerIn,
    VincularIn,
)
from app.servicios import cartas_porte as servicio

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
        orden_carga_id=fila.orden_carga_id,
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
        fecha_partida=t.fecha_hora_partida, cuit_representada=cuit, ambiente=amb, **partes,
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
