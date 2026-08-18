"""Base declarativa y mixins comunes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Auditable:
    """`created_at`/`updated_at` en `timestamptz`, y quién lo hizo.

    El sistema legado no tenía ninguna de las cuatro columnas: su tabla
    `sucesos` registraba que algo había pasado, pero no qué cambió ni sobre
    qué fila. Sin esto no se puede reconstruir un error de carga.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Anotable:
    """Observaciones libres, sin el `varchar(50)` del legado."""

    observaciones: Mapped[str | None] = mapped_column(String, nullable=True)
