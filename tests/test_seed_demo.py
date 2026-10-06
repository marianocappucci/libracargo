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
        r = self.cliente.request(
            req.get_method(), req.full_url[len(self.base):], content=req.data,
            headers={"Content-Type": "application/json"})
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


def test_la_semilla_de_la_demo_corre_y_deja_pre_facturas_de_ejemplo(cliente, monkeypatch, capsys):
    salida = _sembrar(cliente, monkeypatch, capsys)

    assert "las verificaciones del producto coinciden" in salida, salida[-1500:]
    pre_facturas = cliente.get("/api/pre-facturas").json()
    assert pre_facturas["counts"] == {
        "pendiente": 1, "enviado": 0, "aceptado": 1, "facturado": 0, "descartado": 1}
    assert sorted(p["numero_interno"] for p in pre_facturas["items"]) == ["PF-0001", "PF-0002", "PF-0003"]
    # Datos ficticios: ni un nombre real.
    assert {p["cliente_razon"] for p in pre_facturas["items"]} == {
        "Agro del Oeste SA", "Molinos Suipacha", "Cerealera del Sur"}
    # No hay comprobantes: la demo no tiene certificado de ARCA y ya no se registran a mano.
    assert cliente.get("/api/comprobantes").json() == []
    # Las órdenes de las pre facturas abiertas están reservadas; las de la anulada, libres.
    libres = cliente.get("/api/ordenes?reservada=false&estado=pendiente").json()
    assert len(libres) == 3
    assert len(cliente.get("/api/ordenes?reservada=true").json()) == 3
