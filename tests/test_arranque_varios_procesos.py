"""El arranque de LibraCargo con varios procesos (`uvicorn --workers N`; hoy N = 1).

El candado y sus 2 workers de verdad los prueba el motor (`libracore/tests/test_varios_procesos.py`). Lo que se cuida
acá es que **la siembra del admin esté adentro del candado**: sin `una_vez_al_arrancar`, dos workers que arrancan
juntos contestan los dos «no existe» y crean el admin dos veces.
"""

from __future__ import annotations

import contextlib

from app import main as principal
from tests.conftest import config_de_prueba


def test_la_siembra_del_admin_corre_adentro_de_una_vez_al_arrancar(cliente, monkeypatch):
    # `cliente` deja la base lista (schema y cadena de auth); la app que se mide es la que se arma acá.
    eventos = []

    @contextlib.contextmanager
    def espia(nombre, **_):
        eventos.append(("entra", nombre))
        try:
            yield
        finally:
            eventos.append(("sale", nombre))

    def ensure_default_admin_espiado(*_, **__):
        eventos.append("ensure_default_admin")

    def ensure_demo_user_espiado(*_):
        eventos.append("ensure_demo_user")

    monkeypatch.setattr(principal, "una_vez_al_arrancar", espia)
    monkeypatch.setattr(principal, "ensure_default_admin", ensure_default_admin_espiado)
    monkeypatch.setattr(principal, "ensure_demo_user", ensure_demo_user_espiado)

    principal.crear_app(config_de_prueba())

    assert eventos == [
        ("entra", "libracargo-sembrar"), "ensure_default_admin", "ensure_demo_user", ("sale", "libracargo-sembrar"),
    ]
