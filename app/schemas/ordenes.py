"""Esquemas de la orden de carga.

> 🔑 **`iva` y `total` no entran por el cuerpo: los calcula el servidor.**
> En el legado la alícuota estaba fija en el JavaScript de la pantalla, así que
> el importe que llegaba ya venía calculado por el cliente. Aceptarlo hace que
> un total equivocado sea un pedido válido — y el legado tiene 22.588
> movimientos donde eso no se puede auditar. Acá entran `tarifa` y
> `alicuota_iva`, y el resto sale de ahí.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EstadoOrden

#: La alícuota general. El legado la tenía fija; acá es un default editable,
#: porque el relevamiento con el cliente sobre operaciones con otra alícuota
#: sigue abierto.
ALICUOTA_DEFAULT = Decimal("21.00")


def calcular_importes(tarifa: Decimal, alicuota: Decimal) -> tuple[Decimal, Decimal]:
    """`(iva, total)` redondeados a dos decimales.

    `ROUND_HALF_UP` explícito: el default de Python es `ROUND_HALF_EVEN`
    —redondeo bancario—, que sobre importes terminados en 5 da un centavo
    distinto del que espera cualquiera que rehaga la cuenta a mano.
    """
    centavo = Decimal("0.01")
    iva = (tarifa * alicuota / Decimal(100)).quantize(centavo, rounding=ROUND_HALF_UP)
    return iva, (tarifa + iva).quantize(centavo, rounding=ROUND_HALF_UP)


class OrdenIn(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    fecha: date
    cliente_id: int
    origen_id: int
    destino_id: int
    fletero_id: int | None = None
    chofer_id: int | None = None
    vehiculo_id: int | None = None
    tipo_carga_id: int | None = None
    razon_social_id: int | None = None

    remito: str | None = Field(default=None, max_length=30)
    cantidad: Decimal | None = Field(default=None, ge=0)
    unidad: str | None = Field(default=None, max_length=20)

    tarifa: Decimal = Field(default=Decimal(0), ge=0)
    alicuota_iva: Decimal = Field(default=ALICUOTA_DEFAULT, ge=0, le=100)
    comision: Decimal = Field(default=Decimal(0), ge=0)
    observaciones: str | None = None

    @model_validator(mode="after")
    def _origen_distinto_de_destino(self):
        """La misma regla que el `CHECK` de la base, adelantada.

        Sin esto el rechazo llega igual —la base no deja— pero como un 500 con
        el nombre de una restricción, en vez de un 422 que dice cuál es el
        problema. La regla vive en los dos lados a propósito: la base es la que
        no puede mentir, y esta es la que se puede explicar.
        """
        if self.origen_id == self.destino_id:
            raise ValueError("el origen y el destino no pueden ser el mismo lugar")
        return self


class OrdenOut(OrdenIn):
    id: int
    estado: EstadoOrden
    comprobante_id: int | None = None
    iva: Decimal
    total: Decimal
    cantidad_legado: str | None = None
    origen_legado: str | None = None
