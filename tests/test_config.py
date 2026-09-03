"""La guarda de motor: PostgreSQL es el único, y no hay default a SQLite."""

from __future__ import annotations

import pytest

from app.config import Config


def test_sin_ninguna_url_de_base_no_arranca(monkeypatch):
    """Fail-closed, y ahora son DOS los nombres que hay que sacar.

    Desde que la app acepta también `LIBRACARGO_DATABASE_URL` —el nombre que el
    generador le escribe a una instancia nueva— borrar sólo la genérica no deja
    el entorno vacío: si la otra estuviera puesta, este test mediría un arranque
    exitoso y lo llamaría "no arranca".
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LIBRACARGO_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="Falta la URL de la base"):
        Config.desde_entorno()


def test_sqlite_es_rechazado(monkeypatch):
    """Una suite verde sobre SQLite no dice nada del motor real (regla 2026-08-12)."""
    monkeypatch.delenv("LIBRACARGO_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///libracargo.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Config.desde_entorno()


def test_el_mensaje_de_error_no_filtra_la_url(monkeypatch):
    """Nombra el esquema, no la cadena: una URL de Postgres lleva la contraseña
    embebida y los tracebacks terminan en logs y en transcripciones."""
    monkeypatch.setenv("DATABASE_URL", "mysql://usuario:secreto@host/base")
    with pytest.raises(RuntimeError) as e:
        Config.desde_entorno()
    assert "secreto" not in str(e.value)


def test_postgres_pasa_y_debug_arranca_apagado(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/b")
    monkeypatch.delenv("DEBUG", raising=False)
    cfg = Config.desde_entorno()
    assert cfg.database_url.startswith("postgresql+psycopg://")
    assert cfg.debug is False
