"""Esquemas de comprobantes.

> 🔑 **El comprobante no se tipea: lo emite ARCA desde una pre factura** (ADR-032). Hasta entonces, sin
> certificado, alguien registraba a mano el punto de venta y el número de una factura hecha en otro lado
> (`FacturarIn`). Ya no hay forma de hacerlo: lo migrado del legado sigue como estaba, y lo nuevo sale de
> `app/schemas/pre_facturas.py`.

> 🔑 **Los importes no entran por el cuerpo: salen de las órdenes.** Un comprobante es la suma de las
> órdenes que agrupa. Aceptar un total del cliente permitiría que el comprobante diga un número y sus
> órdenes otro, que es exactamente la diferencia que el gate de F5 tiene que poder descartar.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TipoComprobante
from app.schemas.ordenes import OrdenOut

#: Los tipos que se registran sobre órdenes pendientes. Una nota de crédito no
#: agrupa órdenes: revierte un comprobante, y ese camino es `DELETE`.
#: La Factura de Crédito Electrónica MiPyME. Va aparte porque lleva reglas propias:
#: fecha de vencimiento de pago, receptor con CUIT y emisión sólo por ARCA.
TIPOS_FCE = frozenset({
    TipoComprobante.FCE_A,
    TipoComprobante.FCE_B,
    TipoComprobante.FCE_C,
})

TIPOS_FACTURA = frozenset({
    TipoComprobante.FACTURA_A,
    TipoComprobante.FACTURA_B,
    TipoComprobante.FACTURA_C,
}) | TIPOS_FCE

#: Cómo se lee cada tipo en el concepto de la cuenta corriente.
NOMBRES_DE_TIPO = {
    TipoComprobante.FACTURA_A: "Factura A",
    TipoComprobante.FACTURA_B: "Factura B",
    TipoComprobante.FACTURA_C: "Factura C",
    TipoComprobante.NOTA_CREDITO_A: "Nota de credito A",
    TipoComprobante.NOTA_CREDITO_B: "Nota de credito B",
    TipoComprobante.NOTA_CREDITO_C: "Nota de credito C",
    TipoComprobante.FCE_A: "Factura de credito electronica A",
    TipoComprobante.FCE_B: "Factura de credito electronica B",
    TipoComprobante.FCE_C: "Factura de credito electronica C",
    TipoComprobante.NOTA_CREDITO_FCE_A: "Nota de credito FCE A",
    TipoComprobante.NOTA_CREDITO_FCE_B: "Nota de credito FCE B",
    TipoComprobante.NOTA_CREDITO_FCE_C: "Nota de credito FCE C",
}


class NotaDeCreditoIn(BaseModel):
    """El pedido de nota de crédito: el motivo y, si es parcial, el importe.

    - **Sin `importe`, la nota es total**: copia el comprobante, sus órdenes vuelven a pendientes.
    - **Con `importe`, es parcial**: el monto a acreditar, **con IVA**, de hasta dos decimales. No toca las órdenes
      hasta que las notas suman el comprobante entero (ADR-028). Una FCE sólo admite esta, por menos que su saldo.

    Sin fecha y sin tipo, a propósito: la fecha es la de hoy (ARCA exige fechas no decrecientes por tipo y punto de
    venta) y el tipo sale del original. El tope del importe lo valida el motor, que es el que sabe lo ya acreditado.
    """

    model_config = ConfigDict(extra="forbid")

    motivo: str = Field(min_length=3, max_length=500)
    importe: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)

    @field_validator("importe", mode="before")
    @classmethod
    def _sin_booleanos(cls, valor):
        """Un `true` no entra como `1`: un booleano no es un importe (la regla de la familia)."""
        if isinstance(valor, bool):
            raise ValueError("el importe es un numero, no un booleano")
        return valor

    @field_validator("motivo")
    @classmethod
    def _sin_espacios(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 3:
            raise ValueError("el motivo tiene que decir por que se emite la nota (3 letras o mas)")
        return valor


class ComprobanteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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

    #: `None` es el estado normal de todo lo migrado y de lo que se registre a
    #: mano: la pantalla lo lee como "sin CAE", no como un dato que falta.
    cae: str | None = None
    cae_vencimiento: date | None = None
    cae_solicitado_en: datetime | None = None

    #: Sólo una FCE los tiene; en todo lo demás son `None`.
    fch_vto_pago: date | None = None
    fce_cbu: str | None = None
    fce_transmision: str | None = None

    #: Sólo una nota de crédito los tiene: a qué comprobante acredita y por qué.
    comprobante_asociado_id: int | None = None
    motivo: str | None = None


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
    #: Las notas de crédito que cuelgan de este comprobante (vacío en una nota y en lo que no tiene ninguna).
    notas: list[ComprobanteOut] = []
    #: Lo que acreditan sus notas con CAE y lo que queda por acreditar, **calculado por el motor**
    #: (`saldo_acreditable`). `None` donde no hay nota posible: sin CAE, anulado o una nota.
    acreditado: Decimal | None = None
    saldo_acreditable: Decimal | None = None


class TotalDeComprobantes(BaseModel):
    """Lo facturado en el rango, contado por los dos lados.

    - Por **comprobantes**: suma de los encabezados.
    - Por **órdenes**: suma de las órdenes que esos comprobantes agrupan.

    `facturar` deja las dos iguales, así que sobre datos cargados acá siempre coinciden. Lo que esto
    detecta son los **datos migrados** o tocados por fuera, donde un encabezado puede decir un importe y
    sus órdenes otro. Desde ADR-035 hay un solo emisor, así que el total ya no se abre por razón social.
    """

    cantidad_comprobantes: int
    neto_comprobantes: Decimal
    iva_comprobantes: Decimal
    total_comprobantes: Decimal
    cantidad_ordenes: int
    neto_ordenes: Decimal
    iva_ordenes: Decimal
    total_ordenes: Decimal
    coinciden: bool
