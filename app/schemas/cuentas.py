"""Esquemas de caja y cuenta corriente."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja


class MovimientoCajaIn(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    fecha: date
    tipo: TipoMovimientoCaja
    concepto: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    tercero_id: int | None = None
    # No se guarda en `movimientos_caja`: dice a CUÁL de las cuentas del tercero
    # va la contrapartida. Un mismo tercero puede ser cliente y fletero a la
    # vez, así que sin esto no se sabe qué cuenta se está moviendo.
    rol: RolCuenta | None = None
    importe: Decimal = Field(gt=0)
    medio_pago: MedioPago = MedioPago.EFECTIVO
    recibo: str | None = Field(default=None, max_length=30)


class MovimientoCajaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    tipo: TipoMovimientoCaja
    concepto: str
    descripcion: str | None
    tercero_id: int | None
    importe: Decimal
    medio_pago: MedioPago
    recibo: str | None
    anulado: bool


class MovimientoCuentaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    tercero_id: int
    rol: RolCuenta
    concepto: str
    descripcion: str | None
    debe: Decimal
    haber: Decimal
    orden_id: int | None
    comprobante_id: int | None
    movimiento_caja_id: int | None
    #: El cuarto origen posible de un asiento. Sale en la salida porque es lo
    #: que hace clickeable la linea en la cuenta corriente.
    gasto_id: int | None


class FilaDeCuenta(BaseModel):
    """Un movimiento con el saldo acumulado hasta esa fila."""

    movimiento: MovimientoCuentaOut
    saldo: Decimal


class ResumenDeCuenta(BaseModel):
    tercero_id: int
    rol: RolCuenta
    #: Agregado por la base con un `SUM`.
    saldo: Decimal
    #: El mismo número, acumulado fila por fila en Python. Se devuelven **los
    #: dos** a propósito: si difieren, el saldo depende de dónde se hizo la
    #: cuenta, y eso hay que poder verlo sin abrir la base.
    saldo_recorriendo: Decimal
    coinciden: bool
    movimientos: list[FilaDeCuenta]
