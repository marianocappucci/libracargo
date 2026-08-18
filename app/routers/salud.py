"""Sonda de salud. La usa el healthcheck del contenedor."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.tiempo import ahora

router = APIRouter(tags=["salud"])


@router.get("/salud")
def salud(sesion: Session = Depends(obtener_sesion)) -> dict[str, object]:
    """Falla cerrado: si la base no responde, la sonda no dice 'ok'."""
    sesion.execute(text("SELECT 1"))
    return {"estado": "ok", "ts": ahora().isoformat()}
