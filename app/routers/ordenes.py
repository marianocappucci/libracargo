"""Las órdenes de carga: el núcleo del producto.

**Un solo listado con filtros, no once pantallas.** El legado tenía una pantalla
por combinación —por cliente, por fletero, por fecha, las pendientes, las de un
remito— y cada una era un PHP aparte, copiado del anterior. Acá es un endpoint
con filtros opcionales que se combinan entre sí.
"""

from datetime import date
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import String, cast, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.enums import AccionAuditoria, EstadoOrden, EtapaOrden
from app.models.operacion import AdjuntoDeOrden, OrdenCarga, PreFacturaOrden
from app.routers.maestros import traducir_integridad
from app.schemas.ordenes import AdjuntoOut, EtapaIn, OrdenIn, OrdenOut, calcular_importes
from app.servicios import adjuntos, auditoria, pre_facturas
from app.servicios.ordenes import (
    revertir_comision,
    sincronizar_comision,
)

router = APIRouter(prefix="/api/ordenes", tags=["ordenes"],
                   dependencies=[Depends(require_staff)])


def _traer(sesion: Session, id_: int) -> OrdenCarga:
    orden = sesion.get(OrdenCarga, id_)
    if orden is None:
        raise HTTPException(404, f"no existe la orden {id_}")
    return orden


def _exigir_libre(sesion: Session, orden: OrdenCarga) -> None:
    """Una orden en una pre factura abierta no se edita ni se anula: la pre factura quedaría diciendo otra cosa."""
    try:
        pre_facturas.exigir_orden_libre(sesion, orden)
    except pre_facturas.Rechazo as e:
        raise HTTPException(e.status, e.detalle) from None


def _aplicar_importes(orden: OrdenCarga, datos: OrdenIn) -> None:
    orden.iva, orden.total = calcular_importes(datos.tarifa, datos.alicuota_iva)


