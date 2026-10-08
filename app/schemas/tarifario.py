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
