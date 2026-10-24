"""La caja en el motor, y la contrapartida de un movimiento y su reversión.

Un cobro o un pago mueven **dos cosas**: la caja y —si hay tercero— su cuenta
corriente. Acá está el par, en un solo lugar, para que el alta, la edición y la
anulación no puedan divergir. **Nada de esto hace `commit`**: lo llama quien ya
tiene la transacción abierta.

**La caja es la del motor** (ADR-055). Cada movimiento es una fila de
`caja_movimientos` de LibraCore más su fila propia en `movimientos_caja_cargo`, con
el mismo id; el alta y la anulación las hace `libracore.db.caja` con la conexión de la
sesión, así que corren los **ganchos de caja** (ADR-076 del motor) dentro de la misma
transacción. Fuera de un nodo no hay ganchos; el nodo los enchufa en `GANCHOS_DE_CAJA`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from libracore.db import caja as caja_del_motor
from libracore.db.migraciones import conexion_libracore
from libracore.ganchos_de_caja import SIN_GANCHOS, GanchosDeCaja
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.cuentas import (
    MovimientoCaja,
    MovimientoCajaCargo,
    MovimientoCuenta,
    caja_movimientos,
)
from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja
from app.servicios import cuentas

CERO = Decimal("0.00")

#: Los ganchos de caja de este producto: lo que sube la caja de un nodo al central. Vacíos hasta que
#: `app/offline.py` los arme con el outbox. Se leen **en cada llamada**, no al importar: quien los cambia
#: (el nodo al arrancar, un test) no depende del orden de los imports.
GANCHOS_DE_CAJA: GanchosDeCaja = SIN_GANCHOS


def _conexion_del_motor(sesion: Session):
    sesion.flush()
    return conexion_libracore(sesion.connection())


def registrar(sesion: Session, *, fecha: date, tipo: TipoMovimientoCaja, concepto: str, importe: Decimal,
              medio_pago: MedioPago = MedioPago.EFECTIVO, descripcion: str | None = None,
              tercero_id: int | None = None, recibo: str | None = None,
              usuario_id: int | None = None) -> MovimientoCaja:
    """Anota el movimiento en la caja del motor y su fila propia, con el mismo id. No hace `commit`.

    🔑 **`referencia` va vacía, a propósito.** `create_caja_movimiento` toma la referencia como clave de
    idempotencia y devuelve el movimiento que ya existía si se repite: un recibo repetido o mal tipeado haría
    desaparecer un cobro sin avisar. El recibo vive en la fila propia.
    """
    if importe <= 0:
        # La `CHECK` de la tabla vieja (`importe > 0`) ya no tiene dónde vivir: el importe es del motor.
        raise ValueError("el importe de un movimiento de caja tiene que ser mayor que cero")
    conn = _conexion_del_motor(sesion)
    id_ = caja_del_motor.create_caja_movimiento(
        fecha.isoformat(), tipo.value, concepto, importe, usuario_id=usuario_id, medio_pago=medio_pago.value,
        conn=conn, ganchos=GANCHOS_DE_CAJA)
    sesion.add(MovimientoCajaCargo(movimiento_id=id_, descripcion=descripcion, tercero_id=tercero_id,
                                   recibo=recibo))
    sesion.flush()
    return sesion.get(MovimientoCaja, id_)


def viene_de_un_nodo(sesion: Session, movimiento: MovimientoCaja) -> bool:
    """Si el movimiento subió de un nodo (`origen` de la caja del motor, ADR-076): el nodo es su dueño."""
    return sesion.scalar(
        select(caja_movimientos.c.origen).where(caja_movimientos.c.id == movimiento.id)) is not None


def corregir(sesion: Session, movimiento: MovimientoCaja, *, fecha: date, tipo: TipoMovimientoCaja,
             concepto: str, importe: Decimal, medio_pago: MedioPago, descripcion: str | None,
             tercero_id: int | None, recibo: str | None) -> MovimientoCaja:
    """Corrige el movimiento en el lugar: la fila del motor y la propia. No hace `commit`.

    Es la edición del **central**. En un nodo corregir es anular y cargar de nuevo: el motor no tiene un gancho
    de «movimiento modificado», así que una edición no subiría. Ver ADR-055.
    """
    _conexion_del_motor(sesion)
    sesion.execute(update(caja_movimientos).where(caja_movimientos.c.id == movimiento.id).values(
        fecha=fecha, tipo=tipo, concepto=concepto, monto=importe, medio_pago=medio_pago))
    propia = sesion.get(MovimientoCajaCargo, movimiento.id)
    propia.descripcion, propia.tercero_id, propia.recibo = descripcion, tercero_id, recibo
    sesion.flush()
    sesion.expire(movimiento)
    return movimiento


def anular(sesion: Session, movimiento: MovimientoCaja) -> MovimientoCaja:
    """Revierte la contrapartida y marca el movimiento anulado en el motor. No hace `commit`.

    La fila **queda**: sale de los totales y la lista la sigue mostrando. Corre `al_anular_movimiento`.
    """
    # Antes de marcarlo: `revertir` lee la contrapartida vigente.
    revertir(sesion, movimiento)
    caja_del_motor.anular_caja_movimiento(
        movimiento.id, conn=_conexion_del_motor(sesion), ganchos=GANCHOS_DE_CAJA)
    sesion.expire(movimiento)
    return movimiento


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
            cuentas.borrar(sesion, existente)
        return

    al_haber = va_al_haber(rol, movimiento.tipo)
    debe = CERO if al_haber else movimiento.importe
    haber = movimiento.importe if al_haber else CERO

    if existente is None:
        cuentas.asentar(
            sesion,
            fecha=movimiento.fecha, tercero_id=movimiento.tercero_id, rol=rol,
            concepto=movimiento.concepto, descripcion=movimiento.descripcion,
            debe=debe, haber=haber, movimiento_caja_id=movimiento.id,
        )
        return

    cuentas.corregir(sesion, existente, fecha=movimiento.fecha, tercero_id=movimiento.tercero_id,
                     rol=rol, concepto=movimiento.concepto, descripcion=movimiento.descripcion,
                     debe=debe, haber=haber)


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
    cuentas.asentar(
        sesion,
        fecha=movimiento.fecha, tercero_id=existente.tercero_id, rol=existente.rol,
        concepto=f"Anulación {movimiento.concepto}"[:120],
        descripcion=existente.descripcion,
        # Invertidas: lo que sumó al debe se cancela con un haber, y al revés.
        debe=existente.haber, haber=existente.debe,
        movimiento_caja_id=movimiento.id,
    )
