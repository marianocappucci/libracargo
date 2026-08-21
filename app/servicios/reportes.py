"""Los números del negocio, agregados en la base.

Todo lo que se suma acá se suma **en PostgreSQL**, no trayendo filas y sumándolas
en Python: sobre las 22.645 filas de cuenta corriente de Suitrans la diferencia
es entre una consulta y cuatro megabytes de JSON.

> 🔑 **Cada reporte se parametriza por lo suyo, no sólo por fecha.** El resumen y
> las rutas aceptan cliente y fletero, la caja acepta tercero y medio de pago,
> los rankings aceptan un tercero puntual. Un filtro que acota **el mismo**
> reporte —y no un reporte distinto— hace que el número de la lista sea el mismo
> que el de la ficha.

> 🔑 **Y un reporte que no dice sobre qué está calculado no sirve.** El resumen
> devuelve el rango que efectivamente usó, para que la pantalla y el papel puedan
> imprimirlo al lado del número.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models.cuentas import MovimientoCaja, MovimientoCuenta
from app.models.enums import EstadoOrden, MedioPago, RolCuenta, TipoMovimientoCaja
from app.models.maestros import Localidad, RazonSocial, Tercero
from app.models.operacion import Comprobante, OrdenCarga

CERO = Decimal("0.00")


def _entre(consulta, columna, desde: date | None, hasta: date | None):
    if desde is not None:
        consulta = consulta.where(columna >= desde)
    if hasta is not None:
        consulta = consulta.where(columna <= hasta)
    return consulta


def _iguales(consulta, pares):
    """Aplica `columna == valor` para cada par cuyo valor no sea `None`.

    `None` es "sin filtrar" y **no** es lo mismo que un valor vacío: un
    `cliente_id=0` sería un id, no una ausencia.
    """
    for columna, valor in pares:
        if valor is not None:
            consulta = consulta.where(columna == valor)
    return consulta


def _suma(sesion: Session, consulta) -> Decimal:
    return Decimal(sesion.scalar(consulta) or 0).quantize(CERO)


def resumen(sesion: Session, desde: date | None, hasta: date | None,
            cliente_id: int | None = None, fletero_id: int | None = None) -> dict:
    """El período de un vistazo: qué se movió, qué se facturó y qué entró.

    Las órdenes **anuladas quedan afuera de los importes** pero se cuentan
    aparte: esconderlas haría que la cantidad de órdenes del reporte no fuera la
    del listado, y esa diferencia sin explicación es peor que el dato.
    """
    base = _iguales(_entre(select(OrdenCarga), OrdenCarga.fecha, desde, hasta),
                    [(OrdenCarga.cliente_id, cliente_id), (OrdenCarga.fletero_id, fletero_id)])
    vigentes = base.where(OrdenCarga.estado != EstadoOrden.ANULADA)

    def contar(consulta, columna):
        # 🔴 `func.count()` **sin columna** pierde el `FROM` cuando la consulta
        # no tiene ningún `WHERE` que la ancle, y devuelve 1 en vez de fallar.
        # Con filtro contaba bien y sin filtro contaba 1 (ver PR #19).
        return sesion.scalar(consulta.with_only_columns(func.count(columna)))

    def sobre(columna, consulta=None):
        c = (consulta if consulta is not None else vigentes)
        return _suma(sesion, c.with_only_columns(func.coalesce(func.sum(columna), 0)))

    # La caja se acota por tercero, no por "cliente" o "fletero": un movimiento
    # de caja apunta a un tercero y el rol lo dice la contrapartida.
    tercero = cliente_id if cliente_id is not None else fletero_id
    # 🔴 Sin el filtro de anulados, un cobro que se dio de baja sigue contando
    # en los ingresos del periodo y en el conteo de movimientos. El listado si
    # los muestra —con su marca—, porque un recibo que falta necesita
    # explicacion; los TOTALES no.
    caja_base = _iguales(
        _entre(select(MovimientoCaja), MovimientoCaja.fecha, desde, hasta)
        .where(MovimientoCaja.anulado.is_(False)),
        [(MovimientoCaja.tercero_id, tercero)])
    ingresos = caja_base.where(MovimientoCaja.tipo == TipoMovimientoCaja.INGRESO)
    egresos = caja_base.where(MovimientoCaja.tipo == TipoMovimientoCaja.EGRESO)

    comprobantes = _iguales(
        _entre(select(Comprobante).where(Comprobante.anulado.is_(False)),
               Comprobante.fecha, desde, hasta),
        [(Comprobante.cliente_id, cliente_id)])

    return {
        "desde": desde, "hasta": hasta,
        "cliente_id": cliente_id, "fletero_id": fletero_id,
        "ordenes": contar(vigentes, OrdenCarga.id),
        "ordenes_anuladas": contar(
            base.where(OrdenCarga.estado == EstadoOrden.ANULADA), OrdenCarga.id),
        "ordenes_pendientes": contar(
            vigentes.where(OrdenCarga.estado == EstadoOrden.PENDIENTE), OrdenCarga.id),
        "tarifa": sobre(OrdenCarga.tarifa),
        "iva": sobre(OrdenCarga.iva),
        "total": sobre(OrdenCarga.total),
        "comision": sobre(OrdenCarga.comision),
        "comprobantes": contar(comprobantes, Comprobante.id),
        "facturado": sobre(Comprobante.total, comprobantes),
        "movimientos_caja": contar(caja_base, MovimientoCaja.id),
        "cobrado": sobre(MovimientoCaja.importe, ingresos),
        "pagado": sobre(MovimientoCaja.importe, egresos),
    }


def por_tercero(sesion: Session, rol: RolCuenta, desde: date | None, hasta: date | None,
                limite: int, tercero_id: int | None = None) -> list[dict]:
    """Ranking de clientes o de fleteros, con su saldo al día de hoy.

    🔑 **El saldo NO se acota al rango.** Lo facturado en el período y lo que el
    tercero debe son dos preguntas distintas: un saldo recortado a los últimos
    tres meses no es el saldo de nadie. Van en columnas separadas.

    Con `tercero_id` el ranking se acota a uno: es el mismo reporte con el
    universo más chico, así el número de la lista y el de la ficha coinciden.
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

    saldos_por_tercero = (
        select(MovimientoCuenta.tercero_id.label("tercero_id"),
               (func.coalesce(func.sum(MovimientoCuenta.debe), 0)
                - func.coalesce(func.sum(MovimientoCuenta.haber), 0)).label("saldo"))
        .where(MovimientoCuenta.rol == rol)
        .group_by(MovimientoCuenta.tercero_id).subquery())

    consulta = (
        select(Tercero.id, Tercero.razon_social,
               func.coalesce(movidas.c.ordenes, 0),
               func.coalesce(movidas.c.facturado, 0),
               func.coalesce(movidas.c.comision, 0),
               func.coalesce(saldos_por_tercero.c.saldo, 0))
        .select_from(Tercero)
        .outerjoin(movidas, movidas.c.tercero_id == Tercero.id)
        .outerjoin(saldos_por_tercero, saldos_por_tercero.c.tercero_id == Tercero.id)
        .where(condicion.is_(True)))

    if tercero_id is not None:
        consulta = consulta.where(Tercero.id == tercero_id)
    else:
        # Los que no movieron nada en el período y tampoco deben nada no entran:
        # son 276 terceros y el papel se llenaría de ceros. Con un tercero
        # elegido sí se muestra, aunque esté en cero: la respuesta a "¿cómo viene
        # este cliente?" es "en cero", no una tabla vacía.
        consulta = consulta.where((func.coalesce(movidas.c.ordenes, 0) > 0)
                                  | (func.coalesce(saldos_por_tercero.c.saldo, 0) != 0))

    filas = sesion.execute(
        consulta.order_by(func.coalesce(movidas.c.facturado, 0).desc(),
                          func.abs(func.coalesce(saldos_por_tercero.c.saldo, 0)).desc())
        .limit(limite)).fetchall()

    return [{"tercero_id": f[0], "tercero": f[1], "ordenes": f[2],
             "facturado": Decimal(f[3]).quantize(CERO),
             "comision": Decimal(f[4]).quantize(CERO),
             "saldo": Decimal(f[5]).quantize(CERO)} for f in filas]


