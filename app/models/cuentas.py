"""Cuentas corrientes y caja."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    TypeDecorator,
    join,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column

from app.models.base import Auditable, Base
from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja
from app.models.operacion import MOTOR, _Dinero, _Fecha

# ── La caja vive en `caja_movimientos`, la tabla del motor ─────────────────
#
# Hasta la revisión `0032` este producto tenía su propia tabla `movimientos_caja`,
# que ningún otro producto ni el motor veían. Desde ahí cada movimiento es una fila
# de `caja_movimientos` de LibraCore (los ganchos de caja de su ADR-076, la
# columna `origen` con la que la caja de un nodo sube al central), con lo propio de
# acá —el tercero, la descripción, el recibo— en `movimientos_caja_cargo`, con el
# **mismo id** (ADR-055). Es lo mismo que la `0017` hizo con la cuenta corriente.
#
# `MovimientoCaja` sigue siendo la clase que leen las pantallas, los reportes y los
# saldos, mapeada sobre la unión de las dos tablas. **Escribe el motor**
# (`libracore.db.caja`), desde `app/servicios/caja.py`.


class _Tipo(TypeDecorator):
    """Ingreso o egreso: en el motor es texto, acá el enum de siempre."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else TipoMovimientoCaja(value).value

    def process_result_value(self, value, dialect):
        return None if value is None else TipoMovimientoCaja(value)


class _Medio(TypeDecorator):
    """El medio de pago: en el motor es texto, acá el enum de este producto."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else MedioPago(value).value

    def process_result_value(self, value, dialect):
        return None if value is None else MedioPago(value)


class _Marca(TypeDecorator):
    """Una marca que el motor guarda como entero (`0`/`1`) y acá se lee como booleano.

    🔴 Por ser un entero en la base, **`.is_(False)` no sirve**: PostgreSQL rechaza
    `anulado IS false` sobre un `integer`. Se compara con `== 0`.
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int(bool(value))

    def process_result_value(self, value, dialect):
        return None if value is None else bool(value)


caja_movimientos = Table(
    "caja_movimientos", MOTOR,
    Column("id", BigInteger, primary_key=True),
    Column("fecha", _Fecha, nullable=False),
    Column("tipo", _Tipo, nullable=False),
    Column("concepto", Text, nullable=False),
    Column("monto", _Dinero, nullable=False),
    Column("medio_pago", _Medio),
    Column("anulado", _Marca, nullable=False),
    # De qué nodo vino la fila (ADR-076 del motor). No se mapean: las lee `servicios/caja.py`
    # para no dejar que el central edite lo que el nodo es dueño.
    Column("origen", Text),
    Column("origen_id", Integer),
)


class MovimientoCajaCargo(Base, Auditable):
    """Lo que sólo este producto sabe de un movimiento de caja. Una fila por cada fila de `caja_movimientos`.

    El tercero con su FK, la descripción larga, el número de recibo y de dónde salió en
    el legado. La fecha, el tipo, el concepto, el importe, el medio de pago y la marca
    de anulado están en el motor: son lo que el central, el arqueo y los ganchos ven.
    """

    __tablename__ = "movimientos_caja_cargo"

    movimiento_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(caja_movimientos.c.id, ondelete="RESTRICT", name="fk_movimientos_caja_cargo_movimiento"),
        primary_key=True, autoincrement=False,
    )
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    tercero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True
    )
    recibo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_caja_cargo_tercero", "tercero_id"),
        Index("ix_caja_cargo_origen_legado", "origen_legado", unique=True),
    )


_cargo_caja = MovimientoCajaCargo.__table__


class MovimientoCaja(Base):
    """Cobros y pagos. Reemplaza a `novedades`.

    Es la unión de `caja_movimientos` (el movimiento de la familia) y
    `movimientos_caja_cargo` (lo propio). Se **lee** como siempre; se **registra,
    se corrige y se anula** por `app/servicios/caja.py`, que lo hace con el motor.

    Un movimiento de caja genera su contrapartida en `cc_asientos` **dentro de la
    misma transacción**: en el legado eran `INSERT` sueltos y si el segundo
    fallaba, el primero ya había quedado grabado.

    Anular **no borra**: el movimiento queda, deja de contar en los totales y su
    asiento se revierte con una contrapartida (`elimina_novedad.php` hacía tres
    `DELETE` sueltos y el cobro desaparecía sin dejar rastro).
    """

    __table__ = join(caja_movimientos, _cargo_caja, caja_movimientos.c.id == _cargo_caja.c.movimiento_id)

    id = column_property(caja_movimientos.c.id, _cargo_caja.c.movimiento_id)
    #: El nombre de siempre de este producto sobre `monto` del motor.
    importe = column_property(caja_movimientos.c.monto)

    __mapper_args__ = {"exclude_properties": ["origen", "origen_id"]}


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
    #: El movimiento de la caja del motor (`0032`): el mismo id que tenía en la caja propia.
    movimiento_caja_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(caja_movimientos.c.id, ondelete="RESTRICT", name="fk_movimientos_cuenta_cargo_movimiento_caja"),
        nullable=True,
    )
    #: El gasto de proveedor que lo genero. Un gasto deja DOS asientos con el
    #: mismo `gasto_id`: el del proveedor al debe y el del fletero al haber.
    gasto_id: Mapped[int | None] = mapped_column(
        ForeignKey("gastos_de_proveedor.id", ondelete="RESTRICT"), nullable=True
    )
    # 🔑 `origen_nodo` y `origen_nodo_id` (`0034`, ADR-056) **no están en el modelo, a propósito**: de qué nodo vino un
    # asiento lo escribe y lo lee sólo el aplicador del central, con SQL (`servicios/aplicadores.py`); el dominio no los
    # necesita. Mapearlos haría que cada alta del ORM los nombrara en el `INSERT`, y una base migrada hasta antes de la
    # `0034` (los tests de las revisiones viejas) no los tiene. `migrations/env.py` los saca de la comparación.

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
