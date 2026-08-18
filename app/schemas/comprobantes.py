"""Esquemas de comprobantes.

> 🔑 **El comprobante no se emite: se registra.** El sistema legado no factura
> contra ARCA — alguien tipea el número de una factura que ya existe en papel o
> en el facturador de ARCA. Replicar eso es lo que da **paridad verificable**
> contra el sistema viejo durante la migración; la emisión real es F8, con su
> propio alcance. Mezclarlas haría que una diferencia de totales tuviera dos
> causas posibles y ninguna forma de separarlas.

> 🔑 **Los importes tampoco entran por el cuerpo: salen de las órdenes.** Un
> comprobante es la suma de las órdenes que agrupa. Aceptar un total del cliente
> permitiría que el comprobante diga un número y sus órdenes otro, que es
> exactamente la diferencia que el gate de F5 tiene que poder descartar.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TipoComprobante
from app.schemas.ordenes import OrdenOut

#: Los tipos que se registran sobre órdenes pendientes. Una nota de crédito no
#: agrupa órdenes: revierte un comprobante, y ese camino es `DELETE`.
TIPOS_FACTURA = frozenset({
    TipoComprobante.FACTURA_A,
    TipoComprobante.FACTURA_B,
    TipoComprobante.FACTURA_C,
})

#: Cómo se lee cada tipo en el concepto de la cuenta corriente.
NOMBRES_DE_TIPO = {
    TipoComprobante.FACTURA_A: "Factura A",
    TipoComprobante.FACTURA_B: "Factura B",
    TipoComprobante.FACTURA_C: "Factura C",
    TipoComprobante.NOTA_CREDITO_A: "Nota de credito A",
    TipoComprobante.NOTA_CREDITO_B: "Nota de credito B",
    TipoComprobante.NOTA_CREDITO_C: "Nota de credito C",
}


class FacturarIn(BaseModel):
    """"Facturar pendientes": las órdenes elegidas pasan a un comprobante."""

    model_config = ConfigDict(str_strip_whitespace=True)

    fecha: date
    razon_social_id: int
    cliente_id: int
    tipo: TipoComprobante
    punto_venta: int = Field(default=1, ge=0, le=99999)
    numero: int = Field(ge=1)
    orden_ids: list[int] = Field(min_length=1)

    @field_validator("orden_ids")
    @classmethod
    def _sin_repetidos(cls, valor: list[int]) -> list[int]:
        """Una orden repetida sumaría dos veces y la factura quedaría al doble.

        El `IN` de la consulta la trae una sola vez, así que sin este chequeo el
        pedido no falla: pasa, con un total que no es el de las órdenes.
        """
        if len(set(valor)) != len(valor):
            raise ValueError("hay ordenes repetidas: el importe se contaria dos veces")
        return valor


class ComprobanteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    razon_social_id: int
    tipo: TipoComprobante
    punto_venta: int
    numero: int
    fecha: date
    cliente_id: int
    # Importes como `Decimal`: son `NUMERIC` en la base, y pasar por `float`
    # reintroduce el defecto que el producto viene a reparar.
    neto: Decimal
    iva: Decimal
    total: Decimal
    anulado: bool
    origen_legado: str | None = None


class SumaDeOrdenes(BaseModel):
    """Lo que suman las órdenes de un comprobante, contado aparte de él."""

    cantidad: int
    neto: Decimal
    iva: Decimal
    total: Decimal


class ComprobanteConOrdenes(BaseModel):
    """El comprobante, sus órdenes, y si los dos lados dan lo mismo.

    Es el gate de F5 a nivel de un comprobante: el encabezado guarda sus propios
    importes, y las órdenes los suyos. Que se devuelvan **los dos** y si
    coinciden evita tener que abrir la base para saber si el total del papel es
    el de las órdenes que lo componen.
    """

    comprobante: ComprobanteOut
    ordenes: list[OrdenOut]
    suma_de_ordenes: SumaDeOrdenes
    coinciden: bool


class TotalDeRazonSocial(BaseModel):
    """El total facturado por una razón social, contado por los dos lados.

    - Por **comprobantes**: suma de los encabezados.
    - Por **órdenes**: suma de las órdenes, agrupadas por la razón social que
      lleva **la orden**, no la del comprobante.

    Agrupar por la columna de la orden es a propósito: `facturar` deja las dos
    iguales, así que sobre datos cargados acá siempre coinciden. Lo que esto
    detecta son los **datos migrados**, donde `carga_razonsocial` y
    `factura_razonsocial` son dos columnas del legado que pueden discrepar — y
    entonces el mismo importe estaría en una razón social por un lado y en otra
    por el otro.
    """

    razon_social_id: int | None
    cantidad_comprobantes: int
    neto_comprobantes: Decimal
    iva_comprobantes: Decimal
    total_comprobantes: Decimal
    cantidad_ordenes: int
    neto_ordenes: Decimal
    iva_ordenes: Decimal
    total_ordenes: Decimal
    coinciden: bool
