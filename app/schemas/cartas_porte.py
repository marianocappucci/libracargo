"""Esquemas de las Cartas de Porte Electrónicas (ADR-036)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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
