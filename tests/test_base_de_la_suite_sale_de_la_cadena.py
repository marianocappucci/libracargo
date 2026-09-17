"""La base de la suite tiene la cadena de Alembic estampada en su cabeza.

Hasta el 2026-09-17 el fixture `engine` la armaba con `create_all`, sin
`alembic_version_libracargo`. Una base así, respaldada y restaurada, corre la baseline
encima de sus propias tablas y `alembic upgrade head` muere con
`DuplicateObject accion_auditoria`. Se fija la forma, y que un `upgrade head`
sobre ella no tiene nada que hacer.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

RAIZ = Path(__file__).resolve().parent.parent


def _config() -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    return cfg


def _version(engine) -> list[str]:
    with engine.connect() as con:
        return [r[0] for r in con.execute(text("SELECT version_num FROM alembic_version_libracargo"))]


def test_la_base_esta_en_la_cabeza_de_la_cadena(engine):
    assert _version(engine) == [ScriptDirectory.from_config(_config()).get_current_head()]


def test_upgrade_head_sobre_la_base_de_la_suite_no_falla(engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    antes = _version(engine)
    command.upgrade(_config(), "head")
    assert _version(engine) == antes
