"""Cartas de Porte Electrónicas (CPE) traídas de ARCA por su CTG (ADR-036).

Se guarda **lo que este producto usa**, tipado, y la respuesta de ARCA entera en `respuesta_arca` (sin el PDF, que
va aparte en `cartas_porte_pdf`): lo que hoy no interesa —la comercialización, los corredores— no se pierde.

Los CUIT se guardan **como vienen de ARCA** y no como FK a `terceros`: el chofer de la CPE no está en ningún maestro
con CUIT, y el pagador del flete puede no estar cargado todavía. Contra los maestros se cruzan al leer.

Una CPE puede existir sin orden (se cargó el CTG primero) y una orden puede no tener CPE (cargas que no son granos):
`orden_carga_id` es opcional.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Auditable, Base


class CartaPorte(Base, Auditable):
    __tablename__ = "cartas_porte"
    __table_args__ = (
        UniqueConstraint("nro_ctg", name="uq_cartas_porte_ctg"),
        UniqueConstraint("tipo_cpe", "sucursal", "nro_orden", name="uq_cartas_porte_numero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nro_ctg: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tipo_cpe: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sucursal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nro_orden: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estado: Mapped[str] = mapped_column(String(4), nullable=False)
    fecha_emision: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_vencimiento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_partida: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Desde cuándo está en `estado` (`fechaInicioEstado` de ARCA): «Anulada desde el 22-09-2026».
    fecha_inicio_estado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Por quién se consultó: el CUIT que va en `cuitRepresentada`. Se elige al traerla y se reusa al actualizarla.
    cuit_representada: Mapped[str] = mapped_column(String(11), nullable=False)
    ambiente: Mapped[str] = mapped_column(String(15), nullable=False)

    cuit_transportista: Mapped[str | None] = mapped_column(String(11), nullable=True)
    cuit_pagador_flete: Mapped[str | None] = mapped_column(String(11), nullable=True)
    cuit_chofer: Mapped[str | None] = mapped_column(String(11), nullable=True)
    cuit_origen: Mapped[str | None] = mapped_column(String(11), nullable=True)
    cuit_destino: Mapped[str | None] = mapped_column(String(11), nullable=True)
    cuit_destinatario: Mapped[str | None] = mapped_column(String(11), nullable=True)
    #: Chasis y acoplados, separados por coma, en el orden de ARCA.
    dominios: Mapped[str | None] = mapped_column(String(40), nullable=True)

    cod_grano: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cosecha: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Kilos. Los de descarga llegan con el arribo: hasta entonces, vacíos.
    peso_bruto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peso_tara: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peso_bruto_descarga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peso_tara_descarga: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Códigos de provincia y localidad **de ARCA** (no los ids de `localidades`).
    cod_provincia_origen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cod_localidad_origen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cod_provincia_destino: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cod_localidad_destino: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planta_destino: Mapped[int | None] = mapped_column(Integer, nullable=True)
    km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tarifa: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    respuesta_arca: Mapped[str] = mapped_column(Text, nullable=False)
    consultada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    orden_carga_id: Mapped[int | None] = mapped_column(
        ForeignKey("ordenes_carga.id", ondelete="SET NULL"), nullable=True, index=True
    )


class CartaPortePdf(Base):
    """El PDF que devuelve ARCA, aparte: pesa, y el listado no lo necesita."""

    __tablename__ = "cartas_porte_pdf"

    carta_porte_id: Mapped[int] = mapped_column(
        ForeignKey("cartas_porte.id", ondelete="CASCADE"), primary_key=True
    )
    contenido: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
