"""Maestros: terceros, localidades, choferes, vehículos, razones sociales."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Anotable, Auditable, Base
from app.models.enums import CondicionIVA


class Tercero(Base, Auditable, Anotable):
    """Cliente, fletero y/o proveedor — los tres roles en una sola tabla.

    En el legado eran tres tablas con **las mismas 13 columnas**: el mismo
    formulario copiado tres veces. Los roles son atributos porque en los datos
    reales ya se cruzan.

    > La migración desde Suitrans **no deduplica**: los 276 registros entran
    > como 276 terceros. Fusionar por CUIT durante la carga es la forma más
    > rápida de romperle las tres cuentas corrientes a un cliente real; la
    > fusión va después, asistida, con el reporte de CUITs repetidos.
    """

    __tablename__ = "terceros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razon_social: Mapped[str] = mapped_column(String(120), nullable=False)
    cuit: Mapped[str | None] = mapped_column(String(13), nullable=True)
    condicion_iva: Mapped[CondicionIVA] = mapped_column(
        Enum(CondicionIVA, name="condicion_iva",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CondicionIVA.NO_CATEGORIZADO,
    )

    es_cliente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    es_fletero: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    es_proveedor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    direccion: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Texto, no entero: el CPA argentino (`B6600AAA`) no entra en un int.
    codigo_postal: Mapped[str | None] = mapped_column(String(12), nullable=True)
    localidad: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provincia: Mapped[str | None] = mapped_column(String(60), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    celular: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contacto: Mapped[str | None] = mapped_column(String(80), nullable=True)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Trazabilidad de la migración: id del maestro viejo, para poder auditar.
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "es_cliente OR es_fletero OR es_proveedor",
            name="ck_terceros_al_menos_un_rol",
        ),
        Index("ix_terceros_razon_social", "razon_social"),
        Index("ix_terceros_cuit", "cuit"),
        Index("ix_terceros_es_cliente", "es_cliente", postgresql_where="es_cliente"),
        Index("ix_terceros_es_fletero", "es_fletero", postgresql_where="es_fletero"),
        Index("ix_terceros_origen_legado", "origen_legado", unique=True),
    )


class Localidad(Base, Auditable):
    """Orígenes y destinos, unificados.

    El legado tenía `origen` (47 filas) y `destino` (100), con los mismos
    nombres repetidos en las dos tablas.
    """

    __tablename__ = "localidades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    provincia: Mapped[str | None] = mapped_column(String(60), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("nombre", name="uq_localidades_nombre"),)


class Chofer(Base, Auditable, Anotable):
    """El chofer ya no 'tiene' un chasis: eso es del vehículo."""

    __tablename__ = "choferes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    dni: Mapped[str | None] = mapped_column(String(15), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fletero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    fletero: Mapped[Tercero | None] = relationship("Tercero", lazy="raise")

    __table_args__ = (
        Index("ix_choferes_fletero", "fletero_id"),
        Index("ix_choferes_nombre", "nombre"),
        Index("ix_choferes_origen_legado", "origen_legado", unique=True),
    )


class Vehiculo(Base, Auditable, Anotable):
    """Chasis y acoplado, que en el legado vivían dentro de `choferes`.

    Un chofer maneja distintos equipos y un equipo lo manejan distintos
    choferes: la relación no es de propiedad.
    """

    __tablename__ = "vehiculos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patente_chasis: Mapped[str] = mapped_column(String(12), nullable=False)
    patente_acoplado: Mapped[str | None] = mapped_column(String(12), nullable=True)
    fletero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "patente_chasis", "patente_acoplado", name="uq_vehiculos_equipo"
        ),
        Index("ix_vehiculos_fletero", "fletero_id"),
    )


class RazonSocial(Base, Auditable):
    """Las razones sociales propias con las que se factura.

    En el legado eran dos enteros sin tabla, hardcodeados en un `<select>`:
    `1 = Suitrans`, `2 = Mauricio`, más un `0` que usaba `bajarpendientes.php`.
    """

    __tablename__ = "razones_sociales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    cuit: Mapped[str | None] = mapped_column(String(13), nullable=True)
    condicion_iva: Mapped[CondicionIVA] = mapped_column(
        Enum(CondicionIVA, name="condicion_iva",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CondicionIVA.RESPONSABLE_INSCRIPTO,
    )
    punto_venta: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    codigo_legado: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("nombre", name="uq_razones_sociales_nombre"),
        UniqueConstraint("codigo_legado", name="uq_razones_sociales_codigo_legado"),
    )


class TipoCarga(Base, Auditable):
    """`carga_tipo varchar(50)` de texto libre pasa a maestro."""

    __tablename__ = "tipos_carga"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    unidad_default: Mapped[str | None] = mapped_column(String(20), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("nombre", name="uq_tipos_carga_nombre"),)
