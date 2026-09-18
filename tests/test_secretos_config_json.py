"""Los secretos de `config.json` viven cifrados, no en el archivo (2026-09-17).

**Estos tests miran el `config.json` CRUDO y la tabla en la base**, no lo que
devuelve `config_manager.load()`. Es a proposito: `load()` devuelve el secreto
en claro por diseño —para que los ~12 consumidores no cambien— asi que un
assert sobre `load()` da verde igual con la implementacion vieja, la que
escribia el token en el archivo. Lo unico que distingue una de otra es que
quedo en el disco.

Y se mide a traves del enganche REAL del producto (`app.main.crear_app`), no
armando un almacen a mano: lo que este archivo fija es que LibraCargo lo haya
enchufado, que es la mitad que LibraCore no puede garantizar.

`libracore.config_manager` en LibraCargo NO tiene un wrapper propio (a
diferencia de Contalibra, que tiene `app.config_manager`): el producto importa
directo `from libracore import config_manager`, y este archivo hace lo mismo.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from libracore import config_manager
from sqlalchemy import text

from app import db
from app.main import crear_app, migrar_secretos
from tests.conftest import config_de_prueba

TOKEN = "APP_USR-1234567890123456-091712-abcdef0123456789-3392230021"


def _crudo():
    with open(config_manager.CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _escribir_crudo(datos):
    """Escribe el archivo como lo dejaba la version vieja, sin pasar por
    `save()` —que ya enruta al almacen y no dejaria el secreto en el archivo—."""
    with open(config_manager.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f)


def _filas_de_secretos():
    with db.engine().connect() as c:
        return dict(
            c.execute(text("select clave, valor_cifrado from secretos_instancia")).all()
        )


@pytest.fixture(autouse=True)
def _limpio(cliente):
    """Sin secretos en la base ni en el archivo, antes y despues.

    Pide `cliente` a proposito: es el fixture que arma la base de cero y
    dispara el arranque REAL de la app —`exigir_schema_al_dia`, el enganche del
    almacen y la migracion de secretos—. Sin el, `secretos_instancia` no
    existe: la crea la revision `0002` de libraauth, no un `create_all`.
    """
    def limpiar():
        almacen = config_manager.almacen_de_secretos()
        if almacen is not None:
            for clave in config_manager.CLAVES_SECRETAS:
                almacen.delete(clave)
        if os.path.exists(config_manager.CONFIG_PATH):
            os.unlink(config_manager.CONFIG_PATH)
    limpiar()
    yield
    limpiar()


def test_el_producto_enchufo_el_almacen(cliente):
    """Sin esto, todo lo demas es la implementacion vieja: `config_manager` sin
    almacen escribe el secreto en el JSON, exactamente como antes."""
    assert config_manager.almacen_de_secretos() is not None


def test_guardar_el_token_no_lo_deja_en_el_archivo(cliente):
    cfg = config_manager.load()
    cfg["mp_access_token"] = TOKEN
    cfg["empresa_nombre"] = "Suitrans SRL"
    config_manager.save(cfg)

    crudo = _crudo()
    assert crudo["mp_access_token"] == ""
    # Control positivo del mismo barrido: lo que no es secreto si quedo escrito.
    assert crudo["empresa_nombre"] == "Suitrans SRL"
    # Y para los consumidores no cambio nada.
    assert config_manager.load()["mp_access_token"] == TOKEN


def test_en_la_base_tampoco_esta_en_claro(cliente):
    cfg = config_manager.load()
    cfg["mp_access_token"] = TOKEN
    config_manager.save(cfg)

    filas = _filas_de_secretos()
    assert "mp_access_token" in filas
    assert TOKEN not in filas["mp_access_token"]
    assert filas["mp_access_token"].startswith("v1:")


def test_el_arranque_migra_lo_que_la_version_vieja_dejo_en_el_archivo(cliente):
    """🔑 El caso de instancias vivas: el archivo tiene los secretos en claro,
    se despliega esta version, y el arranque los mueve solo."""
    _escribir_crudo({
        "empresa_nombre": "Suitrans SRL",
        "mp_access_token": TOKEN,
        "mp_webhook_secret": "firma-del-webhook",
        "email_smtp_password": "la-contrasena",
    })
    assert _crudo()["mp_access_token"] == TOKEN  # el punto de partida

    informe = migrar_secretos(config_manager.almacen_de_secretos())

    assert sorted(informe["migradas"]) == [
        "email_smtp_password", "mp_access_token", "mp_webhook_secret",
    ]
    crudo = _crudo()
    for clave in config_manager.CLAVES_SECRETAS:
        assert crudo[clave] == "", f"{clave} sigue en el archivo"
    assert crudo["empresa_nombre"] == "Suitrans SRL"
    assert config_manager.load()["mp_access_token"] == TOKEN
    assert config_manager.load()["mp_webhook_secret"] == "firma-del-webhook"


def test_la_migracion_es_idempotente(cliente):
    _escribir_crudo({"mp_access_token": TOKEN})
    migrar_secretos(config_manager.almacen_de_secretos())
    antes = _filas_de_secretos()["mp_access_token"]

    informe = migrar_secretos(config_manager.almacen_de_secretos())

    assert informe == {"migradas": [], "ya_estaban": [], "fallaron": {}}
    # No se reescribio: el blob es el mismo, con el mismo nonce.
    assert _filas_de_secretos()["mp_access_token"] == antes


def test_el_arranque_de_la_app_corre_la_migracion(cliente):
    """El enganche y la migracion viven DENTRO de `crear_app()` (no hay un
    `@app.on_event("startup")` separado en LibraCargo: todo el arranque es
    sincrono en la construccion). Por eso "el arranque real corre la
    migracion" se mide reconstruyendo la app -- exactamente lo que hace un
    restart del contenedor -- y no solo llamando a la funcion suelta.
    """
    _escribir_crudo({"mp_access_token": TOKEN})

    with TestClient(crear_app(config_de_prueba(), sembrar_admin=False)):
        pass

    assert _crudo()["mp_access_token"] == ""
    assert config_manager.load()["mp_access_token"] == TOKEN
