"""La pre liquidación de transportistas: qué se le va a liquidar a cada fletero por sus fletes.

Es **de lectura** y no es un comprobante: arma, para un rango de fechas, los fletes que hizo cada
transportista con lo que cobra por cada uno y el IVA que le corresponde, para mandárselo y que lo
confirme antes de que facture.

🔑 **El valor de cada flete es la comisión de la orden**, no la tarifa: la comisión es lo que cobra
el fletero y el mismo importe que `ordenes.sincronizar_comision` le asienta en su cuenta corriente.
La tarifa es lo que se le cobra al cliente.

🔑 **Qué órdenes entran** (la misma condición con que se le asienta el flete al fletero):

* tienen **fletero** (`fletero_id`) — una orden sin fletero no tiene a quién liquidarle y **no entra**;
* con **comisión mayor que cero**;
* **no anuladas**. Las pendientes y las facturadas entran las dos: la liquidación al transportista
  no depende de que al cliente ya se le haya facturado;
* con la **fecha de la orden** dentro del rango, extremos incluidos.

🔑 **El IVA depende del transportista, no de la orden.** Sólo un **responsable inscripto** discrimina
IVA en lo que factura: a ése se le suma `comisión × alícuota de la orden / 100`, redondeado a
centavos **por flete** (la suma de los redondeos es lo que después va a decir su factura). Para
cualquier otra condición el IVA es cero. Criterio por valor de `CondicionIVA` (ADR-033):

=====================  =====  ==============================================================
condición              IVA    por qué
=====================  =====  ==============================================================
responsable inscripto  suma   discrimina IVA en su factura A
monotributo            cero   factura C: el IVA no se discrimina
exento                 cero   está exento
consumidor final       cero   no es una condición de quien presta un servicio: no discrimina
no categorizado        cero   no se sabe: se liquida sin IVA y el bloque lo avisa
=====================  =====  ==============================================================

Los dos últimos salen con un aviso, porque son un dato a corregir en el maestro de terceros más que
una condición real: sumar IVA por las dudas le liquidaría de más a quien no lo cobra.

Todo es `Decimal` de punta a punta: los importes viajan como string en la API.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.enums import CondicionIVA, EstadoOrden
from app.models.maestros import Localidad, Tercero
from app.models.operacion import OrdenCarga
from app.schemas.ordenes import calcular_importes

CERO = Decimal("0.00")
CENTAVO = Decimal("0.01")

#: Quién suma IVA. Es exhaustivo a propósito (`test_cada_condicion_tiene_su_criterio`): un valor nuevo
#: del enum sin criterio acá tiene que romper un test y no liquidarse en silencio con IVA cero.
DISCRIMINA_IVA: dict[CondicionIVA, bool] = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: True,
    CondicionIVA.MONOTRIBUTO: False,
    CondicionIVA.EXENTO: False,
    CondicionIVA.CONSUMIDOR_FINAL: False,
    CondicionIVA.NO_CATEGORIZADO: False,
}

#: Lo que se avisa en el bloque cuando la condición es un dato a corregir y no una condición real.
AVISO_DE_CONDICION: dict[CondicionIVA, str] = {
    CondicionIVA.CONSUMIDOR_FINAL:
        "Figura como consumidor final, que no es una condición de transportista: se liquida sin IVA. "
        "Corregí su condición de IVA en el maestro de terceros.",
    CondicionIVA.NO_CATEGORIZADO:
        "No tiene condición de IVA cargada: se liquida sin IVA. "
        "Cargala en el maestro de terceros para que se le sume si corresponde.",
}

#: Cómo se lee cada condición en el papel.
NOMBRE_DE_CONDICION: dict[CondicionIVA, str] = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: "Responsable inscripto",
    CondicionIVA.MONOTRIBUTO: "Monotributista",
    CondicionIVA.EXENTO: "Exento",
    CondicionIVA.CONSUMIDOR_FINAL: "Consumidor final",
    CondicionIVA.NO_CATEGORIZADO: "Sin categorizar",
}


def iva_del_flete(condicion: CondicionIVA, comision: Decimal, alicuota: Decimal) -> Decimal:
    """El IVA de un flete: `comisión × alícuota / 100` redondeado a centavos (mitad hacia arriba),
    si el transportista discrimina IVA; cero si no.

    Es la misma cuenta y el mismo redondeo con que la orden calcula su propio IVA
    (`calcular_importes`): una sola fórmula para el IVA de un importe."""
    if not DISCRIMINA_IVA[condicion]:
        return CERO
    return calcular_importes(comision, alicuota)[0]


def armar(sesion: Session, desde: date, hasta: date, fletero_id: int | None = None) -> dict:
    """La pre liquidación del rango, un bloque por transportista.

    Los transportistas salen por razón social (y por id si dos se llaman igual), y sus fletes por
    fecha y número de orden. `fletero_id` acota a uno: es el mismo reporte con el universo más chico.
    """
    fletero = aliased(Tercero)
    cliente = aliased(Tercero)
    origen = aliased(Localidad)
    destino = aliased(Localidad)

    consulta = (
        select(OrdenCarga, fletero, cliente.razon_social, origen.nombre, destino.nombre)
        .join(fletero, fletero.id == OrdenCarga.fletero_id)
        .join(cliente, cliente.id == OrdenCarga.cliente_id)
        .join(origen, origen.id == OrdenCarga.origen_id)
        .join(destino, destino.id == OrdenCarga.destino_id)
        .where(OrdenCarga.fecha >= desde, OrdenCarga.fecha <= hasta,
               OrdenCarga.comision > CERO,
               OrdenCarga.estado != EstadoOrden.ANULADA)
        .order_by(fletero.razon_social, fletero.id, OrdenCarga.fecha, OrdenCarga.id))
    if fletero_id is not None:
        consulta = consulta.where(OrdenCarga.fletero_id == fletero_id)

    bloques: dict[int, dict] = {}
    for orden, tercero, nombre_cliente, nombre_origen, nombre_destino in sesion.execute(consulta):
        bloque = bloques.get(tercero.id)
        if bloque is None:
            condicion = tercero.condicion_iva
            bloque = bloques[tercero.id] = {
                "tercero_id": tercero.id,
                "transportista": tercero.razon_social,
                "cuit": tercero.cuit,
                "condicion_iva": condicion.value,
                "condicion_iva_texto": NOMBRE_DE_CONDICION[condicion],
                "discrimina_iva": DISCRIMINA_IVA[condicion],
                "aviso": AVISO_DE_CONDICION.get(condicion),
                "fletes": [], "cantidad_fletes": 0,
                "neto": CERO, "iva": CERO, "total": CERO,
                "_condicion": condicion,
            }
        neto = Decimal(orden.comision).quantize(CENTAVO)
        iva = iva_del_flete(bloque["_condicion"], neto, Decimal(orden.alicuota_iva))
        bloque["fletes"].append({
            "orden_id": orden.id,
            "fecha": orden.fecha,
            "remito": orden.remito,
            "cliente": nombre_cliente,
            "origen": nombre_origen,
            "destino": nombre_destino,
            "cantidad": orden.cantidad,
            "unidad": orden.unidad,
            "cantidad_legado": orden.cantidad_legado,
            "alicuota_iva": Decimal(orden.alicuota_iva),
            "neto": neto, "iva": iva, "total": neto + iva,
        })
        bloque["cantidad_fletes"] += 1
        bloque["neto"] += neto
        bloque["iva"] += iva
        bloque["total"] += neto + iva

    transportistas = list(bloques.values())
    for b in transportistas:
        del b["_condicion"]
    return {
        "desde": desde, "hasta": hasta, "fletero_id": fletero_id,
        "transportistas": transportistas,
        "fletes": sum(b["cantidad_fletes"] for b in transportistas),
        "neto": sum((b["neto"] for b in transportistas), CERO),
        "iva": sum((b["iva"] for b in transportistas), CERO),
        "total": sum((b["total"] for b in transportistas), CERO),
    }