def saldos(sesion: Session, rol: RolCuenta | None, incluir_en_cero: bool,
           tercero_id: int | None = None) -> list[dict]:
    """Todas las cuentas corrientes de una vez.

    En el sistema viejo esto no existía: había que abrir la cuenta de cada
    tercero, de a uno, para saber quién debe. Con 267 cuentas eso es una tarde.
    """
    consulta = _iguales(
        select(MovimientoCuenta.tercero_id, MovimientoCuenta.rol, Tercero.razon_social,
               func.count(MovimientoCuenta.id),
               func.max(MovimientoCuenta.fecha),
               func.coalesce(func.sum(MovimientoCuenta.debe), 0)
               - func.coalesce(func.sum(MovimientoCuenta.haber), 0))
        .join(Tercero, Tercero.id == MovimientoCuenta.tercero_id)
        .group_by(MovimientoCuenta.tercero_id, MovimientoCuenta.rol, Tercero.razon_social),
        [(MovimientoCuenta.rol, rol), (MovimientoCuenta.tercero_id, tercero_id)])
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


def caja(sesion: Session, desde: date | None, hasta: date | None,
         tercero_id: int | None = None, medio_pago: MedioPago | None = None,
         tipo: TipoMovimientoCaja | None = None) -> list[dict]:
    """La caja del período, abierta por tipo y medio de pago."""
    filas = sesion.execute(_iguales(_entre(
        # 🔴 Mismo criterio que el resumen: los anulados NO suman. El `where` va
        # adentro del `select` y no despues, porque `_entre` y `_iguales`
        # devuelven la consulta ya armada.
        select(MovimientoCaja.tipo, MovimientoCaja.medio_pago,
               func.count(MovimientoCaja.id),
               func.coalesce(func.sum(MovimientoCaja.importe), 0))
        .where(MovimientoCaja.anulado.is_(False)),
        MovimientoCaja.fecha, desde, hasta),
        [(MovimientoCaja.tercero_id, tercero_id), (MovimientoCaja.medio_pago, medio_pago),
         (MovimientoCaja.tipo, tipo)])
        .group_by(MovimientoCaja.tipo, MovimientoCaja.medio_pago)
        .order_by(MovimientoCaja.tipo, MovimientoCaja.medio_pago)).fetchall()
    return [{"tipo": f[0], "medio_pago": f[1], "movimientos": f[2],
             "importe": Decimal(f[3]).quantize(CERO)} for f in filas]


