"""Punto de entrada de la API."""

from __future__ import annotations

from fastapi import FastAPI

from app.routers import salud


def crear_app() -> FastAPI:
    app = FastAPI(
        title="LibraCargo",
        description="Gestión de agencia de cargas — familia Libra",
        version="0.1.0",
    )
    app.include_router(salud.router)
    return app


app = crear_app()
