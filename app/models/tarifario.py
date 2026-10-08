"""El tarifario de referencia de cereales y oleaginosas: una tarifa por tonelada para cada kilómetro (ADR-038).

Es la tabla que publica el sector (la de Suitrans es la del 10 de abril de 2026) y que se usa para cotizar el flete
y para la tarifa de la Carta de Porte: «en 100 km una tarifa, en 101 otra… la tarifa es por tonelada descargada»
(audio del dueño de Suitrans, 2026-10-07). Cada edición es un `Tarifario` con su **vigencia**; las anteriores se
quedan, porque una orden vieja se cotizó con la que regía en su fecha.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Auditable, Base


class Tarifario(Base, Auditable):
    __tablename__ = "tarifarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Desde cuándo rige. Una orden usa el tarifario de vigencia más reciente que no sea posterior a su fecha.
    vigencia: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    #: El «valor de estadía» que publica la misma tabla, por día.
    valor_estadia: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class TarifaDeReferencia(Base):
    __tablename__ = "tarifas_referencia"

    tarifario_id: Mapped[int] = mapped_column(
        ForeignKey("tarifarios.id", ondelete="CASCADE"), primary_key=True)
    km: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Pesos por tonelada.
    tarifa: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("km >= 1 AND tarifa >= 0", name="ck_tarifas_referencia_valores"),
    )
