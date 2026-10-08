"""Esquemas del tarifario de referencia (ADR-038)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TarifarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vigencia: date
    nombre: str
    valor_estadia: Decimal | None
    filas: int = 0
    km_desde: int | None = None
    km_hasta: int | None = None


class ReferenciaOut(BaseModel):
    tarifario_id: int
    vigencia: date
    nombre: str
    km: int
    #: `null` si el tarifario no tiene ese km (no se extrapola).
    tarifa: Decimal | None
    valor_estadia: Decimal | None


class FilaOut(BaseModel):
    km: int
    tarifa: Decimal


class SugerenciaOut(BaseModel):
    porcentaje: Decimal
    orden_id: int
    fecha: date
    km: int
    tarifa_tonelada: Decimal
    tarifa_referencia: Decimal


class VistaPreviaOut(BaseModel):
    """Lo que se cargaría del archivo, sin guardar (`POST /api/tarifario/previsualizar`)."""

    vigencia: date | None
    nombre: str | None
    valor_estadia: Decimal | None
    filas: int
    km_desde: int
    km_hasta: int
    muestra: list[FilaOut]
    #: Si ya hay una edición con esa vigencia (cargarla la reemplaza entera).
    reemplaza: bool
