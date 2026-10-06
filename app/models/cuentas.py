"""Cuentas corrientes y caja."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    TypeDecorator,
    false,
    join,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column

from app.models.base import Auditable, Base
from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja
from app.models.operacion import MOTOR, _Dinero, _Fecha


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
    #: Anular no borra: el movimiento queda, deja de contar en los totales
    #: y su asiento se revierte con una contrapartida. En el legado,
    #: `elimina_novedad.php` hacia tres DELETE sueltos y el cobro
    #: desaparecia sin dejar rastro.
    anulado: Mapped[bool] = mapped_column(
        # `server_default` ademas del `default` de Python: el ETL de migracion
        # escribe por `COPY` sin nombrar esta columna, y ahi el default de la
        # aplicacion no corre. Tiene que decir lo mismo que la migracion 0008.
        Boolean, nullable=False, default=False, server_default=false()
    )
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


# ── La cuenta corriente vive en el libro de terceros del motor ─────────────
#
# Hasta la revisión `0017` este producto tenía su propia tabla
# `movimientos_cuenta`. Desde ahí cada asiento es una fila de `cc_asientos`, el
# libro de cuenta corriente de terceros de LibraCore (su ADR-026), con lo propio
# de acá —de qué orden, cobro o gasto salió— en `movimientos_cuenta_cargo`, con
# el **mismo id** (ADR-031). `MovimientoCuenta` sigue siendo la clase que leen los
# saldos y los reportes, mapeada sobre la unión de las dos tablas. **Escribe el
# motor**, desde `app/servicios/cuentas.py`.


class _Rol(TypeDecorator):
    """El rol de la cuenta: en el motor es texto, acá el enum de siempre."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else RolCuenta(value).value

    def process_result_value(self, value, dialect):
        return None if value is None else RolCuenta(value)


cc_asientos = Table(
    "cc_asientos", MOTOR,
    Column("id", BigInteger, primary_key=True),
    Column("fecha", _Fecha, nullable=False),
    Column("tercero_id", Integer, nullable=False),
    Column("rol", _Rol, nullable=False),
    Column("concepto", Text, nullable=False),
    Column("descripcion", Text),
    Column("debe", _Dinero, nullable=False),
    Column("haber", _Dinero, nullable=False),
    Column("factura_id", BigInteger),
    Column("contrapartida_de", BigInteger),
    Column("origen_legado", Text),
)


class MovimientoCuentaCargo(Base, Auditable):
    """De qué documento de este producto salió cada asiento del libro del motor."""

    __tablename__ = "movimientos_cuenta_cargo"

    asiento_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(cc_asientos.c.id, ondelete="RESTRICT", name="fk_movimientos_cuenta_cargo_asiento"),
        primary_key=True, autoincrement=False,
    )
    orden_id: Mapped[int | None] = mapped_column(
        ForeignKey("ordenes_carga.id", ondelete="RESTRICT"), nullable=True
    )
    movimiento_caja_id: Mapped[int | None] = mapped_column(
        ForeignKey("movimientos_caja.id", ondelete="RESTRICT"), nullable=True
    )
    #: El gasto de proveedor que lo genero. Un gasto deja DOS asientos con el
    #: mismo `gasto_id`: el del proveedor al debe y el del fletero al haber.
    gasto_id: Mapped[int | None] = mapped_column(
        ForeignKey("gastos_de_proveedor.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("ix_cuenta_cargo_orden", "orden_id"),
        Index("ix_cuenta_cargo_caja", "movimiento_caja_id"),
        Index("ix_cuenta_cargo_gasto", "gasto_id"),
    )


_cargo_cuenta = MovimientoCuentaCargo.__table__


class MovimientoCuenta(Base):
    """Las tres cuentas corrientes —cliente, fletero y proveedor—, en el libro del motor.

    El legado tenía `clientectacte`, `fleteroctacte` y `ctacteprov`, con la
    misma forma. Acá la cuenta es el par **(tercero, rol)**.

    Sin saldo materializado: con el índice sobre `(tercero_id, rol, fecha)`,
    sumar 22.588 filas en PostgreSQL es instantáneo, y una cache de saldo es
    una cosa más que se puede desincronizar.

    Se **lee** como siempre; se **escribe** por `app/servicios/cuentas.py`, que
    lo hace con el motor (`libracore.db.libro_de_terceros`).
    """

    __table__ = join(cc_asientos, _cargo_cuenta, cc_asientos.c.id == _cargo_cuenta.c.asiento_id)

    id = column_property(cc_asientos.c.id, _cargo_cuenta.c.asiento_id)
    #: El comprobante del asiento, una fila de `facturas` del motor.
    comprobante_id = column_property(cc_asientos.c.factura_id)

    __mapper_args__ = {"exclude_properties": ["contrapartida_de"]}
