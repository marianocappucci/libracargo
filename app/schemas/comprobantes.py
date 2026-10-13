"""Esquemas de comprobantes.

> 🔑 **El comprobante no se tipea: lo emite ARCA.** Desde ADR-048 sale de dos caminos y los dos van directo a
> ARCA, sin documento intermedio: **«Facturar pendientes»** (`FacturarOrdenesIn`: las órdenes de un cliente) y
> **«Nueva factura»** (`FacturaDirectaIn`: conceptos libres). Antes (ADR-032) pasaba por una pre factura y,
> antes todavía, alguien registraba a mano el punto de venta y el número de una factura hecha en otro lado. Ya no
> hay forma de hacerlo: lo migrado del legado sigue como estaba.

> 🔑 **Los importes de «Facturar pendientes» no entran por el cuerpo: salen de las órdenes.** Un comprobante es la
> suma de las órdenes que agrupa. Aceptar un total del cliente permitiría que el comprobante diga un número y sus
> órdenes otro, que es exactamente la diferencia que el gate de F5 tiene que poder descartar. En cambio la factura
> directa **no tiene órdenes contra las que comparar**: sus importes salen de los conceptos, y los calcula el
> servidor (`servicios/facturacion.py`), nunca el cliente.
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
    TipoComprobante.NOTA_DEBITO_A: "Nota de debito A",
    TipoComprobante.NOTA_DEBITO_B: "Nota de debito B",
    TipoComprobante.NOTA_DEBITO_C: "Nota de debito C",
    TipoComprobante.NOTA_DEBITO_FCE_A: "Nota de debito FCE A",
    TipoComprobante.NOTA_DEBITO_FCE_B: "Nota de debito FCE B",
    TipoComprobante.NOTA_DEBITO_FCE_C: "Nota de debito FCE C",
}

#: Las alícuotas de IVA que se pueden facturar. **Son las que conoce el WSFE del motor** (`arca_wsfe._IVA_ID`): una
#: que no está ahí cae al 21% sin avisar (docs/facturacion-arca.md del motor). Un test las compara con la tabla del
#: motor, así que si el motor suma una, esto avisa.
ALICUOTAS_DE_IVA = (Decimal("0"), Decimal("10.5"), Decimal("21"), Decimal("27"))


def _sin_booleanos(valor):
    """Un `true` no entra como `1`: un booleano no es un número (la regla de la familia, libracore v1.125.0)."""
    if isinstance(valor, bool):
        raise ValueError("tiene que ser un numero, no un booleano")
    return valor


class _ComprobanteIn(BaseModel):
    """Lo que tienen en común los dos caminos de emisión: a quién, qué tipo, cuándo y, si es FCE, cómo se cobra.

    `extra="forbid"`: un cuerpo con `punto_venta`, `numero`, `neto` o `total` es un cliente que cree que los puede
    mandar, y callarlo dejaría que el error se descubra en la factura. El punto de venta es el de la configuración
    de ARCA y el número lo pone ARCA.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cliente_id: int
    tipo: TipoComprobante
    fecha: date
    #: Sólo la FCE lo lleva, y toda FCE lo exige (lo valida `servicios.facturacion`).
    fecha_vencimiento_pago: date | None = None
    #: Sólo la FCE: en qué cuenta se cobra, por su CBU **o su alias** (libracore ADR-040). `""` o ausente es la
    #: predeterminada de la configuración de ARCA; una que no está cargada la rechaza el motor (422).
    fce_cbu: str | None = Field(default=None, max_length=40)
    observaciones: str = Field(default="", max_length=500)

    _cliente_sin_booleanos = field_validator("cliente_id", mode="before")(_sin_booleanos)


class FacturarOrdenesIn(_ComprobanteIn):
    """«Facturar pendientes»: las órdenes de un cliente, por ARCA y sin pre factura (ADR-048).

    Ítems e importes no entran: salen de las órdenes (ver el docstring del módulo).
    """

    orden_ids: list[int] = Field(min_length=1)

    @field_validator("orden_ids")
    @classmethod
    def _sin_repetidos(cls, valor: list[int]) -> list[int]:
        """Una orden repetida sumaría dos veces y la factura quedaría al doble.

        El `IN` de la consulta la trae una sola vez, así que sin este chequeo el pedido no falla: pasa,
        con un total que no es el de las órdenes.
        """
        if len(set(valor)) != len(valor):
            raise ValueError("hay ordenes repetidas: el importe se contaria dos veces")
        return valor


