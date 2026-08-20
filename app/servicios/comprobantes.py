"""Totales de comprobantes, contados por los dos lados a propósito.

El criterio de F5 en el ROADMAP es que **los totales por razón social sean
reproducibles**. Reproducible quiere decir que el mismo número salga de dos
lugares distintos: de los encabezados de los comprobantes, y de las órdenes que
esos comprobantes agrupan.

Es el mismo criterio de F4 aplicado a otra cosa. Si los dos lados coinciden, el
total no depende de dónde se lo miró; si difieren, hay un importe que está en
una razón social por un lado y en otra por el otro —o un encabezado que dice
algo que sus órdenes no dicen—. En el legado esa comparación no se podía hacer:
`orden_carga.carga_razonsocial` y `facturas.factura_razonsocial` son dos enteros
sin tabla ni clave foránea que los ate.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.enums import TipoComprobante
from app.models.operacion import Comprobante, OrdenCarga
from app.schemas.comprobantes import (
    NOMBRES_DE_TIPO,
    SumaDeOrdenes,
    TotalDeRazonSocial,
)

CERO = Decimal("0.00")


def etiqueta(tipo: TipoComprobante, punto_venta: int, numero: int) -> str:
    """`Factura A 0001-00000123` — como se lee en un papel argentino.

    Se usa como concepto del movimiento de cuenta corriente: quien mira la
    cuenta tiene que poder encontrar el comprobante sin cruzar ids a mano.
    """
    return f"{NOMBRES_DE_TIPO[tipo]} {punto_venta:04d}-{numero:08d}"


def sumar_ordenes(ordenes: Iterable[OrdenCarga]) -> SumaDeOrdenes:
    """La suma de las órdenes, en `Decimal` de punta a punta.

    El neto de un comprobante es la suma de las **tarifas**, y el IVA la suma de
    los IVA de cada orden — no el IVA recalculado sobre el neto total. No es lo
    mismo: cada orden redondea su IVA a dos decimales, y aplicar la alícuota
    sobre la suma puede dar un centavo distinto. Sumando lo que ya está guardado,
    el total del comprobante es exactamente el de sus órdenes, y además admite
    órdenes con alícuotas distintas en la misma factura.
    """
    cantidad, neto, iva, total = 0, CERO, CERO, CERO
    for orden in ordenes:
        cantidad += 1
        neto += orden.tarifa
        iva += orden.iva
        total += orden.total
    return SumaDeOrdenes(cantidad=cantidad, neto=neto.quantize(CERO),
                         iva=iva.quantize(CERO), total=total.quantize(CERO))


def _acotar(consulta: Select, desde: date | None, hasta: date | None) -> Select:
    """El rango se aplica **siempre sobre la fecha del comprobante**.

    En los dos lados, aunque uno agregue órdenes: si el lado de las órdenes
    filtrara por la fecha de la orden, los dos conjuntos no serían el mismo y la
    diferencia diría "no coinciden" por el recorte, no por los datos.
    """
    if desde is not None:
        consulta = consulta.where(Comprobante.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(Comprobante.fecha <= hasta)
    return consulta


def totales_por_razon_social(
    sesion: Session, desde: date | None = None, hasta: date | None = None
) -> list[TotalDeRazonSocial]:
    """Los totales de cada razón social, por comprobantes y por órdenes.

    Los anulados quedan afuera de los dos lados: un comprobante anulado devuelve
    sus órdenes a pendientes, así que contarlo de un lado y no del otro
    reportaría una diferencia que no existe.
    """
    por_comprobante = _acotar(
        select(
            Comprobante.razon_social_id,
            func.count(Comprobante.id),
            func.coalesce(func.sum(Comprobante.neto), 0),
            func.coalesce(func.sum(Comprobante.iva), 0),
            func.coalesce(func.sum(Comprobante.total), 0),
        ).where(Comprobante.anulado.is_(False)).group_by(Comprobante.razon_social_id),
        desde, hasta,
    )
    por_orden = _acotar(
        select(
            OrdenCarga.razon_social_id,
            func.count(OrdenCarga.id),
            func.coalesce(func.sum(OrdenCarga.tarifa), 0),
            func.coalesce(func.sum(OrdenCarga.iva), 0),
            func.coalesce(func.sum(OrdenCarga.total), 0),
        )
        .join(Comprobante, OrdenCarga.comprobante_id == Comprobante.id)
        .where(Comprobante.anulado.is_(False))
        .group_by(OrdenCarga.razon_social_id),
        desde, hasta,
    )

    lado_a = {fila[0]: fila[1:] for fila in sesion.execute(por_comprobante)}
    lado_b = {fila[0]: fila[1:] for fila in sesion.execute(por_orden)}

    salida = []
    # La unión de las dos claves, no la intersección: una razón social que
    # aparece de un solo lado es justamente el caso que hay que ver. Con un
    # `join` entre los dos agregados, esa fila desaparecería y la pantalla
    # mostraría todo en orden.
    for clave in sorted(set(lado_a) | set(lado_b), key=lambda k: (k is None, k or 0)):
        cant_c, neto_c, iva_c, total_c = lado_a.get(clave, (0, 0, 0, 0))
        cant_o, neto_o, iva_o, total_o = lado_b.get(clave, (0, 0, 0, 0))
        neto_c, iva_c, total_c = (Decimal(x).quantize(CERO) for x in (neto_c, iva_c, total_c))
        neto_o, iva_o, total_o = (Decimal(x).quantize(CERO) for x in (neto_o, iva_o, total_o))
        salida.append(TotalDeRazonSocial(
            razon_social_id=clave,
            cantidad_comprobantes=cant_c,
            neto_comprobantes=neto_c, iva_comprobantes=iva_c, total_comprobantes=total_c,
            cantidad_ordenes=cant_o,
            neto_ordenes=neto_o, iva_ordenes=iva_o, total_ordenes=total_o,
            # Los tres importes, no sólo el total: un neto de más compensado por
            # un IVA de menos da el mismo total y es un error igual.
            coinciden=(neto_c, iva_c, total_c) == (neto_o, iva_o, total_o),
        ))
    return salida
