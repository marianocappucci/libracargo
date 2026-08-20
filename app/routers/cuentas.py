"""Caja y cuentas corrientes.

Un movimiento de caja genera su contrapartida en la cuenta corriente **dentro de
la misma transacción**. En el legado eran dos `INSERT` sueltos: si el segundo
fallaba, el primero ya había quedado grabado y la caja decía una cosa y la
cuenta del cliente otra, sin nada que lo delatara.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.cuentas import MovimientoCaja, MovimientoCuenta
from app.models.enums import AccionAuditoria, RolCuenta, TipoMovimientoCaja
from app.routers.maestros import traducir_integridad
from app.schemas.cuentas import (
    FilaDeCuenta,
    MovimientoCajaIn,
    MovimientoCajaOut,
    ResumenDeCuenta,
)
from app.servicios import auditoria
from app.servicios.cuentas import movimientos_con_saldo, saldo, saldo_recorriendo

router = APIRouter(prefix="/api", tags=["cuentas"], dependencies=[Depends(require_staff)])


@router.get("/cuentas/{rol}/{tercero_id}", response_model=ResumenDeCuenta)
def cuenta_corriente(
    rol: RolCuenta,
    tercero_id: int,
    sesion: Session = Depends(obtener_sesion),
    hasta: date | None = Query(default=None, description="corte, inclusive"),
):
    """La cuenta con su saldo, calculado por **los dos caminos**.

    Devolver los dos números y si coinciden es el criterio de F4 hecho dato: no
    hace falta abrir la base para saber si el saldo depende de dónde se sumó.
    """
    por_sql = saldo(sesion, tercero_id, rol, hasta)
    recorriendo = saldo_recorriendo(sesion, tercero_id, rol, hasta)
    filas = movimientos_con_saldo(sesion, tercero_id, rol, hasta)
    return ResumenDeCuenta(
        tercero_id=tercero_id, rol=rol,
        saldo=por_sql, saldo_recorriendo=recorriendo,
        coinciden=por_sql == recorriendo,
        movimientos=[FilaDeCuenta(movimiento=m, saldo=s) for m, s in filas],
    )


@router.get("/caja", response_model=list[MovimientoCajaOut])
def listar_caja(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = None,
    hasta: date | None = None,
    tercero_id: int | None = None,
    tipo: TipoMovimientoCaja | None = None,
    limite: int = Query(default=200, ge=1, le=1000),
):
    consulta = select(MovimientoCaja)
    if desde is not None:
        consulta = consulta.where(MovimientoCaja.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(MovimientoCaja.fecha <= hasta)
    if tercero_id is not None:
        consulta = consulta.where(MovimientoCaja.tercero_id == tercero_id)
    if tipo is not None:
        consulta = consulta.where(MovimientoCaja.tipo == tipo)
    consulta = consulta.order_by(
        MovimientoCaja.fecha.desc(), MovimientoCaja.id.desc()
    ).limit(limite)
    return list(sesion.scalars(consulta))


@router.post("/caja", response_model=MovimientoCajaOut, status_code=201)
def registrar_caja(datos: MovimientoCajaIn, sesion: Session = Depends(obtener_sesion),
                   actual: dict = Depends(get_current_user)):
    """Registra el movimiento y su contrapartida, o no registra ninguno.

    La contrapartida sólo existe si hay tercero: un gasto general de la agencia
    no mueve la cuenta de nadie. Pero si hay tercero **tiene que haber rol**,
    porque un mismo tercero puede ser cliente y fletero a la vez y si no no se
    sabe cuál de sus cuentas se está moviendo.
    """
    if datos.tercero_id is not None and datos.rol is None:
        raise HTTPException(422, "falta el rol: no se sabe a que cuenta del tercero va")
    if datos.tercero_id is None and datos.rol is not None:
        raise HTTPException(422, "hay rol pero no hay tercero")

    movimiento = MovimientoCaja(
        fecha=datos.fecha, tipo=datos.tipo, concepto=datos.concepto,
        descripcion=datos.descripcion, tercero_id=datos.tercero_id,
        importe=datos.importe, medio_pago=datos.medio_pago, recibo=datos.recibo,
    )
    sesion.add(movimiento)
    try:
        # `flush` y no `commit`: necesito el id para la contrapartida, pero la
        # transaccion tiene que seguir abierta. Con dos commits, un fallo en el
        # segundo deja el primero grabado -- el defecto exacto del legado.
        sesion.flush()
        if datos.tercero_id is not None:
            # Un ingreso baja lo que el tercero debe; un egreso lo sube. Vale
            # para las tres cuentas, porque el signo lo da el movimiento y no
            # el rol.
            es_ingreso = datos.tipo is TipoMovimientoCaja.INGRESO
            sesion.add(MovimientoCuenta(
                fecha=datos.fecha,
                tercero_id=datos.tercero_id,
                rol=datos.rol,
                concepto=datos.concepto,
                descripcion=datos.descripcion,
                debe=0 if es_ingreso else datos.importe,
                haber=datos.importe if es_ingreso else 0,
                movimiento_caja_id=movimiento.id,
            ))
        auditoria.registrar(sesion, actual, "movimiento_caja", movimiento.id,
                            AccionAuditoria.ALTA, despues=movimiento)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(movimiento)
    return movimiento
