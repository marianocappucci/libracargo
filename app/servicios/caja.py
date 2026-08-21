"""La contrapartida de un movimiento de caja, y su reversión.

Un cobro o un pago mueven **dos cosas**: la caja y —si hay tercero— su cuenta
corriente. Acá está el par, en un solo lugar, para que el alta, la edición y la
anulación no puedan divergir. **Nada de esto hace `commit`**: lo llama quien ya
tiene la transacción abierta.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCaja, MovimientoCuenta
from app.models.enums import RolCuenta, TipoMovimientoCaja

CERO = Decimal("0.00")


def va_al_haber(rol: RolCuenta, tipo: TipoMovimientoCaja) -> bool:
    """A qué columna va el asiento. Depende del **par** (rol, tipo).

    | Cuenta | Ingreso | Egreso |
    |---|---|---|
    | Cliente | cobranza → `haber` | devolución → `debe` |
    | Fletero / proveedor | devolución → `debe` | pago → `haber` |

    Es la convención del legado y la de los 22.645 movimientos migrados: el
    cargo va a `debe` y el pago a `haber` en las tres cuentas. Lo que cambia es
    cuál de los dos es un ingreso, porque para un cliente el saldo positivo es
    lo que **debe** y para un fletero es lo que se le **debe**.

    Vivía suelta adentro del alta, y por eso la edición y la anulación no tenían
    de dónde sacarla sin repetirla.
    """
    cobranza = rol is RolCuenta.CLIENTE
    return (tipo is TipoMovimientoCaja.INGRESO) == cobranza


def contrapartida_de(sesion: Session, movimiento: MovimientoCaja) -> MovimientoCuenta | None:
    """El asiento de cuenta corriente de este movimiento, si tiene.

    Devuelve el **primero**: de un movimiento anulado cuelgan dos —el original y
    su reversión—, y quien llama a esto es la edición, que sólo corre sobre
    movimientos vigentes.
    """
    return sesion.scalar(
        select(MovimientoCuenta)
        .where(MovimientoCuenta.movimiento_caja_id == movimiento.id)
        .order_by(MovimientoCuenta.id)
    )


def sincronizar_contrapartida(sesion: Session, movimiento: MovimientoCaja,
                              rol: RolCuenta | None) -> None:
    """Deja la cuenta del tercero diciendo lo que el movimiento dice ahora.

    Crea, corrige o saca el asiento. Un movimiento **sin tercero** —un gasto
    general de la agencia— no mueve la cuenta de nadie, y si un movimiento que
    la tenía deja de tenerla, el asiento se va con ella.
    """
    existente = contrapartida_de(sesion, movimiento)

    if movimiento.tercero_id is None or rol is None:
        if existente is not None:
            sesion.delete(existente)
        return

    al_haber = va_al_haber(rol, movimiento.tipo)
    debe = CERO if al_haber else movimiento.importe
    haber = movimiento.importe if al_haber else CERO

    if existente is None:
        sesion.add(MovimientoCuenta(
            fecha=movimiento.fecha, tercero_id=movimiento.tercero_id, rol=rol,
            concepto=movimiento.concepto, descripcion=movimiento.descripcion,
            debe=debe, haber=haber, movimiento_caja_id=movimiento.id,
        ))
        return

    existente.fecha = movimiento.fecha
    existente.tercero_id = movimiento.tercero_id
    existente.rol = rol
    existente.concepto = movimiento.concepto
    existente.descripcion = movimiento.descripcion
    existente.debe = debe
    existente.haber = haber


def revertir(sesion: Session, movimiento: MovimientoCaja) -> None:
    """Contraasiento por anulación, con la fecha del movimiento.

    Anular **no borra** — ni el movimiento de caja ni su asiento—. El legado
    hacía tres `DELETE` sueltos (`elimina_novedad.php`) y un cobro anulado
    desaparecía sin dejar rastro: el número de recibo quedaba con un hueco que
    nadie podía explicar.
    """
    existente = contrapartida_de(sesion, movimiento)
    if existente is None:
        return
    sesion.add(MovimientoCuenta(
        fecha=movimiento.fecha, tercero_id=existente.tercero_id, rol=existente.rol,
        concepto=f"Anulación {movimiento.concepto}"[:120],
        descripcion=existente.descripcion,
        # Invertidas: lo que sumó al debe se cancela con un haber, y al revés.
        debe=existente.haber, haber=existente.debe,
        movimiento_caja_id=movimiento.id,
    ))
