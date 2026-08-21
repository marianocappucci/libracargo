"""Los dos asientos que deja un gasto de proveedor.

Mismo criterio que el asiento del fletero de una orden (`app/servicios/ordenes.py`)
y que la anulación de un comprobante: **nada de acá hace `commit`**. La llama
quien ya tiene la transacción abierta, para que el documento y sus dos asientos
entren juntos o no entre ninguno.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCuenta
from app.models.enums import RolCuenta
from app.models.operacion import GastoDeProveedor

CERO = Decimal("0.00")


def _concepto(gasto: GastoDeProveedor) -> str:
    return f"Gasto {gasto.comprobante}" if gasto.comprobante else "Gasto de proveedor"


def asientos_de(sesion: Session, gasto: GastoDeProveedor) -> list[MovimientoCuenta]:
    """**Todos** los movimientos que cuelgan de este gasto, en orden de alta.

    De un gasto vigente cuelgan dos —proveedor y fletero—; de uno anulado,
    cuatro, porque la anulación agrega las dos contrapartidas y no borra nada.

    Que devuelva todos alcanza porque las dos funciones que lo usan sólo corren
    sobre un gasto **vigente**: `sincronizar` la llama al alta y al editar, y
    editar un gasto anulado devuelve 409; `revertir` la llama al anular, que
    también está guardado por `anulado`. Si eso cambiara, acá hay que filtrar.
    """
    return list(sesion.scalars(
        select(MovimientoCuenta)
        .where(MovimientoCuenta.gasto_id == gasto.id)
        .order_by(MovimientoCuenta.id)
    ))


def sincronizar(sesion: Session, gasto: GastoDeProveedor) -> None:
    """Deja las dos cuentas diciendo lo que el gasto dice ahora.

    Los crea al dar de alta y los corrige al editar, **en el lugar**: una línea
    por cuenta y no dos, que es lo que hace el `UPDATE` de
    `modifica_ctacteprov.php` y lo que el cliente espera ver en la cuenta.
    """
    existentes = {m.rol: m for m in asientos_de(sesion, gasto)}

    proveedor = existentes.get(RolCuenta.PROVEEDOR)
    if proveedor is None:
        sesion.add(MovimientoCuenta(
            fecha=gasto.fecha, tercero_id=gasto.proveedor_id, rol=RolCuenta.PROVEEDOR,
            concepto=_concepto(gasto), descripcion=gasto.descripcion,
            debe=gasto.importe, haber=CERO, gasto_id=gasto.id,
        ))
    else:
        proveedor.fecha = gasto.fecha
        proveedor.tercero_id = gasto.proveedor_id
        proveedor.concepto = _concepto(gasto)
        proveedor.descripcion = gasto.descripcion
        proveedor.debe = gasto.importe

    fletero = existentes.get(RolCuenta.FLETERO)
    if fletero is None:
        sesion.add(MovimientoCuenta(
            fecha=gasto.fecha, tercero_id=gasto.fletero_id, rol=RolCuenta.FLETERO,
            concepto=_concepto(gasto), descripcion=gasto.descripcion,
            debe=CERO, haber=gasto.importe, gasto_id=gasto.id,
        ))
    else:
        fletero.fecha = gasto.fecha
        fletero.tercero_id = gasto.fletero_id
        fletero.concepto = _concepto(gasto)
        fletero.descripcion = gasto.descripcion
        fletero.haber = gasto.importe


def revertir(sesion: Session, gasto: GastoDeProveedor) -> None:
    """Contraasientos por anulación, con la fecha del gasto.

    Anular **no borra**: quedan las dos líneas originales y sus dos
    contrapartidas. Y la fecha es la del gasto y no la de hoy, por lo mismo que
    en la anulación de un comprobante — con la fecha de hoy, la cuenta mostraría
    entre el cargo y su reversión una deuda que ningún total del período
    reconoce.
    """
    for movimiento in asientos_de(sesion, gasto):
        # Se invierten las columnas: el debe del proveedor se cancela con un
        # haber, y el haber del fletero con un debe.
        sesion.add(MovimientoCuenta(
            fecha=gasto.fecha, tercero_id=movimiento.tercero_id, rol=movimiento.rol,
            concepto=f"Anulación gasto {gasto.id}", descripcion=movimiento.descripcion,
            debe=movimiento.haber, haber=movimiento.debe, gasto_id=gasto.id,
        ))
