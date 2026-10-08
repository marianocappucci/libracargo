"""Esquemas de la orden de carga.

> 🔑 **`iva` y `total` no entran por el cuerpo: los calcula el servidor.**
> En el legado la alícuota estaba fija en el JavaScript de la pantalla, así que
> el importe que llegaba ya venía calculado por el cliente. Aceptarlo hace que
> un total equivocado sea un pedido válido — y el legado tiene 22.588
> movimientos donde eso no se puede auditar. Acá entran `tarifa` y
> `alicuota_iva`, y el resto sale de ahí.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EstadoOrden, EtapaOrden

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


class CamposDeOrden(BaseModel):
    """Los campos que comparten la entrada y la salida, **sin ninguna regla**.

    🔴 Existe porque `OrdenOut` heredaba de `OrdenIn`, y con la herencia se
    llevaba también su validador. Una regla de entrada aplicada a la salida no
    valida nada: rechaza lo que **ya está guardado**. Con las 33 órdenes
    migradas que salen y llegan a la misma localidad —legítimas, ver ADR-015—,
    `GET /api/ordenes` devolvía **500** con el límite por omisión; con
    `limite=3` andaba, porque esas filas no entraban en la página. La pantalla
    de órdenes quedaba inutilizable justo sobre los datos del cliente.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    fecha: date
    cliente_id: int
    origen_id: int
    destino_id: int
    fletero_id: int | None = None
    chofer_id: int | None = None
    vehiculo_id: int | None = None
    tipo_carga_id: int | None = None

    remito: str | None = Field(default=None, max_length=30)
    cantidad: Decimal | None = Field(default=None, ge=0)
    unidad: str | None = Field(default=None, max_length=20)

    tarifa: Decimal = Field(default=Decimal(0), ge=0)
    alicuota_iva: Decimal = Field(default=ALICUOTA_DEFAULT, ge=0, le=100)
    comision: Decimal = Field(default=Decimal(0), ge=0)
    observaciones: str | None = None

    #: La etapa del viaje (ADR-037), aparte del estado de facturación.
    etapa: EtapaOrden = EtapaOrden.ASIGNADA
    #: Kilos de la pesada al cargar y del ticket al descargar. Enteros.
    kg_bruto_carga: int | None = Field(default=None, ge=0)
    kg_tara_carga: int | None = Field(default=None, ge=0)
    kg_neto_carga: int | None = Field(default=None, ge=0)
    kg_bruto_descarga: int | None = Field(default=None, ge=0)
    kg_tara_descarga: int | None = Field(default=None, ge=0)
    kg_neto_descarga: int | None = Field(default=None, ge=0)
    #: Los km del viaje y la tarifa por tonelada pactada (ADR-038). Se proponen desde el tarifario; varían por viaje.
    km: int | None = Field(default=None, ge=1, le=99999)
    tarifa_tonelada: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

class OrdenIn(CamposDeOrden):
    """Lo que se acepta al crear o modificar. Acá sí van las reglas."""

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

    @model_validator(mode="after")
    def _neto_de_bruto_y_tara(self):
        """Con bruto y tara, el neto es la resta y lo pone el servidor; uno distinto que venga es un error de carga.

        Sin bruto o sin tara, el neto se acepta solo: a veces es lo único que se sabe (lo que dice el ticket).
        """
        for tramo in ("carga", "descarga"):
            bruto, tara = getattr(self, f"kg_bruto_{tramo}"), getattr(self, f"kg_tara_{tramo}")
            neto = getattr(self, f"kg_neto_{tramo}")
            if bruto is None or tara is None:
                continue
            if tara > bruto:
                raise ValueError(
                    f"los kilos de {tramo}: la tara ({tara}) no puede ser mayor que el bruto ({bruto})")
            if neto is not None and neto != bruto - tara:
                raise ValueError(
                    f"los kilos de {tramo}: el neto ({neto}) no es bruto menos tara "
                    f"({bruto} - {tara} = {bruto - tara})")
            setattr(self, f"kg_neto_{tramo}", bruto - tara)
        return self


class EtapaIn(BaseModel):
    etapa: EtapaOrden


class OrdenOut(CamposDeOrden):
    """Lo que se devuelve. **No hereda de `OrdenIn` a propósito**: lo que ya está
    en la base se muestra tal como está, y lo que no se pueda cargar de nuevo se
    rechaza al entrar, no al salir."""

    id: int
    estado: EstadoOrden
    comprobante_id: int | None = None
    iva: Decimal
    total: Decimal
    cantidad_legado: str | None = None
    origen_legado: str | None = None


class AdjuntoOut(BaseModel):
    """Un adjunto sin su contenido: el archivo se baja aparte."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    orden_id: int
    nombre: str
    tipo_contenido: str
    tamanio: int
    created_at: datetime
