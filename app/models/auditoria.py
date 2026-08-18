"""Auditoría: qué cambió, no sólo que algo pasó."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AccionAuditoria


class RegistroAuditoria(Base):
    """Reemplaza a `sucesos`.

    La tabla vieja guardaba fecha, hora, tipo, el **nombre** del usuario en
    `varchar(11)` —contra un `usuario_nombre` de `varchar(10)`, que ni siquiera
    coincidía— y dos ids. Nunca guardó qué cambió, así que un error de carga no
    se podía reconstruir.
    """

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usuario_nombre: Mapped[str | None] = mapped_column(String(120), nullable=True)
    entidad: Mapped[str] = mapped_column(String(60), nullable=False)
    entidad_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accion: Mapped[AccionAuditoria] = mapped_column(
        Enum(AccionAuditoria, name="accion_auditoria",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    datos_antes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    datos_despues: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_auditoria_ts", "ts"),
        Index("ix_auditoria_entidad", "entidad", "entidad_id"),
        Index("ix_auditoria_usuario", "usuario_id"),
    )
