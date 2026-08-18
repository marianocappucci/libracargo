"""Configuración por entorno. Ningún secreto vive en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    entorno: str
    debug: bool

    @classmethod
    def desde_entorno(cls) -> Config:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "Falta DATABASE_URL. LibraCargo corre sobre PostgreSQL; "
                "no hay default a SQLite a propósito."
            )
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError(
                f"DATABASE_URL debe apuntar a PostgreSQL, no a {url.split(':', 1)[0]!r}. "
                "PostgreSQL es el único motor de la familia Libra."
            )
        return cls(
            database_url=url,
            entorno=os.environ.get("ENTORNO", "dev"),
            debug=os.environ.get("DEBUG", "").lower() in {"1", "true", "si"},
        )
