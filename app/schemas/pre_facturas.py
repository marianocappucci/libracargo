"""Esquemas de la pre factura: lo que elige el operador, y nada de lo que sale de las órdenes.

> 🔑 **Los ítems y los importes no entran por el cuerpo: salen de las órdenes.** Es la regla de los
> comprobantes (ver `app/schemas/comprobantes.py`) llevada a la pre factura: aceptar ítems del cliente
> permitiría una pre factura que diga un importe y sus órdenes otro, que es justo lo que el gate de F5
> tiene que poder descartar.
>
> Tampoco entran **punto de venta ni número**: la pre factura tiene un número interno (`PF-0001`) que
> pone el motor, y el de la factura lo pone ARCA.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TipoComprobante


class PreFacturaEditarIn(BaseModel):
    """Los datos de una pre factura que se pueden cambiar mientras no esté facturada ni anulada.

    `extra="forbid"`: un cuerpo con `items`, `punto_venta` o `numero` es un cliente que cree que los puede
    mandar, y callarlo dejaría que el error se descubra en la factura.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tipo: TipoComprobante
    fecha: date
    #: Sólo la FCE lo lleva, y toda FCE lo exige (lo valida `servicios.pre_facturas`).
    fecha_vencimiento_pago: date | None = None
    #: Sólo la FCE: en qué cuenta se cobra, por su CBU **o su alias** (libracore ADR-040). `""` o ausente es la
    #: predeterminada de la configuración de ARCA; una que no está cargada la rechaza el motor (422).
    fce_cbu: str | None = Field(default=None, max_length=40)
    orden_ids: list[int] = Field(min_length=1)
    observaciones: str = Field(default="", max_length=500)

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


class PreFacturaIn(PreFacturaEditarIn):
    """Generar la pre factura: lo mismo que se edita, más de qué cliente es."""

    cliente_id: int


class FacturarPreFacturaIn(BaseModel):
    """Facturar por ARCA. Sin cuerpo, el comprobante sale con la fecha de la pre factura.

    La fecha se puede pasar porque a los días de generarla ARCA puede no aceptar la vieja.
    """

    model_config = ConfigDict(extra="forbid")

    fecha: date | None = None
