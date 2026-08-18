"""Entrypoint ASGI: `uvicorn app.asgi:app`.

Sirve el build del frontend desde el **mismo origen** que la API, con catch-all
a `index.html` para el ruteo del lado del cliente. El dist se hornea fuera de
`/app` (`/opt/frontend-dist`) porque el compose de dev monta `./:/app` entero
para el `--reload`, y eso taparía cualquier build copiado adentro.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import crear_app
from app.spa import TIPOS_PROPIOS, archivo_publico, es_ruta_de_api

app = crear_app()

_DIST_DOCKER = Path("/opt/frontend-dist")
_DIST_LOCAL = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_DIST = _DIST_DOCKER if _DIST_DOCKER.is_dir() else _DIST_LOCAL

if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets"
    )

    @app.get("/{ruta:path}", include_in_schema=False)
    async def spa(ruta: str):
        if es_ruta_de_api(ruta):
            raise HTTPException(404, "no existe esa ruta")
        archivo = archivo_publico(FRONTEND_DIST, ruta)
        if archivo is not None:
            return FileResponse(archivo, media_type=TIPOS_PROPIOS.get(archivo.suffix))
        return FileResponse(FRONTEND_DIST / "index.html")
