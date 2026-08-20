"""Las órdenes de carga: el núcleo del producto.

**Un solo listado con filtros, no once pantallas.** El legado tenía una pantalla
por combinación —por cliente, por fletero, por fecha, las pendientes, las de un
remito— y cada una era un PHP aparte, copiado del anterior. Acá es un endpoint
con filtros opcionales que se combinan entre sí.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.enums import AccionAuditoria, EstadoOrden
from app.models.operacion import OrdenCarga
from app.routers.maestros import traducir_integridad
from app.schemas.ordenes import OrdenIn, OrdenOut, calcular_importes
from app.servicios import auditoria
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
    razon_social_id: int | None = None,
    estado: EstadoOrden | None = None,
    # `None` es "las dos", distinto de `False`. Es el filtro que en el legado
    # era una pantalla propia: "facturar pendientes".
    facturada: bool | None = Query(default=None),
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
        (OrdenCarga.razon_social_id, razon_social_id),
        (OrdenCarga.estado, estado),
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
