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

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


def _hoy() -> date:
    """La fecha de hoy en Argentina, que es la que compara ARCA."""
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()


class FacturarIn(BaseModel):
    """"Facturar pendientes": las órdenes elegidas pasan a un comprobante."""

    model_config = ConfigDict(str_strip_whitespace=True)

    fecha: date
    razon_social_id: int
    cliente_id: int
    tipo: TipoComprobante
    punto_venta: int = Field(default=1, ge=0, le=99999)
    #: ⚠️ Opcional **sólo porque puede venir de ARCA**. Cuando la razón social
    #: emite, el número lo da `FECompUltimoAutorizado + 1` y mandarlo desde el
    #: cliente no tiene sentido: ARCA rechaza cualquier otro. Cuando registra a
    #: mano sigue siendo obligatorio, y lo exige el endpoint.
    numero: int | None = Field(default=None, ge=1)
    orden_ids: list[int] = Field(min_length=1)
    #: **Sólo la FCE** lo lleva, y toda FCE lo exige: ARCA la rechaza sin él (10163).
    fecha_vencimiento_pago: date | None = None

    @model_validator(mode="after")
    def _vencimiento_de_pago(self):
        if self.tipo in TIPOS_FCE:
            if self.fecha_vencimiento_pago is None:
                raise ValueError(
                    "la factura de credito electronica exige la fecha de vencimiento de pago")
            if self.fecha_vencimiento_pago < self.fecha:
                raise ValueError(
                    "el vencimiento de pago no puede ser anterior a la fecha del comprobante")
            # ARCA lo compara además contra **hoy** (10164, «posterior o igual a la fecha de
            # emisión o a la fecha de presentación, la que sea posterior»): una FCE con
            # fecha atrasada y un vencimiento ya vencido llegaría hasta ARCA y volvería
            # como un 502 después de pedir el número.
            if self.fecha_vencimiento_pago < _hoy():
                raise ValueError("el vencimiento de pago no puede ser anterior a hoy")
        elif self.fecha_vencimiento_pago is not None:
            raise ValueError(
                "solo la factura de credito electronica lleva fecha de vencimiento de pago")
        return self

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
