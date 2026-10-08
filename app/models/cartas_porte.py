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
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
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

    #: Si la emitió este sistema (por delegación, ADR-043), y no sólo la trajo de ARCA. Sólo esas se anulan desde acá.
    emitida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
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


class PlantillaCpe(Base):
    """Lo último que se usó para emitir a nombre de un titular (ADR-043): el origen, el grano, el destino, la planta,
    los intervinientes. La próxima emisión de ese titular arranca con esto, y el operador sólo completa el viaje."""

    __tablename__ = "plantillas_cpe"

    cuit_titular: Mapped[str] = mapped_column(String(11), primary_key=True)
    datos: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


#: Quién emite la Carta de Porte de un titular (ADR-044): este sistema, por la delegación del titular en ARCA, o él.
EMITE_NOSOTROS = "nosotros"
EMITE_TITULAR = "titular"


class TitularCpe(Base, Auditable):
    """Un titular de Carta de Porte: el cliente (o no) a cuyo nombre se emite, o que emite por su cuenta (ADR-044).

    Es **libreta de direcciones y no permiso**: que un titular esté cargado no le da a este sistema ninguna facultad.
    La delegación es de ARCA y se lee del ticket de WSAA de `wscpe` en cada consulta; acá no se guarda ni se tilda a
    mano. Lo que sí se guarda es lo que ARCA no sabe: a quién corresponde, quién emite y sus datos habituales.

    `id` y no el CUIT como clave: la auditoría (`entidad_id`) es un entero de 32 bits y un CUIT no entra.
    """

    __tablename__ = "titulares_cpe"
    __table_args__ = (
        CheckConstraint(f"emite IN ('{EMITE_NOSOTROS}', '{EMITE_TITULAR}')", name="ck_titulares_cpe_emite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Once dígitos, sin guiones: lo mismo que `cuitRepresentada` de ARCA y que `plantillas_cpe.cuit_titular`.
    cuit: Mapped[str] = mapped_column(String(11), nullable=False, unique=True)
    razon_social: Mapped[str] = mapped_column(String(120), nullable=False)
    #: La entidad de Entidades (ADR-040) con ese CUIT, si existe. Se completa sola al cargar y se puede cambiar.
    tercero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="SET NULL"), nullable=True, index=True
    )
    emite: Mapped[str] = mapped_column(String(10), nullable=False, default=EMITE_NOSOTROS,
                                       server_default=EMITE_NOSOTROS)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