class ConceptoIn(BaseModel):
    """Un renglón de la factura directa: qué se cobra, cuántos, a qué precio y con qué IVA.

    El precio es **neto** (sin IVA); una clase C no discrimina IVA y ahí el precio es el total (la alícuota se
    ignora y sale en cero, que es lo único que admite ARCA para esa clase).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    descripcion: str = Field(min_length=1, max_length=200)
    cantidad: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    precio_unitario: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    alicuota_iva: Decimal = Decimal("21")

    _numeros_sin_booleanos = field_validator(
        "cantidad", "precio_unitario", "alicuota_iva", mode="before")(_sin_booleanos)

    @field_validator("alicuota_iva")
    @classmethod
    def _alicuota_conocida(cls, valor: Decimal) -> Decimal:
        if valor not in ALICUOTAS_DE_IVA:
            raise ValueError(
                "la alicuota de IVA tiene que ser una de " + ", ".join(f"{a.normalize():f}" for a in ALICUOTAS_DE_IVA)
                + "%: son las que ARCA recibe")
        return valor


class FacturaDirectaIn(_ComprobanteIn):
    """«Nueva factura»: conceptos libres, sin órdenes ni remitos, directo por ARCA (ADR-048).

    Los importes los calcula el servidor desde los conceptos. **Todos los conceptos llevan la misma alícuota**: el
    WSFE del motor arma un solo bloque de IVA por comprobante, y mezclar alícuotas daría un IVA que ARCA no cierra.
    """

    conceptos: list[ConceptoIn] = Field(min_length=1, max_length=50)


class NotaDeDebitoIn(BaseModel):
    """El pedido de nota de débito: el motivo y **cuánto se debita** (con IVA).

    A diferencia de la de crédito, **no hay nota total** (no copia la factura) y el importe **no tiene tope**: agrega
    plata (intereses, un gasto, una diferencia de precio). Sin fecha y sin tipo, a propósito: la fecha es la de hoy
    y el tipo sale de la factura (ND A/B/C = 2/7/12; si es FCE, 202/207/212).
    """

    model_config = ConfigDict(extra="forbid")

    motivo: str = Field(min_length=3, max_length=500)
    importe: Decimal = Field(gt=0, max_digits=14, decimal_places=2)

    _importe_sin_booleanos = field_validator("importe", mode="before")(_sin_booleanos)

    @field_validator("motivo")
    @classmethod
    def _sin_espacios(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 3:
            raise ValueError("el motivo tiene que decir por que se emite la nota (3 letras o mas)")
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
    #: No agrupa órdenes: una factura directa o una nota de débito (ADR-048). La pantalla no espera sus órdenes y el
    #: gate de F5 no la compara contra ellas.
    sin_ordenes: bool = False

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
    #: Las notas de débito que cuelgan de este comprobante (ADR-048). No acreditan: suman a la deuda del cliente.
    notas_debito: list[ComprobanteOut] = []
    #: Lo que acreditan sus notas con CAE y lo que queda por acreditar, **calculado por el motor**
    #: (`saldo_acreditable`). `None` donde no hay nota posible: sin CAE, anulado o una nota.
    acreditado: Decimal | None = None
    saldo_acreditable: Decimal | None = None


class TotalDeComprobantes(BaseModel):
    """Lo facturado en el rango, contado por los dos lados.

    - Por **comprobantes**: suma de los encabezados **de los que agrupan órdenes**.
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
    #: Lo que no tiene órdenes contra las que compararse (ADR-048): las facturas directas y las notas de débito,
    #: **netas de las notas de crédito de las facturas directas**. Va aparte del gate: no puede coincidir con unas
    #: órdenes que no tiene, y mezclarlo lo pondría en rojo siempre.
    cantidad_sin_ordenes: int = 0
    total_sin_ordenes: Decimal = Decimal("0.00")
