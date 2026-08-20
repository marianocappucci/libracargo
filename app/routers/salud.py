"""Sonda de salud. La usa el healthcheck del contenedor."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.tiempo import ahora

router = APIRouter(tags=["salud"])


# 🔑 **Dos rutas, un solo handler.** `/salud` es el nombre de este producto,
# donde todo se llama en castellano. `/health` es la convención de la familia:
# los otros seis la sirven, y es el default de `libracore.provisioning`, o sea
# la que el alta de un cliente le estampa al healthcheck de su contenedor.
#
# 🔴 Con la SPA horneada, apuntar el healthcheck a una ruta que la app no sirve
# **no se ve como un 404**: lo contesta el catch-all de `app/asgi.py` con el
# `index.html`, o sea 200. Una instancia nacería con un chequeo que mide que
# haya estáticos y no que la base responda, y se vería sana con la base caída.
# Le pasó a LibraDesk, que servía sólo `/api/health` mientras el provisioning
# probaba `/health`.
#
# Se declaran las dos en vez de renombrar porque no pueden divergir: es la misma
# función. Lo que no se hace es dejar una sola y que el provisioning apunte a la
# otra.
@router.get("/salud")
@router.get("/health")
def salud(sesion: Session = Depends(obtener_sesion)) -> dict[str, object]:
    """Falla cerrado: si la base no responde, la sonda no dice 'ok'."""
    sesion.execute(text("SELECT 1"))
    return {"estado": "ok", "ts": ahora().isoformat()}
