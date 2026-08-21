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
from app.models.cuentas import MovimientoCaja
from app.models.enums import AccionAuditoria, RolCuenta, TipoMovimientoCaja
from app.routers.maestros import traducir_integridad
from app.schemas.cuentas import (
    FilaDeCuenta,
    MovimientoCajaIn,
    MovimientoCajaOut,
    ResumenDeCuenta,
)
from app.servicios import auditoria
from app.servicios.caja import revertir, sincronizar_contrapartida
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


def _validar_par(datos: MovimientoCajaIn) -> None:
    """Tercero y rol van juntos, o no va ninguno.

    Un gasto general de la agencia no mueve la cuenta de nadie. Pero si hay
    tercero **tiene que haber rol**, porque un mismo tercero puede ser cliente y
    fletero a la vez y si no, no se sabe cuál de sus cuentas se está moviendo.
    """
    if datos.tercero_id is not None and datos.rol is None:
        raise HTTPException(422, "falta el rol: no se sabe a que cuenta del tercero va")
    if datos.tercero_id is None and datos.rol is not None:
        raise HTTPException(422, "hay rol pero no hay tercero")


def _traer_caja(sesion: Session, id_: int) -> MovimientoCaja:
    movimiento = sesion.get(MovimientoCaja, id_)
    if movimiento is None:
        raise HTTPException(404, f"no existe el movimiento de caja {id_}")
    return movimiento


@router.post("/caja", response_model=MovimientoCajaOut, status_code=201)
def registrar_caja(datos: MovimientoCajaIn, sesion: Session = Depends(obtener_sesion),
                   actual: dict = Depends(get_current_user)):
    """Registra el movimiento y su contrapartida, o no registra ninguno."""
    _validar_par(datos)
    movimiento = MovimientoCaja(
        fecha=datos.fecha, tipo=datos.tipo, concepto=datos.concepto,
        descripcion=datos.descripcion, tercero_id=datos.tercero_id,
        importe=datos.importe, medio_pago=datos.medio_pago, recibo=datos.recibo,
    )
    sesion.add(movimiento)
    try:
        # `flush` y no `commit`: hace falta el id para la contrapartida, pero la
        # transaccion tiene que seguir abierta. Con dos commits, un fallo en el
        # segundo deja el primero grabado -- el defecto exacto del legado.
        sesion.flush()
        sincronizar_contrapartida(sesion, movimiento, datos.rol)
        auditoria.registrar(sesion, actual, "movimiento_caja", movimiento.id,
                            AccionAuditoria.ALTA, despues=movimiento)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(movimiento)
    return movimiento


@router.put("/caja/{id_}", response_model=MovimientoCajaOut)
def editar_caja(id_: int, datos: MovimientoCajaIn,
                sesion: Session = Depends(obtener_sesion),
                actual: dict = Depends(get_current_user)):
    """Corrige el movimiento **y su contrapartida**, en el lugar.

    Una línea por cuenta y no dos, que es lo que hace el `UPDATE` de
    `modifica_novedad.php` y lo que el cliente espera ver. Cambiar el tercero, el
    rol o el importe mueve el asiento con el movimiento; sacarle el tercero lo
    borra.
    """
    _validar_par(datos)
    movimiento = _traer_caja(sesion, id_)
    if movimiento.anulado:
        raise HTTPException(409, "el movimiento está anulado: no se puede modificar")
    antes = auditoria.instantanea(movimiento)
    for campo in ("fecha", "tipo", "concepto", "descripcion", "tercero_id",
                  "importe", "medio_pago", "recibo"):
        setattr(movimiento, campo, getattr(datos, campo))
    try:
        sincronizar_contrapartida(sesion, movimiento, datos.rol)
        auditoria.registrar(sesion, actual, "movimiento_caja", movimiento.id,
                            AccionAuditoria.MODIFICACION, antes=antes, despues=movimiento)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(movimiento)
    return movimiento


@router.delete("/caja/{id_}", response_model=MovimientoCajaOut)
def anular_caja(id_: int, sesion: Session = Depends(obtener_sesion),
                actual: dict = Depends(get_current_user)):
    """Anular, no borrar.

    🔴 `elimina_novedad.php` hacía tres `DELETE` sueltos —la cuenta del cliente,
    la del fletero, la del proveedor— y después borraba la novedad. Un cobro
    anulado desaparecía sin dejar rastro y el número de recibo quedaba con un
    hueco que nadie podía explicar. Acá el movimiento queda, deja de contar en
    los totales y su asiento se revierte con una contrapartida.
    """
    movimiento = _traer_caja(sesion, id_)
    if movimiento.anulado:
        raise HTTPException(409, "el movimiento ya está anulado")
    antes = auditoria.instantanea(movimiento)
    # Antes de marcarlo: `revertir` lee la contrapartida vigente.
    revertir(sesion, movimiento)
    movimiento.anulado = True
    auditoria.registrar(sesion, actual, "movimiento_caja", movimiento.id,
                        AccionAuditoria.BAJA, antes=antes, despues=movimiento)
    sesion.commit()
    sesion.refresh(movimiento)
    return movimiento