def por_razon_social(sesion: Session, desde: date | None, hasta: date | None,
                     razon_social_id: int | None = None) -> list[dict]:
    """Lo facturado por cada razón social propia, con su nombre.

    Es la misma cuenta que el gate de F5, pero para leer y no para controlar: acá
    interesa el número, no si los dos lados coinciden.
    """
    filas = sesion.execute(_iguales(_entre(
        select(Comprobante.razon_social_id, RazonSocial.nombre,
               func.count(Comprobante.id),
               func.coalesce(func.sum(Comprobante.neto), 0),
               func.coalesce(func.sum(Comprobante.iva), 0),
               func.coalesce(func.sum(Comprobante.total), 0))
        .join(RazonSocial, RazonSocial.id == Comprobante.razon_social_id)
        .where(Comprobante.anulado.is_(False)),
        Comprobante.fecha, desde, hasta),
        [(Comprobante.razon_social_id, razon_social_id)])
        .group_by(Comprobante.razon_social_id, RazonSocial.nombre)
        .order_by(func.coalesce(func.sum(Comprobante.total), 0).desc())).fetchall()
    return [{"razon_social_id": f[0], "razon_social": f[1], "comprobantes": f[2],
             "neto": Decimal(f[3]).quantize(CERO), "iva": Decimal(f[4]).quantize(CERO),
             "total": Decimal(f[5]).quantize(CERO)} for f in filas]


def por_ruta(sesion: Session, desde: date | None, hasta: date | None, limite: int,
             origen_id: int | None = None, destino_id: int | None = None,
             cliente_id: int | None = None, fletero_id: int | None = None) -> list[dict]:
    """Las rutas más transitadas: origen → destino, con lo que dejaron.

    El legado no podía contestar esto: `origen` y `destino` eran dos tablas con
    los mismos 100 nombres repetidos, y la cantidad era texto libre.
    """
    origen = aliased(Localidad)
    destino = aliased(Localidad)
    filas = sesion.execute(_iguales(_entre(
        select(origen.nombre, destino.nombre,
               func.count(OrdenCarga.id),
               func.coalesce(func.sum(OrdenCarga.total), 0),
               func.coalesce(func.sum(OrdenCarga.comision), 0),
               func.coalesce(func.sum(OrdenCarga.cantidad), 0))
        .join(origen, origen.id == OrdenCarga.origen_id)
        .join(destino, destino.id == OrdenCarga.destino_id)
        .where(OrdenCarga.estado != EstadoOrden.ANULADA),
        OrdenCarga.fecha, desde, hasta),
        [(OrdenCarga.origen_id, origen_id), (OrdenCarga.destino_id, destino_id),
         (OrdenCarga.cliente_id, cliente_id), (OrdenCarga.fletero_id, fletero_id)])
        .group_by(origen.nombre, destino.nombre)
        .order_by(func.count(OrdenCarga.id).desc())
        .limit(limite)).fetchall()
    return [{"origen": f[0], "destino": f[1], "ordenes": f[2],
             "total": Decimal(f[3]).quantize(CERO),
             "comision": Decimal(f[4]).quantize(CERO),
             "cantidad": Decimal(f[5] or 0)} for f in filas]


def pendientes_de_facturar(sesion: Session, desde: date | None, hasta: date | None,
                           cliente_id: int | None = None, limite: int = 200) -> list[dict]:
    """Las órdenes que todavía no salieron en ningún comprobante, por cliente.

    Es el reporte que en el legado era una pantalla propia —`facturarpedientes`,
    con la falta de ortografía y todo—. Acá sale de los mismos datos que el
    listado, agrupado por cliente para saber a quién hay que facturarle.
    """
    filas = sesion.execute(_iguales(_entre(
        select(OrdenCarga.cliente_id, Tercero.razon_social,
               func.count(OrdenCarga.id),
               func.min(OrdenCarga.fecha), func.max(OrdenCarga.fecha),
               func.coalesce(func.sum(OrdenCarga.total), 0))
        .join(Tercero, Tercero.id == OrdenCarga.cliente_id)
        .where(OrdenCarga.estado == EstadoOrden.PENDIENTE),
        OrdenCarga.fecha, desde, hasta),
        [(OrdenCarga.cliente_id, cliente_id)])
        .group_by(OrdenCarga.cliente_id, Tercero.razon_social)
        .order_by(func.coalesce(func.sum(OrdenCarga.total), 0).desc())
        .limit(limite)).fetchall()
    return [{"cliente_id": f[0], "cliente": f[1], "ordenes": f[2],
             "desde": f[3], "hasta": f[4],
             "total": Decimal(f[5]).quantize(CERO)} for f in filas]
