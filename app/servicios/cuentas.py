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

from libracore.db import libro_de_terceros as libro
from libracore.db.migraciones import conexion_libracore
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCuenta, MovimientoCuentaCargo
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


# ── Escribir la cuenta: lo hace el motor ────────────────────────────────────
#
# Desde la revisión `0017` cada asiento es una fila de `cc_asientos`, el libro de
# cuenta corriente de terceros de LibraCore (ADR-026 del motor, ADR-031 de acá).
# Este producto no lo escribe con su ORM: asienta, corrige, borra y revierte **el
# motor**, con la conexión de la sesión (`conn=`), así que el asiento sigue
# entrando y saliendo junto con su documento —el comprobante, el cobro, el gasto—.
# Lo único que escribe el ORM es `movimientos_cuenta_cargo`.


def _conexion_del_motor(sesion: Session):
    sesion.flush()
    return conexion_libracore(sesion.connection())


def asentar(sesion: Session, *, fecha: date, tercero_id: int, rol: RolCuenta, concepto: str,
            descripcion: str | None = None, debe: Decimal = CERO, haber: Decimal = CERO,
            comprobante_id: int | None = None, orden_id: int | None = None,
            movimiento_caja_id: int | None = None, gasto_id: int | None = None) -> MovimientoCuenta:
    """Escribe un asiento en el libro del motor y su fila propia. No hace `commit`."""
    conn = _conexion_del_motor(sesion)
    asiento_id = libro.asentar(
        tercero_id, RolCuenta(rol).value, fecha.isoformat(), concepto, debe=debe, haber=haber,
        descripcion=descripcion, factura_id=comprobante_id, conn=conn)
    sesion.add(MovimientoCuentaCargo(asiento_id=asiento_id, orden_id=orden_id,
                                     movimiento_caja_id=movimiento_caja_id, gasto_id=gasto_id))
    sesion.flush()
    return sesion.get(MovimientoCuenta, asiento_id)


def corregir(sesion: Session, movimiento: MovimientoCuenta, **campos) -> MovimientoCuenta:
    """Cambia el asiento en el lugar: lo que se hace al editar el documento que lo originó."""
    traducidos = {}
    for clave, valor in campos.items():
        if clave == "fecha":
            valor = valor.isoformat()
        elif clave == "rol":
            valor = RolCuenta(valor).value
        traducidos[clave] = valor
    libro.corregir(movimiento.id, conn=_conexion_del_motor(sesion), **traducidos)
    sesion.expire(movimiento)
    return movimiento


def borrar(sesion: Session, movimiento: MovimientoCuenta) -> None:
    """Saca el asiento cuando el documento editado deja de mover la cuenta. No es anular."""
    conn = _conexion_del_motor(sesion)
    cargo = sesion.get(MovimientoCuentaCargo, movimiento.id)
    sesion.expunge(movimiento)
    if cargo is not None:
        sesion.delete(cargo)
        sesion.flush()
    libro.borrar(movimiento.id, conn=conn)


def contraasentar(sesion: Session, movimiento: MovimientoCuenta, *, concepto: str,
                  fecha: date | None = None) -> MovimientoCuenta:
    """Revierte un asiento con otro de columnas invertidas, con la misma fila propia."""
    conn = _conexion_del_motor(sesion)
    original = sesion.get(MovimientoCuentaCargo, movimiento.id)
    asiento_id = libro.contraasentar(
        movimiento.id, fecha=fecha.isoformat() if fecha else None, concepto=concepto, conn=conn)
    sesion.add(MovimientoCuentaCargo(
        asiento_id=asiento_id,
        orden_id=original.orden_id if original else None,
        movimiento_caja_id=original.movimiento_caja_id if original else None,
        gasto_id=original.gasto_id if original else None,
    ))
    sesion.flush()
    return sesion.get(MovimientoCuenta, asiento_id)
