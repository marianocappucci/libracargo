"""Gastos de proveedor: el bloque que el sistema viejo llamaba COMPROBANTES PROVEEDORES.

El nombre engañaba. Medido sobre los 3.347 registros del legado: **2.799 son
gastos**, los 2.799 están imputados a un fletero y **ninguno tiene número de
comprobante**; el tipo dice "Remito" en 2.806. Los 539 restantes son pagos, y
esos ya se hacen por caja.

O sea: esto no es una factura de compra, es **lo que el proveedor entrega y se
le descuenta al fletero**. Un gasto mueve dos cuentas —proveedor al debe,
fletero al haber— y las mueve **en una transacción**, que es lo que el legado no
hacía: eran dos `INSERT` sueltos y si el segundo fallaba el primero quedaba.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.enums import AccionAuditoria
from app.models.operacion import GastoDeProveedor
from app.routers.maestros import traducir_integridad
from app.schemas.gastos import GastoIn, GastoOut
from app.servicios import auditoria
from app.servicios.gastos import revertir, sincronizar

router = APIRouter(prefix="/api/gastos", tags=["gastos"],
                   dependencies=[Depends(require_staff)])


def _traer(sesion: Session, id_: int) -> GastoDeProveedor:
    gasto = sesion.get(GastoDeProveedor, id_)
    if gasto is None:
        raise HTTPException(404, f"no existe el gasto {id_}")
    return gasto


@router.get("", response_model=list[GastoOut])
def listar(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = None,
    hasta: date | None = None,
    proveedor_id: int | None = None,
    fletero_id: int | None = None,
    # `None` es "todos", distinto de `False`. Esconder los anulados por omisión
    # haría que un importe que no aparece en la cuenta no tenga explicación en
    # pantalla — mismo criterio que comprobantes.
    anulado: bool | None = Query(default=None),
    limite: int = Query(default=200, ge=1, le=1000),
    desplazamiento: int = Query(default=0, ge=0),
):
    consulta = select(GastoDeProveedor)
    for columna, valor in (
        (GastoDeProveedor.proveedor_id, proveedor_id),
        (GastoDeProveedor.fletero_id, fletero_id),
        (GastoDeProveedor.anulado, anulado),
    ):
        if valor is not None:
            consulta = consulta.where(columna == valor)
    if desde is not None:
        consulta = consulta.where(GastoDeProveedor.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(GastoDeProveedor.fecha <= hasta)
    consulta = (
        consulta.order_by(GastoDeProveedor.fecha.desc(), GastoDeProveedor.id.desc())
        .limit(limite).offset(desplazamiento)
    )
    return list(sesion.scalars(consulta))


@router.get("/{id_}", response_model=GastoOut)
def traer(id_: int, sesion: Session = Depends(obtener_sesion)):
    return _traer(sesion, id_)


@router.post("", response_model=GastoOut, status_code=201)
def crear(datos: GastoIn, sesion: Session = Depends(obtener_sesion),
          actual: dict = Depends(get_current_user)):
    gasto = GastoDeProveedor(**datos.model_dump())
    sesion.add(gasto)
    try:
        # `flush` y no `commit`: hacen falta el id para los dos asientos, y que
        # la transacción siga abierta para que entren con el documento.
        sesion.flush()
        sincronizar(sesion, gasto)
        auditoria.registrar(sesion, actual, "gasto_de_proveedor", gasto.id,
                            AccionAuditoria.ALTA, despues=gasto)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(gasto)
    return gasto


@router.put("/{id_}", response_model=GastoOut)
def editar(id_: int, datos: GastoIn, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    gasto = _traer(sesion, id_)
    if gasto.anulado:
        raise HTTPException(409, "el gasto está anulado: no se puede modificar")
    antes = auditoria.instantanea(gasto)
    for campo, valor in datos.model_dump().items():
        setattr(gasto, campo, valor)
    try:
        # Los dos asientos siguen al documento: si cambió el importe, el
        # proveedor y el fletero tienen que decir lo que el gasto dice ahora.
        sincronizar(sesion, gasto)
        auditoria.registrar(sesion, actual, "gasto_de_proveedor", gasto.id,
                            AccionAuditoria.MODIFICACION, antes=antes, despues=gasto)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(gasto)
    return gasto


@router.delete("/{id_}", response_model=GastoOut)
def anular(id_: int, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    """Anular, no borrar.

    El gasto es el origen de dos asientos de cuenta corriente. Borrarlo los
    dejaría sin explicación, que es exactamente lo que tiene el legado por no
    haber declarado una sola clave foránea.
    """
    gasto = _traer(sesion, id_)
    if gasto.anulado:
        raise HTTPException(409, "el gasto ya está anulado")
    antes = auditoria.instantanea(gasto)
    # Antes de marcarlo: `revertir` lee los asientos vigentes.
    revertir(sesion, gasto)
    gasto.anulado = True
    auditoria.registrar(sesion, actual, "gasto_de_proveedor", gasto.id,
                        AccionAuditoria.BAJA, antes=antes, despues=gasto)
    sesion.commit()
    sesion.refresh(gasto)
    return gasto
