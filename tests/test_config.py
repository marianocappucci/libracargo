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


# ── La base de LibraCore es la del dominio (ADR-054) ─────────────────────────
#
# `LIBRACARGO_LIBRACORE_DATABASE_URL` ya no hace falta: el schema del motor vive
# en la base del dominio desde la `0015`. Tres formas reales de entorno:
#   - sin la variable: una instancia nueva y el compose de dev;
#   - con la variable IGUAL a la del dominio: Suitrans y la demo, hasta que se
#     les saque (nadie toca el VPS desde acá);
#   - con la variable a OTRA base: una instancia sin unir, que no se soporta.

DOMINIO = "postgresql+psycopg://u:clave-secreta@h:5432/libracargo"


@pytest.fixture
def _dominio(monkeypatch):
    monkeypatch.delenv("LIBRACARGO_DATABASE_URL", raising=False)
    monkeypatch.delenv("LIBRACARGO_LIBRACORE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", DOMINIO)


def test_sin_la_variable_del_core_la_app_arranca(_dominio):
    cfg = Config.desde_entorno()
    assert cfg.database_url == DOMINIO
    # Y no hay una segunda URL que pueda divergir: el core ES la del dominio.
    assert not hasattr(cfg, "database_url_core")


def test_con_la_variable_IGUAL_a_la_del_dominio_no_cambia_nada(_dominio, monkeypatch):
    """La forma del compose de Suitrans hoy: las dos variables, la misma URL."""
    sin = Config.desde_entorno()
    monkeypatch.setenv("LIBRACARGO_LIBRACORE_DATABASE_URL", DOMINIO)
    assert Config.desde_entorno() == sin


@pytest.mark.parametrize("variante", [
    "postgresql://u:clave-secreta@h:5432/libracargo",            # sin el driver
    "postgresql+psycopg://u:clave-secreta@h:5432/libracargo?sslmode=disable",
    "postgresql+psycopg://u:clave-secreta@h/libracargo",         # puerto por defecto
    "postgresql+psycopg://otro:otra-clave@H:5432/libracargo",    # otro usuario, host en mayúsculas
])
def test_la_misma_base_escrita_distinto_tampoco_cambia_nada(_dominio, monkeypatch, variante):
    """Una diferencia de forma no tumba un arranque: lo que identifica la base es
    servidor, puerto y nombre."""
    monkeypatch.setenv("LIBRACARGO_LIBRACORE_DATABASE_URL", variante)
    assert Config.desde_entorno().database_url == DOMINIO


def test_una_variable_del_core_vacia_cuenta_como_no_puesta(_dominio, monkeypatch):
    monkeypatch.setenv("LIBRACARGO_LIBRACORE_DATABASE_URL", "  ")
    assert Config.desde_entorno().database_url == DOMINIO


@pytest.mark.parametrize("otra", [
    "postgresql+psycopg://u:clave-secreta@h:5432/libracargo_core",   # otra base, mismo servidor
    "postgresql+psycopg://u:clave-secreta@otro-host:5432/libracargo",  # mismo nombre, otro servidor
    "postgresql+psycopg://u:clave-secreta@h:5433/libracargo",          # mismo nombre, otro puerto
    "sqlite:///core.db",
    "no es una url",
])
def test_la_variable_del_core_a_OTRA_base_hace_fallar_el_arranque(_dominio, monkeypatch, otra):
    """LibraCargo no soporta dos bases desde la `0015`. Ignorar la variable en
    silencio dejaría a `libracore-migrar` migrando una base y a la app escribiendo
    en otra: el error tiene que verse al arrancar, y decir qué hacer."""
    monkeypatch.setenv("LIBRACARGO_LIBRACORE_DATABASE_URL", otra)
    with pytest.raises(RuntimeError, match="LIBRACARGO_LIBRACORE_DATABASE_URL apunta a otra base") as e:
        Config.desde_entorno()
    texto = str(e.value)
    assert "Sacá la variable" in texto
    # Nombra las bases, no las URL: la contraseña no sale en un traceback.
    assert "clave-secreta" not in texto
    assert "'libracargo'" in texto
