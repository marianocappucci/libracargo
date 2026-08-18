"""Órdenes de carga y comprobantes — el núcleo del negocio."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Anotable, Auditable, Base
from app.models.enums import EstadoOrden, TipoComprobante


class Comprobante(Base, Auditable):
    """Factura o nota de crédito emitida por una de las razones sociales propias.

    La numeración es única por razón social, tipo y punto de venta — en el
    legado la PK era `(factura_nro, factura_razonsocial)`, que no contemplaba
    ni el tipo ni el punto de venta.
    """

    __tablename__ = "comprobantes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razon_social_id: Mapped[int] = mapped_column(
        ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[TipoComprobante] = mapped_column(
        Enum(TipoComprobante, name="tipo_comprobante",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    punto_venta: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )

    # NUMERIC, nunca float: el legado sumaba `float(10,2)` sobre 22.588
    # movimientos y arrastraba el error de redondeo a los saldos.
    neto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    anulado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "razon_social_id",
            "tipo",
            "punto_venta",
            "numero",
            name="uq_comprobantes_numeracion",
        ),
        CheckConstraint("neto >= 0 AND iva >= 0 AND total >= 0", name="ck_comprobantes_signos"),
        Index("ix_comprobantes_fecha", "fecha"),
        Index("ix_comprobantes_cliente_fecha", "cliente_id", "fecha"),
        Index("ix_comprobantes_origen_legado", "origen_legado", unique=True),
    )


class OrdenCarga(Base, Auditable, Anotable):
    """Una orden de transporte: el cliente la pide, el fletero la hace.

    La comisión es la diferencia con la que vive la agencia, y por eso es una
    columna propia y no un margen que se recalcula.
    """

    __tablename__ = "ordenes_carga"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )
    origen_id: Mapped[int] = mapped_column(
        ForeignKey("localidades.id", ondelete="RESTRICT"), nullable=False
    )
    destino_id: Mapped[int] = mapped_column(
        ForeignKey("localidades.id", ondelete="RESTRICT"), nullable=False
    )
    fletero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True
    )
    chofer_id: Mapped[int | None] = mapped_column(
        ForeignKey("choferes.id", ondelete="RESTRICT"), nullable=True
    )
    vehiculo_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehiculos.id", ondelete="RESTRICT"), nullable=True
    )
    tipo_carga_id: Mapped[int | None] = mapped_column(
        ForeignKey("tipos_carga.id", ondelete="RESTRICT"), nullable=True
    )

    remito: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # En el legado la cantidad era `varchar(20)` y no se podía totalizar.
    # `cantidad_legado` conserva el texto original cuando no parsea a número.
    cantidad: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cantidad_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    tarifa: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    alicuota_iva: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("21.00")
    )
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    comision: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    estado: Mapped[EstadoOrden] = mapped_column(
        Enum(EstadoOrden, name="estado_orden",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=EstadoOrden.PENDIENTE,
    )
    razon_social_id: Mapped[int | None] = mapped_column(
        ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=True
    )
    # FK real, no el número de factura copiado a mano como hacía el legado.
    comprobante_id: Mapped[int | None] = mapped_column(
        ForeignKey("comprobantes.id", ondelete="RESTRICT"), nullable=True
    )
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    comprobante: Mapped[Comprobante | None] = relationship("Comprobante", lazy="raise")

    __table_args__ = (
        CheckConstraint("origen_id <> destino_id", name="ck_ordenes_origen_distinto_destino"),
        CheckConstraint("tarifa >= 0 AND total >= 0", name="ck_ordenes_importes_no_negativos"),
        CheckConstraint(
            "alicuota_iva >= 0 AND alicuota_iva <= 100", name="ck_ordenes_alicuota"
        ),
        # Una orden facturada tiene comprobante; una pendiente no puede tenerlo.
        CheckConstraint(
            "(estado = 'facturada' AND comprobante_id IS NOT NULL) "
            "OR (estado <> 'facturada' AND comprobante_id IS NULL)",
            name="ck_ordenes_facturada_con_comprobante",
        ),
        Index("ix_ordenes_fecha", "fecha"),
        Index("ix_ordenes_cliente_fecha", "cliente_id", "fecha"),
        Index("ix_ordenes_fletero_fecha", "fletero_id", "fecha"),
        Index("ix_ordenes_estado", "estado"),
        Index("ix_ordenes_comprobante", "comprobante_id"),
        Index("ix_ordenes_remito", "remito"),
        Index("ix_ordenes_origen_legado", "origen_legado", unique=True),
    )
