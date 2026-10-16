"""`GET /api/consultar-cuit/{cuit}`: el router del motor, montado en este producto.

Completa el alta de un tercero (razón social, domicilio, condición de IVA) con el padrón de ARCA. Es el
mismo router que usan Contalibra, Restolibra y VentaLibra; acá se fija lo que le toca a LibraCargo:

- **Lee la config de ARCA que escribe la pantalla de Configuración** (`/api/arca`, tabla `arca_config` del
  motor, en la base de core): se la carga por esa misma pantalla y el endpoint la encuentra.
- **Va con `require_staff`**, la guarda de los maestros: sin sesión es 401 y un operador (no admin) entra.
- El cliente de ARCA vive en el motor, así que se simula `libracore.arca_wsaa` y `libracore.arca_wspadron`.
"""

import pytest
from fastapi.testclient import TestClient
from libraauth.testing import crear_schema_de_auth

from app.main import crear_app
from tests.conftest import config_de_prueba, configurar_arca, vaciar_auth

CUIT_EMISOR = "20-12345678-6"
URL = "/api/consultar-cuit/"

#: Lo que devuelve el padrón y el endpoint entrega tal cual.
PERSONA = {
    "nombre": "ACME SA",
    "domicilio": "Ruta 8 km 5, Pilar, Buenos Aires",
    "iva_condition": "Responsable Inscripto",
    "estado": "ACTIVO",
}


def _padron(monkeypatch, *, persona=None, falla=None, pedidos=None, usados=None):
    """Simula WSAA y WSPadron; `pedidos` junta los CUIT consultados y `usados` lo que se le pasó al WSAA."""
    from libracore import arca_wsaa, arca_wspadron

    async def _autenticar(cert, clave, ambiente, servicio=""):
        if usados is not None:
            usados.update(cert=cert, clave=clave, ambiente=ambiente, servicio=servicio)
        return {"token": "t", "sign": "s"}

    async def _consultar(cuit_emisor, cuit_consultado, *a, **k):
        if pedidos is not None:
            pedidos.append(cuit_consultado)
        if falla is not None:
            raise falla
        return persona

    monkeypatch.setattr(arca_wsaa, "autenticar", _autenticar)
    monkeypatch.setattr(arca_wspadron, "consultar_persona", _consultar)


@pytest.mark.parametrize("cuit", ["123", "abc", "2011111111912"])
def test_cuit_que_no_tiene_11_digitos_da_400(cliente, cuit):
    configurar_arca(cliente, cuit=CUIT_EMISOR, ambiente="homologacion")
    r = cliente.get(URL + cuit)
    assert r.status_code == 400
    assert r.json() == {"error": "CUIT inválido. Debe tener 11 dígitos."}


def test_sin_config_de_arca_da_503(cliente):
    r = cliente.get(URL + "30711111114")
    assert r.status_code == 503
    assert r.json() == {
        "error": "Configurá los certificados ARCA en Configuración para habilitar la consulta de CUIT."
    }


def test_con_el_padron_simulado_da_200_con_los_campos_del_padron(cliente, monkeypatch):
    configurar_arca(cliente, cuit=CUIT_EMISOR, ambiente="homologacion")
    usados = {}
    _padron(monkeypatch, persona=PERSONA, usados=usados)
    r = cliente.get(URL + "30711111114")
    assert r.status_code == 200, r.text
    assert r.json() == PERSONA
    # Lo que se cargó por la pantalla de ARCA es lo que usa el padrón: el par de ese ambiente, en su servicio.
    assert usados["ambiente"] == "homologacion"
    assert usados["servicio"] == "ws_sr_padron_a13"


def test_el_cuit_se_limpia_antes_de_consultar(cliente, monkeypatch):
    configurar_arca(cliente, cuit=CUIT_EMISOR, ambiente="homologacion")
    pedidos = []
    _padron(monkeypatch, persona=PERSONA, pedidos=pedidos)
    assert cliente.get(URL + "30-71111111-4").status_code == 200
    assert pedidos == ["30711111114"]


@pytest.mark.parametrize("falla, estado, mensaje", [
    (RuntimeError("CUIT no encontrado en el padrón de ARCA."), 404, "CUIT no encontrado en el padrón de ARCA."),
    (RuntimeError("Computador no autorizado a acceder al servicio"), 403, "Consulta a Padrón Alcance 13"),
    (RuntimeError("alguna otra cosa de ARCA"), 502, "alguna otra cosa de ARCA"),
    (ValueError("boom"), 500, "Error al consultar ARCA: boom"),
])
def test_los_errores_del_padron_conservan_estado_y_mensaje(cliente, monkeypatch, falla, estado, mensaje):
    configurar_arca(cliente, cuit=CUIT_EMISOR, ambiente="homologacion")
    _padron(monkeypatch, falla=falla)
    r = cliente.get(URL + "30711111114")
    assert r.status_code == estado, r.text
    assert mensaje in r.json()["error"]


def test_un_operador_que_no_es_admin_puede_consultar(cliente, monkeypatch):
    """La guarda es la de los maestros (`require_staff`): quien da de alta un tercero tiene que poder consultar."""
    configurar_arca(cliente, cuit=CUIT_EMISOR, ambiente="homologacion")
    _padron(monkeypatch, persona=PERSONA)
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    assert staff.post("/auth/login", json={"username": "marta", "password": "una-clave"}).status_code == 200
    # Control: ese mismo usuario no administra usuarios, así que de verdad no es admin.
    assert staff.get("/api/usuarios").status_code == 403
    r = staff.get(URL + "30711111114")
    assert r.status_code == 200, r.text
    assert r.json() == PERSONA


def test_sin_sesion_es_401_y_no_se_toca_arca(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    pedidos = []
    _padron(monkeypatch, persona=PERSONA, pedidos=pedidos)
    anonimo = TestClient(crear_app(config_de_prueba(), sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get(URL + "30711111114").status_code == 401
        assert pedidos == []
    finally:
        vaciar_auth(engine)
