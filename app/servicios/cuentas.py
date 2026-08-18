"""Saldos de cuenta corriente, por dos caminos distintos a propósito.

El criterio de terminado de F4 en el ROADMAP es que **el saldo de un tercero dé
igual calculado de dos maneras**. Por eso hay dos funciones y no una:

- `saldo()` agrega en la **base**, con un `SUM`.
- `saldo_recorriendo()` trae los movimientos y los acumula en **Python**.

No es duplicación: es el control. Si las dos coinciden, el saldo no depende de
dónde se hizo la cuenta; si difieren, hay un movimiento que una de las dos ve y
la otra no —un filtro de más, una fila fuera de rango, un `Decimal` que se
convirtió a float en el camino—. El legado no tenía forma de hacer esta
comparación: los importes estaban en `float` de precisión simple y no había una
sola clave foránea que garantizara qué movimiento pertenecía a qué cuenta.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCuenta
from app.models.enums import RolCuenta

CERO = Decimal("0.00")


def _base(tercero_id: int, rol: RolCuenta, hasta: date | None = None):
    consulta = select(MovimientoCuenta).where(
        MovimientoCuenta.tercero_id == tercero_id,
        MovimientoCuenta.rol == rol,
    )
    if hasta is not None:
        consulta = consulta.where(MovimientoCuenta.fecha <= hasta)
    return consulta


def saldo(sesion: Session, tercero_id: int, rol: RolCuenta,
          hasta: date | None = None) -> Decimal:
    """El saldo agregado por la base: `SUM(debe) - SUM(haber)`.

    `coalesce` sobre cada suma: sin movimientos, `SUM` devuelve `NULL` y la
    resta daría `None` en vez de cero — y un saldo ausente no es lo mismo que un
    saldo en cero para quien lo lee.
    """
    consulta = select(
        func.coalesce(func.sum(MovimientoCuenta.debe), 0)
        - func.coalesce(func.sum(MovimientoCuenta.haber), 0)
    ).where(
        MovimientoCuenta.tercero_id == tercero_id,
        MovimientoCuenta.rol == rol,
    )
    if hasta is not None:
        consulta = consulta.where(MovimientoCuenta.fecha <= hasta)
    return Decimal(sesion.scalar(consulta) or 0).quantize(CERO)


def movimientos_con_saldo(
    sesion: Session, tercero_id: int, rol: RolCuenta, hasta: date | None = None
) -> list[tuple[MovimientoCuenta, Decimal]]:
    """Cada movimiento con el saldo **acumulado hasta esa fila**.

    El orden es `(fecha, id)`. El `id` no es decoración: dos movimientos del
    mismo día sin desempate salen en un orden que la base puede cambiar entre
    consultas, y entonces el saldo corrido de la fila del medio cambia solo —
    la misma cuenta impresa dos veces daría dos papeles distintos.
    """
    filas = list(sesion.scalars(
        _base(tercero_id, rol, hasta).order_by(MovimientoCuenta.fecha, MovimientoCuenta.id)
    ))
    acumulado = CERO
    salida = []
    for m in filas:
        acumulado = (acumulado + m.debe - m.haber).quantize(CERO)
        salida.append((m, acumulado))
    return salida


def saldo_recorriendo(sesion: Session, tercero_id: int, rol: RolCuenta,
                      hasta: date | None = None) -> Decimal:
    """El mismo saldo, acumulado en Python fila por fila.

    Es el segundo camino del criterio de F4. Se calcula con `Decimal` de punta a
    punta: pasar por `float` acá reintroduciría exactamente el defecto que el
    producto viene a reparar.
    """
    filas = movimientos_con_saldo(sesion, tercero_id, rol, hasta)
    return filas[-1][1] if filas else CERO
