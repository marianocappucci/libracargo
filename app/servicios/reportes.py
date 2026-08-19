"""Los números del negocio, agregados en la base.

Todo lo que se suma acá se suma **en PostgreSQL**, no trayendo filas y sumándolas
en Python: sobre las 22.645 filas de cuenta corriente de Suitrans la diferencia
es entre una consulta y cuatro megabytes de JSON.

> 🔑 **Un reporte que no dice sobre qué está calculado no sirve.** Cada uno
> devuelve el rango que efectivamente usó y la cantidad de filas que agregó, para
> que la pantalla —y el papel— puedan imprimirlo al lado del número. Un total sin
> su universo es un número que nadie puede verificar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCaja, MovimientoCuenta
from app.models.enums import EstadoOrden, RolCuenta, TipoMovimientoCaja
from app.models.maestros import RazonSocial, Tercero
from app.models.operacion import Comprobante, OrdenCarga

CERO = Decimal("0.00")


def _entre(consulta, columna, desde: date | None, hasta: date | None):
    if desde is not None:
        consulta = consulta.where(columna >= desde)
    if hasta is not None:
        consulta = consulta.where(columna <= hasta)
    return consulta


def _suma(sesion: Session, consulta) -> Decimal:
    return Decimal(sesion.scalar(consulta) or 0).quantize(CERO)


def resumen(sesion: Session, desde: date | None, hasta: date | None) -> dict:
    """El período de un vistazo: qué se movió, qué se facturó y qué entró.

    Las órdenes **anuladas quedan afuera de los importes** pero se cuentan
    aparte: esconderlas haría que la cantidad de órdenes del reporte no fuera la
    del listado, y esa diferencia sin explicación es peor que el dato.
    """
    base = _entre(select(OrdenCarga), OrdenCarga.fecha, desde, hasta)
    vigentes = base.where(OrdenCarga.estado != EstadoOrden.ANULADA)

    def sobre(columna, consulta=None):
        c = (consulta if consulta is not None else vigentes).with_only_columns(
            func.coalesce(func.sum(columna), 0))
        return _suma(sesion, c)

    contar = lambda c: sesion.scalar(c.with_only_columns(func.count()))  # noqa: E731

    caja = _entre(select(MovimientoCaja), MovimientoCaja.fecha, desde, hasta)
    ingresos = caja.where(MovimientoCaja.tipo == TipoMovimientoCaja.INGRESO)
    egresos = caja.where(MovimientoCaja.tipo == TipoMovimientoCaja.EGRESO)

    comprobantes = _entre(
        select(Comprobante).where(Comprobante.anulado.is_(False)),
        Comprobante.fecha, desde, hasta)

    return {
        "desde": desde, "hasta": hasta,
        "ordenes": contar(vigentes),
        "ordenes_anuladas": contar(base.where(OrdenCarga.estado == EstadoOrden.ANULADA)),
        "ordenes_pendientes": contar(vigentes.where(OrdenCarga.estado == EstadoOrden.PENDIENTE)),
        "tarifa": sobre(OrdenCarga.tarifa),
        "iva": sobre(OrdenCarga.iva),
        "total": sobre(OrdenCarga.total),
        "comision": sobre(OrdenCarga.comision),
        "comprobantes": contar(comprobantes),
        "facturado": sobre(Comprobante.total, comprobantes),
        "movimientos_caja": contar(caja),
        "cobrado": sobre(MovimientoCaja.importe, ingresos),
        "pagado": sobre(MovimientoCaja.importe, egresos),
    }


def por_tercero(sesion: Session, rol: RolCuenta, desde: date | None,
                hasta: date | None, limite: int) -> list[dict]:
    """Ranking de clientes o de fleteros, con su saldo al día de hoy.

    🔑 **El saldo NO se acota al rango.** Lo facturado en el período y lo que el
    tercero debe son dos preguntas distintas: un saldo recortado a los últimos
    tres meses no es el saldo de nadie. La pantalla lo dice, y el reporte devuelve
    las dos cosas en columnas separadas.
    """
    if rol is RolCuenta.CLIENTE:
        columna, condicion = OrdenCarga.cliente_id, Tercero.es_cliente
    else:
        columna, condicion = OrdenCarga.fletero_id, Tercero.es_fletero

    movidas = _entre(
        select(columna.label("tercero_id"),
               func.count(OrdenCarga.id).label("ordenes"),
               func.coalesce(func.sum(OrdenCarga.total), 0).label("facturado"),
               func.coalesce(func.sum(OrdenCarga.comision), 0).label("comision"))
        .where(OrdenCarga.estado != EstadoOrden.ANULADA, columna.is_not(None)),
        OrdenCarga.fecha, desde, hasta).group_by(columna).subquery()

    saldos = (
        select(MovimientoCuenta.tercero_id.label("tercero_id"),
               (func.coalesce(func.sum(MovimientoCuenta.debe), 0)
                - func.coalesce(func.sum(MovimientoCuenta.haber), 0)).label("saldo"))
        .where(MovimientoCuenta.rol == rol)
        .group_by(MovimientoCuenta.tercero_id).subquery())

    filas = sesion.execute(
        select(Tercero.id, Tercero.razon_social,
               func.coalesce(movidas.c.ordenes, 0),
               func.coalesce(movidas.c.facturado, 0),
               func.coalesce(movidas.c.comision, 0),
               func.coalesce(saldos.c.saldo, 0))
        .select_from(Tercero)
        .outerjoin(movidas, movidas.c.tercero_id == Tercero.id)
        .outerjoin(saldos, saldos.c.tercero_id == Tercero.id)
        .where(condicion.is_(True))
        # Las que no movieron nada en el período y tampoco deben nada no entran:
        # son 276 terceros y el papel se llenaría de ceros.
        .where((func.coalesce(movidas.c.ordenes, 0) > 0)
               | (func.coalesce(saldos.c.saldo, 0) != 0))
        .order_by(func.coalesce(movidas.c.facturado, 0).desc(),
                  func.abs(func.coalesce(saldos.c.saldo, 0)).desc())
        .limit(limite)).fetchall()

    return [{"tercero_id": f[0], "tercero": f[1], "ordenes": f[2],
             "facturado": Decimal(f[3]).quantize(CERO),
             "comision": Decimal(f[4]).quantize(CERO),
             "saldo": Decimal(f[5]).quantize(CERO)} for f in filas]


def saldos(sesion: Session, rol: RolCuenta | None, incluir_en_cero: bool) -> list[dict]:
    """Todas las cuentas corrientes de una vez.

    En el sistema viejo esto no existía: había que abrir la cuenta de cada
    tercero, de a uno, para saber quién debe. Con 267 cuentas eso es una tarde.
    """
    consulta = (
        select(MovimientoCuenta.tercero_id, MovimientoCuenta.rol, Tercero.razon_social,
               func.count(MovimientoCuenta.id),
               func.max(MovimientoCuenta.fecha),
               func.coalesce(func.sum(MovimientoCuenta.debe), 0)
               - func.coalesce(func.sum(MovimientoCuenta.haber), 0))
        .join(Tercero, Tercero.id == MovimientoCuenta.tercero_id)
        .group_by(MovimientoCuenta.tercero_id, MovimientoCuenta.rol, Tercero.razon_social))
    if rol is not None:
        consulta = consulta.where(MovimientoCuenta.rol == rol)
    if not incluir_en_cero:
        consulta = consulta.having(
            func.coalesce(func.sum(MovimientoCuenta.debe), 0)
            - func.coalesce(func.sum(MovimientoCuenta.haber), 0) != 0)
    filas = sesion.execute(consulta.order_by(
        func.abs(func.coalesce(func.sum(MovimientoCuenta.debe), 0)
                 - func.coalesce(func.sum(MovimientoCuenta.haber), 0)).desc())).fetchall()
    return [{"tercero_id": f[0], "rol": f[1], "tercero": f[2], "movimientos": f[3],
             "ultimo_movimiento": f[4], "saldo": Decimal(f[5]).quantize(CERO)}
            for f in filas]


def caja(sesion: Session, desde: date | None, hasta: date | None) -> list[dict]:
    """La caja del período, abierta por tipo y medio de pago."""
    filas = sesion.execute(_entre(
        select(MovimientoCaja.tipo, MovimientoCaja.medio_pago,
               func.count(MovimientoCaja.id),
               func.coalesce(func.sum(MovimientoCaja.importe), 0)),
        MovimientoCaja.fecha, desde, hasta)
        .group_by(MovimientoCaja.tipo, MovimientoCaja.medio_pago)
        .order_by(MovimientoCaja.tipo, MovimientoCaja.medio_pago)).fetchall()
    return [{"tipo": f[0], "medio_pago": f[1], "movimientos": f[2],
             "importe": Decimal(f[3]).quantize(CERO)} for f in filas]


def por_razon_social(sesion: Session, desde: date | None, hasta: date | None) -> list[dict]:
    """Lo facturado por cada razón social propia, con su nombre.

    Es la misma cuenta que el gate de F5, pero para leer y no para controlar: acá
    interesa el número, no si los dos lados coinciden.
    """
    filas = sesion.execute(_entre(
        select(Comprobante.razon_social_id, RazonSocial.nombre,
               func.count(Comprobante.id),
               func.coalesce(func.sum(Comprobante.neto), 0),
               func.coalesce(func.sum(Comprobante.iva), 0),
               func.coalesce(func.sum(Comprobante.total), 0))
        .join(RazonSocial, RazonSocial.id == Comprobante.razon_social_id)
        .where(Comprobante.anulado.is_(False)),
        Comprobante.fecha, desde, hasta)
        .group_by(Comprobante.razon_social_id, RazonSocial.nombre)
        .order_by(func.coalesce(func.sum(Comprobante.total), 0).desc())).fetchall()
    return [{"razon_social_id": f[0], "razon_social": f[1], "comprobantes": f[2],
             "neto": Decimal(f[3]).quantize(CERO), "iva": Decimal(f[4]).quantize(CERO),
             "total": Decimal(f[5]).quantize(CERO)} for f in filas]


def por_ruta(sesion: Session, desde: date | None, hasta: date | None,
             limite: int) -> list[dict]:
    """Las rutas más transitadas: origen → destino, con lo que dejaron.

    El legado no podía contestar esto: `origen` y `destino` eran dos tablas con
    los mismos nombres repetidos, y la cantidad era texto libre.
    """
    from sqlalchemy.orm import aliased

    from app.models.maestros import Localidad

    origen = aliased(Localidad)
    destino = aliased(Localidad)
    filas = sesion.execute(_entre(
        select(origen.nombre, destino.nombre,
               func.count(OrdenCarga.id),
               func.coalesce(func.sum(OrdenCarga.total), 0),
               func.coalesce(func.sum(OrdenCarga.comision), 0),
               func.coalesce(func.sum(OrdenCarga.cantidad), 0))
        .join(origen, origen.id == OrdenCarga.origen_id)
        .join(destino, destino.id == OrdenCarga.destino_id)
        .where(OrdenCarga.estado != EstadoOrden.ANULADA),
        OrdenCarga.fecha, desde, hasta)
        .group_by(origen.nombre, destino.nombre)
        .order_by(func.count(OrdenCarga.id).desc())
        .limit(limite)).fetchall()
    return [{"origen": f[0], "destino": f[1], "ordenes": f[2],
             "total": Decimal(f[3]).quantize(CERO),
             "comision": Decimal(f[4]).quantize(CERO),
             "cantidad": Decimal(f[5] or 0)} for f in filas]