@router.get("", response_model=list[OrdenOut])
def listar(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = Query(default=None, description="fecha desde, inclusive"),
    hasta: date | None = Query(default=None, description="fecha hasta, inclusive"),
    cliente_id: int | None = None,
    fletero_id: int | None = None,
    chofer_id: int | None = None,
    vehiculo_id: int | None = None,
    origen_id: int | None = None,
    destino_id: int | None = None,
    tipo_carga_id: int | None = None,
    estado: EstadoOrden | None = None,
    etapa: EtapaOrden | None = None,
    # `None` es "las dos", distinto de `False`. Es el filtro que en el legado
    # era una pantalla propia: "facturar pendientes".
    facturada: bool | None = Query(default=None),
    # Reservada en una pre factura abierta (ADR-032). `reservada=false` son las que se pueden incluir en
    # una pre factura nueva; `pre_factura_id`, las de esa pre factura.
    reservada: bool | None = Query(default=None),
    pre_factura_id: int | None = None,
    q: str | None = Query(default=None, description="busca en remito y observaciones"),
    limite: int = Query(default=200, ge=1, le=1000),
    desplazamiento: int = Query(default=0, ge=0),
):
    consulta = select(OrdenCarga)
    for columna, valor in (
        (OrdenCarga.cliente_id, cliente_id),
        (OrdenCarga.fletero_id, fletero_id),
        (OrdenCarga.chofer_id, chofer_id),
        (OrdenCarga.vehiculo_id, vehiculo_id),
        (OrdenCarga.origen_id, origen_id),
        (OrdenCarga.destino_id, destino_id),
        (OrdenCarga.tipo_carga_id, tipo_carga_id),
        (OrdenCarga.estado, estado),
        (OrdenCarga.etapa, etapa),
    ):
        if valor is not None:
            consulta = consulta.where(columna == valor)
    if desde is not None:
        consulta = consulta.where(OrdenCarga.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(OrdenCarga.fecha <= hasta)
    if facturada is not None:
        # Se pregunta por el comprobante y no por el estado: son lo mismo —hay
        # un CHECK que lo garantiza— pero el comprobante es el dato duro.
        consulta = consulta.where(
            OrdenCarga.comprobante_id.is_not(None) if facturada
            else OrdenCarga.comprobante_id.is_(None)
        )
    if reservada is not None:
        reservadas = select(PreFacturaOrden.orden_id)
        consulta = consulta.where(
            OrdenCarga.id.in_(reservadas) if reservada else OrdenCarga.id.not_in(reservadas))
    if pre_factura_id is not None:
        consulta = consulta.where(OrdenCarga.id.in_(
            select(PreFacturaOrden.orden_id).where(PreFacturaOrden.pre_factura_id == pre_factura_id)))
    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(or_(
            cast(OrdenCarga.remito, String).ilike(patron),
            cast(OrdenCarga.observaciones, String).ilike(patron),
        ))
    # Más nueva primero, con el id como desempate: dos órdenes del mismo día sin
    # un segundo criterio salen en un orden que la base puede cambiar entre
    # consultas, y una lista que se reordena sola no se puede revisar.
    consulta = (
        consulta.order_by(OrdenCarga.fecha.desc(), OrdenCarga.id.desc())
        .limit(limite).offset(desplazamiento)
    )
    return list(sesion.scalars(consulta))


@router.get("/{id_}", response_model=OrdenOut)
def traer(id_: int, sesion: Session = Depends(obtener_sesion)):
    return _traer(sesion, id_)


@router.post("", response_model=OrdenOut, status_code=201)
def crear(datos: OrdenIn, sesion: Session = Depends(obtener_sesion),
          actual: dict = Depends(get_current_user)):
    orden = OrdenCarga(**datos.model_dump())
    # Nace pendiente y sin comprobante: facturar es F5, y el CHECK de la base no
    # deja que una orden diga "facturada" sin uno.
    orden.estado = EstadoOrden.PENDIENTE
    orden.comprobante_id = None
    _aplicar_importes(orden, datos)
    sesion.add(orden)
    try:
        # `flush` y no `commit`: hace falta el id para el asiento del fletero,
        # pero la transacción tiene que seguir abierta. En el legado el alta
        # eran tres `INSERT` sueltos y si el tercero fallaba, la orden ya
        # estaba grabada sin su contrapartida.
        sesion.flush()
        sincronizar_comision(sesion, orden)
        auditoria.registrar(sesion, actual, "orden_carga", orden.id,
                            AccionAuditoria.ALTA, despues=orden)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(orden)
    return orden


@router.put("/{id_}", response_model=OrdenOut)
def editar(id_: int, datos: OrdenIn, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    orden = _traer(sesion, id_)
    if orden.estado is EstadoOrden.FACTURADA:
        # Ya salió en un comprobante: cambiarle la tarifa deja el comprobante
        # diciendo un importe que la orden ya no dice.
        raise HTTPException(409, "la orden esta facturada: no se puede modificar")
    if orden.estado is EstadoOrden.ANULADA:
        raise HTTPException(409, "la orden esta anulada: no se puede modificar")
    _exigir_libre(sesion, orden)
    antes = auditoria.instantanea(orden)
    for campo, valor in datos.model_dump().items():
        setattr(orden, campo, valor)
    _aplicar_importes(orden, datos)
    try:
        # Cambió la comisión, o el fletero: la cuenta del fletero tiene que
        # decir lo que la orden dice ahora, o queda diciendo lo de antes sin
        # que nada lo delate.
        sincronizar_comision(sesion, orden)
        auditoria.registrar(sesion, actual, "orden_carga", orden.id,
                            AccionAuditoria.MODIFICACION, antes=antes, despues=orden)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(orden)
    return orden


@router.delete("/{id_}", response_model=OrdenOut)
def anular(id_: int, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    """Anular, no borrar.

    La orden es la contrapartida de los movimientos de cuenta del cliente y del
    fletero. Borrarla deja esos movimientos sin origen, que es exactamente lo
    que tiene el legado por no haber declarado una sola clave foránea.
    """
    orden = _traer(sesion, id_)
    if orden.estado is EstadoOrden.FACTURADA:
        raise HTTPException(
            409, "la orden esta facturada: primero hay que anular el comprobante"
        )
    _exigir_libre(sesion, orden)
    antes = auditoria.instantanea(orden)
    # El contraasiento se arma ANTES de marcarla anulada: lee el cargo vigente,
    # y `sincronizar_comision` no vuelve a crearlo porque una orden anulada no
    # le debe nada a nadie.
    revertir_comision(sesion, orden)
    orden.estado = EstadoOrden.ANULADA
    auditoria.registrar(sesion, actual, "orden_carga", orden.id,
                        AccionAuditoria.BAJA, antes=antes, despues=orden)
    sesion.commit()
    sesion.refresh(orden)
    return orden


@router.get("/{id_}/importes")
def auditar_importes(
    id_: int, sesion: Session = Depends(obtener_sesion)
) -> dict[str, Decimal]:
    """Lo guardado contra lo que da la cuenta.

    Existe para las órdenes **migradas**: si no coinciden, el importe viene del
    legado —donde el dinero estaba en `float` de precisión simple— y no de esta
    cuenta. Es el insumo del gate de saldos de F6.
    """
    orden = _traer(sesion, id_)
    iva, total = calcular_importes(orden.tarifa, orden.alicuota_iva)
    return {"iva_calculado": iva, "total_calculado": total,
            "iva_guardado": orden.iva, "total_guardado": orden.total}


# ── Etapa ───────────────────────────────────────────────────────────────────


@router.put("/{id_}/etapa", response_model=OrdenOut)
def cambiar_etapa(id_: int, datos: EtapaIn, sesion: Session = Depends(obtener_sesion),
                  actual: dict = Depends(get_current_user)):
    """Mueve la orden a otra etapa del viaje (ADR-037).

    Aparte del `PUT` de la orden porque **también vale para una facturada**: la etapa es operativa y no cambia
    nada del comprobante. Por ahora sólo informa: se puede ir a cualquier etapa, para adelante o para atrás.
    Una anulada no se mueve.
    """
    orden = _traer(sesion, id_)
    if orden.estado is EstadoOrden.ANULADA:
        raise HTTPException(409, "la orden esta anulada: no cambia de etapa")
    antes = auditoria.instantanea(orden)
    orden.etapa = datos.etapa
    auditoria.registrar(sesion, actual, "orden_carga", orden.id,
                        AccionAuditoria.MODIFICACION, antes=antes, despues=orden)
    sesion.commit()
    sesion.refresh(orden)
    return orden


# ── Adjuntos ────────────────────────────────────────────────────────────────


def _adjunto(sesion: Session, orden_id: int, adjunto_id: int) -> AdjuntoDeOrden:
    adj = sesion.get(AdjuntoDeOrden, adjunto_id)
    if adj is None or adj.orden_id != orden_id:
        raise HTTPException(404, f"la orden {orden_id} no tiene el adjunto {adjunto_id}")
    return adj


def _usuario_id(actual: dict | None) -> int | None:
    valor = str((actual or {}).get("id", ""))
    return int(valor) if valor.isdigit() else None


@router.get("/{id_}/adjuntos", response_model=list[AdjuntoOut])
def listar_adjuntos(id_: int, sesion: Session = Depends(obtener_sesion)):
    _traer(sesion, id_)
    return list(sesion.scalars(
        select(AdjuntoDeOrden).where(AdjuntoDeOrden.orden_id == id_).order_by(AdjuntoDeOrden.id)))


@router.post("/{id_}/adjuntos", response_model=AdjuntoOut, status_code=201)
def subir_adjunto(id_: int, archivo: UploadFile = File(...), sesion: Session = Depends(obtener_sesion),
                  actual: dict = Depends(get_current_user)):
    """Adjunta un archivo (la foto del ticket, un PDF). **También a una orden facturada**: el ticket suele
    llegar después. El tipo sale del contenido, no del navegador; tope de 10 MB."""
    orden = _traer(sesion, id_)
    if orden.estado is EstadoOrden.ANULADA:
        raise HTTPException(409, "la orden esta anulada: no se le adjuntan archivos")
    contenido = archivo.file.read(adjuntos.TAMANIO_MAXIMO + 1)
    try:
        tipo = adjuntos.tipo_por_contenido(contenido)
    except adjuntos.AdjuntoInvalido as e:
        raise HTTPException(422, str(e)) from None
    adj = AdjuntoDeOrden(orden_id=orden.id, nombre=adjuntos.nombre_seguro(archivo.filename),
                         tipo_contenido=tipo, tamanio=len(contenido), contenido=contenido,
                         created_by=_usuario_id(actual))
    sesion.add(adj)
    sesion.flush()
    auditoria.registrar(sesion, actual, "orden_adjunto", adj.id, AccionAuditoria.ALTA,
                        despues={"orden_id": orden.id, "nombre": adj.nombre, "tipo": tipo, "tamanio": adj.tamanio})
    sesion.commit()
    sesion.refresh(adj)
    return adj


@router.get("/{id_}/adjuntos/{adjunto_id}")
def descargar_adjunto(id_: int, adjunto_id: int, sesion: Session = Depends(obtener_sesion)):
    adj = _adjunto(sesion, id_, adjunto_id)
    return Response(adj.contenido, media_type=adj.tipo_contenido, headers={
        # `filename*` en UTF-8 para los acentos y un `filename` ASCII de respaldo: un nombre con «ñ» o un emoji
        # en el `filename` solo rompe el encabezado.
        "Content-Disposition": (f'inline; filename="{adj.nombre.encode("ascii", "replace").decode()}"; '
                                f"filename*=UTF-8''{quote(adj.nombre)}"),
        "X-Content-Type-Options": "nosniff",
    })


@router.delete("/{id_}/adjuntos/{adjunto_id}", status_code=204)
def borrar_adjunto(id_: int, adjunto_id: int, sesion: Session = Depends(obtener_sesion),
                   actual: dict = Depends(get_current_user)):
    adj = _adjunto(sesion, id_, adjunto_id)
    auditoria.registrar(sesion, actual, "orden_adjunto", adj.id, AccionAuditoria.BAJA,
                        antes={"orden_id": adj.orden_id, "nombre": adj.nombre, "tipo": adj.tipo_contenido,
                               "tamanio": adj.tamanio})
    sesion.delete(adj)
    sesion.commit()
    return Response(status_code=204)
