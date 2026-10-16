"""La semilla de la demo (`scripts/seed_demo.py`) sigue funcionando sin el registro a mano (ADR-032).

El script habla HTTP contra una instancia (`--url`); acá se lo corre **tal cual** contra la app de la suite,
cambiando sólo el transporte: el `opener` de `urllib` reenvía cada pedido al `TestClient`. Así lo que se
prueba es el script real, con sus rutas y sus cuerpos, y no una copia.
"""

import io
import runpy
import sys
import urllib.error
import urllib.request
from pathlib import Path

from tests.conftest import CLAVE, RAIZ, USUARIO


class _Respuesta:
    def __init__(self, r):
        self.status = r.status_code
        self._cuerpo = r.content

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _OpenerAlTestClient:
    def __init__(self, cliente, base):
        self.cliente, self.base = cliente, base

    def open(self, req, timeout=30):
        # El `Content-Type` que puso la semilla (el multipart del tarifario lleva su `boundary`); JSON si no puso.
        tipo = req.get_header("Content-type") or "application/json"
        r = self.cliente.request(
            req.get_method(), req.full_url[len(self.base):], content=req.data,
            headers={"Content-Type": tipo})
        if r.status_code >= 400:
            raise urllib.error.HTTPError(req.full_url, r.status_code, "", {}, io.BytesIO(r.content))
        return _Respuesta(r)


def _sembrar(cliente, monkeypatch, capsys):
    base = "https://testserver"
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: _OpenerAlTestClient(cliente, base))
    monkeypatch.setattr(sys, "argv", ["seed_demo.py", "--url", base, "--usuario", USUARIO, "--password", CLAVE])
    try:
        runpy.run_path(str(Path(RAIZ) / "scripts" / "seed_demo.py"), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), capsys.readouterr().out[-1500:]
    return capsys.readouterr().out


def test_la_semilla_de_la_demo_corre_y_deja_ordenes_pendientes_para_facturar(cliente, monkeypatch, capsys):
    salida = _sembrar(cliente, monkeypatch, capsys)

    assert "las verificaciones del producto coinciden" in salida, salida[-1500:]
    # No hay comprobantes: la demo no tiene certificado de ARCA y no se registran a mano (ADR-048).
    assert cliente.get("/api/comprobantes").json() == []
    # Todas las órdenes vigentes están pendientes y libres: se ven en «Facturar pendientes».
    pendientes = cliente.get("/api/ordenes?facturada=false&estado=pendiente").json()
    assert len(pendientes) == 6
    assert {o["cliente_id"] for o in pendientes} and len({o["cliente_id"] for o in pendientes}) == 3
    # Y la pre factura ya no existe en el producto.
    assert cliente.get("/api/pre-facturas").status_code in (404, 405)


# ── 🔴 La demo no queda con datos fiscales reales (ADR-061 de libracore) ─────────────────────────────────────────


def test_el_texto_de_la_semilla_no_tiene_cuit_de_forma_real():
    """Un CUIT con verificador válido y fuera del rango reservado `99999xxx` no se puede distinguir de uno real; los
    inventados que no cierran el verificador no existen en el padrón y no cuentan. La empresa de la demo incluida."""
    from libracore.demo import auditar_literales

    hallazgos = auditar_literales(
        (Path(RAIZ) / "scripts" / "seed_demo.py").read_text(encoding="utf-8"), "scripts/seed_demo.py")
    assert hallazgos == [], "\n".join(str(h) for h in hallazgos)


def test_la_semilla_de_la_demo_no_deja_datos_fiscales_reales_en_la_base(cliente, monkeypatch, capsys):
    """Lo que quedó en las dos bases después de sembrar: el CUIT de «Datos de la empresa» (`configuracion_empresa`),
    el de terceros y choferes, los titulares de CPE y lo que el motor guarda (`arca_config`, `config.json`)."""
    from libracore.db import core
    from libracore.db.core import conectar
    from libracore.db.url_de_instancia import url_de_instancia
    from libracore.demo import auditar_datos_fiscales

    _sembrar(cliente, monkeypatch, capsys)
    monkeypatch.setenv("DEMO_MODE", "1")
    dominio = conectar(url_de_instancia("libracargo"))
    try:
        with core.get_connection() as conn:
            hallazgos = auditar_datos_fiscales(
                conn, conn_producto=dominio, empresa=[("configuracion_empresa", "cuit")],
                terceros=[("terceros", "cuit"), ("choferes", "cuit"), ("choferes", "dni"), ("titulares_cpe", "cuit")])
    finally:
        dominio.close()
    assert hallazgos == [], "\n".join(str(h) for h in hallazgos)
