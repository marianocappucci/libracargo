"""Esquemas de las Cartas de Porte Electrónicas (ADR-036)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from libracore.arca_wsfe import cuit_con_verificador_valido
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.servicios.emision_cpe import INTERVINIENTES


class ConsultaIn(BaseModel):
    ctg: int = Field(gt=0)
    #: Por quién se consulta. Obligatorio y sin valor por defecto (ver `servicios.cartas_porte`).
    cuit_representada: str = Field(min_length=11, max_length=13)


class TraerIn(BaseModel):
    ctgs: list[int] = Field(min_length=1)
    cuit_representada: str = Field(min_length=11, max_length=13)
    orden_carga_id: int | None = None


class VincularIn(BaseModel):
    orden_carga_id: int | None


class Representado(BaseModel):
    cuit: str
    nombre: str | None


class RepresentadosOut(BaseModel):
    ambiente: str
    cuits: list[Representado]


class Parte(BaseModel):
    """Un CUIT de la CPE con el nombre del tercero cargado, si lo hay."""

    cuit: str | None
    nombre: str | None = None


class CartaPorteOut(BaseModel):
    """Una CPE: la guardada (`id`) o la vista previa de ARCA (`id` vacío)."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    nro_ctg: int
    numero: str
    estado: str
    estado_descripcion: str
    fecha_emision: datetime | None
    fecha_vencimiento: datetime | None
    fecha_partida: datetime | None
    #: Desde cuándo está en ese estado (para «Anulada desde…»).
    fecha_inicio_estado: datetime | None = None
    cuit_representada: str
    ambiente: str
    transportista: Parte
    pagador_flete: Parte
    chofer: Parte
    origen: Parte
    destino: Parte
    destinatario: Parte
    dominios: list[str]
    cod_grano: int | None
    cosecha: int | None
    peso_bruto: int | None
    peso_tara: int | None
    peso_neto: int | None
    peso_bruto_descarga: int | None
    peso_tara_descarga: int | None
    peso_neto_descarga: int | None
    cod_provincia_origen: int | None
    cod_localidad_origen: int | None
    cod_provincia_destino: int | None
    cod_localidad_destino: int | None
    planta_destino: int | None
    #: La emitió LibraCargo (ADR-043): sólo esas se pueden anular desde acá.
    emitida: bool = False
    km: int | None
    tarifa: Decimal | None
    tiene_pdf: bool
    tiene_descarga: bool
    consultada_en: datetime | None = None
    orden_carga_id: int | None = None
    #: Si la vista previa corresponde a una CPE ya guardada.
    guardada_id: int | None = None


class ResultadoTraer(BaseModel):
    ctg: int
    id: int | None
    error: str | None


class ResumenActualizar(BaseModel):
    actualizadas: int
    errores: list[dict]


# ── Titulares (ADR-044) ────────────────────────────────────────────────────

def _cuit_de_once(v):
    """Los once dígitos de un CUIT (acepta guiones). `None` y vacío pasan como ausencia."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    d = "".join(c for c in str(v) if c.isdigit())
    if len(d) != 11 or not cuit_con_verificador_valido(d):
        raise ValueError("el CUIT tiene que tener 11 dígitos y un dígito verificador válido")
    return d


class TitularIn(BaseModel):
    """Alta de un titular. La razón social puede faltar si el CUIT es de una entidad cargada: se toma de ella."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cuit: str
    razon_social: str | None = Field(default=None, max_length=120)
    tercero_id: int | None = None
    emite: Literal["nosotros", "titular"] = "nosotros"
    activo: bool = True
    notas: str | None = Field(default=None, max_length=2000)

    @field_validator("cuit", mode="before")
    @classmethod
    def _cuit(cls, v):
        d = _cuit_de_once(v)
        if d is None:
            raise ValueError("falta el CUIT")
        return d


class TitularEdicion(BaseModel):
    """Edición: el CUIT es la identidad del titular y no se cambia (se da de baja y se carga el otro)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    razon_social: str = Field(min_length=1, max_length=120)
    tercero_id: int | None = None
    emite: Literal["nosotros", "titular"]
    activo: bool
    notas: str | None = Field(default=None, max_length=2000)


class _OrigenPlantilla(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["campo", "planta"] = "campo"
    cod_provincia: int | None = Field(default=None, ge=0)
    cod_localidad: int | None = Field(default=None, ge=0)
    planta: int | None = Field(default=None, ge=0)
    renspa: str | None = Field(default=None, max_length=30)


class _DestinoPlantilla(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cuit: str | None = None
    cod_provincia: int | None = Field(default=None, ge=0)
    cod_localidad: int | None = Field(default=None, ge=0)
    planta: int | None = Field(default=None, ge=0)
    es_campo: bool = False

    _cuit = field_validator("cuit", mode="before")(_cuit_de_once)


class PlantillaIn(BaseModel):
    """Los datos habituales de un titular, con las mismas claves que guarda y lee la emisión (`CAMPOS_DE_PLANTILLA`).

    Las reglas son las de `SolicitudCpe.problemas()` del motor, pero cada dato es opcional: una plantilla puede ser
    parcial, y lo que falte lo completa quien emite. Una clave desconocida es un 422 y no se guarda en silencio.
    """

    model_config = ConfigDict(extra="forbid")

    sucursal: int | None = Field(default=None, ge=1, le=99999)
    origen: _OrigenPlantilla | None = None
    cod_grano: int | None = Field(default=None, ge=0)
    cosecha: int | None = Field(default=None, ge=0, le=9999)
    destino: _DestinoPlantilla | None = None
    cuit_destinatario: str | None = None
    intervinientes: dict[str, str | None] = Field(default_factory=dict)
    cuit_remitente_comercial_productor: str | None = None
    mercaderia_fumigada: bool | None = None
    km: int | None = Field(default=None, ge=1, le=99999)
    observaciones: str | None = Field(default=None, max_length=2000)

    _cuits = field_validator("cuit_destinatario", "cuit_remitente_comercial_productor", mode="before")(_cuit_de_once)

    @field_validator("intervinientes")
    @classmethod
    def _intervinientes(cls, v: dict[str, str | None]) -> dict[str, str]:
        desconocidos = sorted(set(v) - set(INTERVINIENTES))
        if desconocidos:
            raise ValueError(f"interviniente desconocido: {', '.join(desconocidos)}")
        return {k: _cuit_de_once(c) for k, c in v.items() if c not in (None, "")}


class PlantillaPut(BaseModel):
    datos: PlantillaIn
