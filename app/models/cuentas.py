"""Cuentas corrientes y caja."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Auditable, Base
from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja


class MovimientoCaja(Base, Auditable):
    """Cobros y pagos. Reemplaza a `novedades`.

    Un movimiento de caja genera su contrapartida en `movimientos_cuenta`
    **dentro de la misma transacción**: en el legado eran `INSERT` sueltos y
    si el segundo fallaba, el primero ya había quedado grabado.
    """

    __tablename__ = "movimientos_caja"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    tipo: Mapped[TipoMovimientoCaja] = mapped_column(
        Enum(TipoMovimientoCaja, name="tipo_movimiento_caja",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    concepto: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    tercero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True
    )
    importe: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    medio_pago: Mapped[MedioPago] = mapped_column(
        Enum(MedioPago, name="medio_pago",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=MedioPago.EFECTIVO,
    )
    recibo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        # Mismo escape, por lo mismo: 6 movimientos del legado tienen
        # descripción real y ningún importe cargado. Ver ADR-015.
        CheckConstraint(
            "importe > 0 OR origen_legado IS NOT NULL", name="ck_caja_importe_positivo"
        ),
        Index("ix_caja_fecha", "fecha"),
        Index("ix_caja_tercero_fecha", "tercero_id", "fecha"),
        Index("ix_caja_origen_legado", "origen_legado", unique=True),
    )


class MovimientoCuenta(Base, Auditable):
    """Las tres cuentas corrientes, en una sola tabla.

    El legado tenía `clientectacte`, `fleteroctacte` y `ctacteprov`, con la
    misma forma. Acá la cuenta es el par **(tercero, rol)**.

    Sin saldo materializado: con el índice sobre `(tercero_id, rol, fecha)`,
    sumar 22.588 filas en PostgreSQL es instantáneo, y una cache de saldo es
    una cosa más que se puede desincronizar.
    """

    __tablename__ = "movimientos_cuenta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    tercero_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )
    rol: Mapped[RolCuenta] = mapped_column(
        Enum(RolCuenta, name="rol_cuenta",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    concepto: Mapped[str] = mapped_column(String(120), nullable=False)

    # `Text`, sin límite. En el legado esta columna era `varchar(50)` y
    # guardaba "origen - destino - cantidad - tipo - remito" concatenado:
    # MySQL la truncaba en silencio.
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    debe: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    haber: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    orden_id: Mapped[int | None] = mapped_column(
        ForeignKey("ordenes_carga.id", ondelete="RESTRICT"), nullable=True
    )
    comprobante_id: Mapped[int | None] = mapped_column(
        ForeignKey("comprobantes.id", ondelete="RESTRICT"), nullable=True
    )
    movimiento_caja_id: Mapped[int | None] = mapped_column(
        ForeignKey("movimientos_caja.id", ondelete="RESTRICT"), nullable=True
    )
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint("debe >= 0 AND haber >= 0", name="ck_cuenta_signos"),
        # Un asiento mueve una columna o la otra, nunca las dos ni ninguna.
        # El escape por `origen_legado` es para el histórico: el legado tiene 36
        # asientos con las dos en cero, y ponerles un importe sería inventarlo.
        # Ver ADR-015 y la migración 0003.
        CheckConstraint(
            "((debe > 0 AND haber = 0) OR (haber > 0 AND debe = 0)) "
            "OR origen_legado IS NOT NULL",
            name="ck_cuenta_debe_o_haber",
        ),
        Index("ix_cuenta_saldo", "tercero_id", "rol", "fecha"),
        Index("ix_cuenta_orden", "orden_id"),
        Index("ix_cuenta_comprobante", "comprobante_id"),
        Index("ix_cuenta_caja", "movimiento_caja_id"),
        Index("ix_cuenta_origen_legado", "origen_legado", unique=True),
    )
