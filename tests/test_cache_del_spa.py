"""Las cabeceras de caché del frontend, que son lo que hace que un deploy se vea.

**Por qué existe este archivo.** El 2026-08-19 la pantalla de Backup estaba
desplegada —el contenedor con el código nuevo, el bundle nuevo publicado— y no
se veía en el navegador. Del lado del servidor todo daba bien.

La causa: `index.html` se servía **sin `Cache-Control`**, y sin esa cabecera el
navegador aplica caché heurística y puede servir la copia guardada sin
preguntar. Como Vite le pone un hash en el nombre a cada bundle, el bundle viejo
**sigue existiendo**: el `index.html` viejo lo pide y lo recibe, con 200. No hay
error en ninguna capa — ni un 404 que delate nada.

Los dos tests principales son las dos mitades del mismo arreglo, y ninguna sirve
sola:

- el archivo cuyo nombre NO cambia (`index.html`) revalida siempre;
- los que llevan el hash en el nombre se cachean para siempre, que es seguro
  **porque** el index revalida.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
ASSET = "index-DELTEST123.js"


@pytest.fixture(scope="module")
def cliente():
    """La app ASGI de verdad, con un `dist` presente.

    El `dist` no es decorado: el mount de `/assets` y el catch-all **se arman en
    el import** y sólo si el directorio existe. Sin él, este archivo probaría
    una app sin frontend, o sea nada. Se fabrica uno mínimo si el checkout no lo
    tiene —el job de tests del CI no construye el frontend— y se borra sólo lo
    que se haya creado.
    """
    dist = REPO / "frontend" / "dist"
    creado = not dist.is_dir()
    if creado:
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text(
            "<!doctype html><title>LibraCargo</title>", encoding="utf-8")
        (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    asset = dist / "assets" / ASSET
    asset.write_text("console.log(1)", encoding="utf-8")
    suelto = dist / "prueba-de-cache.txt"
    suelto.write_text("hola", encoding="utf-8")

    # Importar `app.asgi` construye la app entera, y el sembrado del admin es
    # fail-closed: sin la contraseña no levanta. Un test tiene que traer su
    # entorno, no heredar el del shell de quien lo corre.
    previo = {v: os.environ.get(v) for v in
              ("ENV", "LIBRACARGO_ADMIN_USERNAME", "LIBRACARGO_ADMIN_PASSWORD",
               "SECRET_KEY")}
    os.environ["ENV"] = "development"
    os.environ["LIBRACARGO_ADMIN_USERNAME"] = "admin"
    os.environ["LIBRACARGO_ADMIN_PASSWORD"] = "clave-de-prueba"
    os.environ["SECRET_KEY"] = "libracargo-suite-no-es-un-secreto-real"

    sys.modules.pop("app.asgi", None)
    asgi = importlib.import_module("app.asgi")
    assert asgi.FRONTEND_DIST.is_dir(), "sin dist esto no prueba nada"

    yield TestClient(asgi.app, base_url="https://testserver")

    sys.modules.pop("app.asgi", None)
    for var, valor in previo.items():
        if valor is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = valor
    asset.unlink(missing_ok=True)
    suelto.unlink(missing_ok=True)
    if creado:
        shutil.rmtree(dist, ignore_errors=True)


def test_el_index_revalida_siempre(cliente):
    """El archivo cuyo nombre no cambia no se puede cachear a ciegas.

    Es el único que dice cuál es el bundle de ahora. Si el navegador se queda
    con el viejo, pide el bundle viejo —que existe, porque el nombre lleva
    hash— y lo recibe con 200: el deploy no se ve y nada falla.
    """
    r = cliente.get("/")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", ""), dict(r.headers)


def test_una_ruta_del_ruteo_del_cliente_tambien(cliente):
    """Cae en el mismo `index.html` por el catch-all, y tiene que traer lo mismo."""
    r = cliente.get("/ordenes/nueva")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", ""), dict(r.headers)


def test_los_assets_se_cachean_para_siempre(cliente):
    """La otra mitad: el nombre lleva el hash del contenido, así que el mismo
    nombre nunca cambia de contenido."""
    r = cliente.get(f"/assets/{ASSET}")
    assert r.status_code == 200
    cache = r.headers.get("cache-control", "")
    assert "immutable" in cache and "max-age=31536000" in cache, cache


def test_los_archivos_sueltos_del_dist_no_se_cachean(cliente):
    """Un favicon o un manifest no llevan hash: mismo criterio que el index."""
    r = cliente.get("/prueba-de-cache.txt")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", ""), dict(r.headers)


def test_las_dos_politicas_son_distintas(cliente):
    """El control de los dos de arriba, juntos.

    Si algún día las dos rutas devolvieran la misma cabecera, uno de los dos
    tests seguiría pasando por el motivo equivocado y nadie se enteraría.
    """
    index = cliente.get("/").headers.get("cache-control", "")
    asset = cliente.get(f"/assets/{ASSET}").headers.get("cache-control", "")
    assert index and asset and index != asset, f"index={index!r} asset={asset!r}"
