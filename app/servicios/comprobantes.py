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
from sqlalchemy.orm import Session, aliased

from app.models.enums import TipoComprobante
from app.models.operacion import Comprobante, OrdenCarga
from app.schemas.comprobantes import (
    NOMBRES_DE_TIPO,
    SumaDeOrdenes,
    TotalDeRazonSocial,
)

CERO = Decimal("0.00")

#: Las notas de crédito (de factura y de FCE). No **suman** a lo facturado: lo **restan**, y sólo
#: mientras su original sigue vigente (ver `acreditado_por_notas`).
TIPOS_NOTA = frozenset({
    TipoComprobante.NOTA_CREDITO_A,
    TipoComprobante.NOTA_CREDITO_B,
    TipoComprobante.NOTA_CREDITO_C,
    TipoComprobante.NOTA_CREDITO_FCE_A,
    TipoComprobante.NOTA_CREDITO_FCE_B,
    TipoComprobante.NOTA_CREDITO_FCE_C,
})


def solo_facturas(consulta):
    """Saca las notas de crédito de una suma de lo facturado: las notas se **restan** aparte.

    Sumarlas haría subir lo facturado en vez de bajarlo. Lo que restan lo da `acreditado_por_notas`.
    """
    return consulta.where(Comprobante.tipo.notin_(TIPOS_NOTA))


def acreditado_por_notas(
    agrupar_por, desde: date | None = None, hasta: date | None = None, filtros=(),
) -> Select:
    """Lo que acreditan las notas de crédito **cuyo original sigue vigente**, agrupado por `agrupar_por`.

    Devuelve `(clave, cantidad, neto, iva, total)` por grupo; es lo que se **resta** de lo facturado (ADR-028).

    - 🔑 **Sólo cuentan las notas de un original no anulado.** Una nota total anula su original, y cuando las
      parciales suman el comprobante entero también (`cerrar_lo_propio`): ese original ya salió de los totales en
      todo el rango, y restar además sus notas lo descontaría dos veces. Así la nota total no suma ni resta, y no
      hace falta distinguirla de una parcial.
    - **El rango es el de la fecha de la nota**, no la del original: es un hecho fechado de ARCA, y es la fecha con la
      que entra al libro de ventas y a la cuenta corriente.
    - `agrupar_por` es una columna de la **nota** (`Comprobante.razon_social_id`, `Comprobante.cliente_id`…), y
      `filtros` pares `(columna, valor)` sobre ella; un valor `None` no filtra.
    """
    original = aliased(Comprobante)
    consulta = (
        select(
            agrupar_por,
            func.count(Comprobante.id),
            func.coalesce(func.sum(Comprobante.neto), 0),
            func.coalesce(func.sum(Comprobante.iva), 0),
            func.coalesce(func.sum(Comprobante.total), 0),
        )
        .select_from(Comprobante)
        # Toda nota tiene asociado y nada más lo tiene (`ck_comprobantes_nota_con_asociado`): el `join` ya las elige.
        .join(original, Comprobante.comprobante_asociado_id == original.id)
        .where(Comprobante.anulado.is_(False), original.anulado.is_(False))
        .group_by(agrupar_por)
    )
    for columna, valor in filtros:
        if valor is not None:
            consulta = consulta.where(columna == valor)
    return _acotar(consulta, desde, hasta)


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

    🔑 **Las notas parciales se restan de los dos lados, por lo mismo** (ADR-028): acreditan plata sin tocar las
    órdenes, así que del lado de los comprobantes lo facturado baja y del lado de las órdenes también tiene que
    bajar —si no, cada nota parcial aparecería como una diferencia—. Los dos restan **el mismo** conjunto
    (`acreditado_por_notas`), así que la comparación sigue siendo la de los encabezados contra sus órdenes.
    `cantidad_comprobantes` cuenta facturas, no notas.
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
    por_comprobante = solo_facturas(por_comprobante)
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
    notas = {fila[0]: fila[2:] for fila in sesion.execute(
        acreditado_por_notas(Comprobante.razon_social_id, desde, hasta))}

    salida = []
    # La unión de las dos claves, no la intersección: una razón social que
    # aparece de un solo lado es justamente el caso que hay que ver. Con un
    # `join` entre los dos agregados, esa fila desaparecería y la pantalla
    # mostraría todo en orden.
    for clave in sorted(set(lado_a) | set(lado_b) | set(notas), key=lambda k: (k is None, k or 0)):
        cant_c, neto_c, iva_c, total_c = lado_a.get(clave, (0, 0, 0, 0))
        cant_o, neto_o, iva_o, total_o = lado_b.get(clave, (0, 0, 0, 0))
        neto_n, iva_n, total_n = (Decimal(x) for x in notas.get(clave, (0, 0, 0)))
        neto_c, iva_c, total_c = (
            (Decimal(x) - n).quantize(CERO) for x, n in ((neto_c, neto_n), (iva_c, iva_n), (total_c, total_n)))
        neto_o, iva_o, total_o = (
            (Decimal(x) - n).quantize(CERO) for x, n in ((neto_o, neto_n), (iva_o, iva_n), (total_o, total_n)))
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
