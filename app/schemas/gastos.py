"""Esquemas del gasto de proveedor."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GastoIn(BaseModel):
    """Lo que se puede mandar. `anulado` no está: se anula por su endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    fecha: date
    proveedor_id: int
    #: Obligatorio, y no por comodidad del modelo: en el legado los 2.799 gastos
    #: lo tienen. Uno que no se le descuenta a nadie es un gasto general de la
    #: agencia y va por caja.
    fletero_id: int
    comprobante: str | None = Field(default=None, max_length=30)
    descripcion: str = Field(min_length=1)
    importe: Decimal = Field(gt=0)


class GastoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    proveedor_id: int
    fletero_id: int
    comprobante: str | None
    descripcion: str
    importe: Decimal
    anulado: bool
