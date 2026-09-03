"""Los datos de la empresa: los que salen impresos en cada papel."""


import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.main import crear_app
from tests.conftest import config_de_prueba

ADMIN, CLAVE = "admin", "clave-de-prueba"

#: Un PNG de 1x1 de verdad, no un `b"x"`: si el endpoint algún día mira los
#: bytes, un contenido falso lo dejaría pasar igual y el test no probaría nada.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")

EMPRESA = {
    "razon_social": "Suitrans SRL", "cuit": "30-71234567-9",
    "domicilio": "San Martín 450", "localidad": "Mercedes",
    "telefono": "2324-441122", "pie_de_impresion": "Recibí conforme",
}


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", ADMIN)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


def test_una_instancia_sin_configurar_contesta_vacia_y_no_404(cliente):
    """La barra lateral la pide en cada carga: un 404 la dejaría rota de entrada.

    Y obligaría a cada pantalla a distinguir "no hay configuración" de "no se
    pudo leer", que son cosas distintas y ninguna es un error.
    """
    r = cliente.get("/api/configuracion")
    assert r.status_code == 200
    assert r.json()["razon_social"] == ""
    assert r.json()["tiene_logo"] is False


def test_se_guarda_y_se_lee(cliente):
    r = cliente.put("/api/configuracion", json=EMPRESA)
    assert r.status_code == 200, r.text
    assert r.json()["razon_social"] == "Suitrans SRL"
    assert cliente.get("/api/configuracion").json()["domicilio"] == "San Martín 450"

    # Y editar no crea una segunda: sigue siendo la misma fila.
    cliente.put("/api/configuracion", json={**EMPRESA, "telefono": "2324-999999"})
    assert cliente.get("/api/configuracion").json()["telefono"] == "2324-999999"


def test_el_logo_va_y_vuelve_con_su_tipo(cliente):
    cliente.put("/api/configuracion", json=EMPRESA)
    r = cliente.post("/api/configuracion/logo",
                     files={"archivo": ("logo.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["tiene_logo"] is True

    imagen = cliente.get("/api/configuracion/logo")
    assert imagen.status_code == 200
    assert imagen.headers["content-type"] == "image/png"
    assert imagen.content == PNG

    assert cliente.delete("/api/configuracion/logo").json()["tiene_logo"] is False
    assert cliente.get("/api/configuracion/logo").status_code == 404


def test_un_svg_no_entra(cliente):
    """🔴 El SVG lleva scripts y esto se sirve desde el MISMO origen que la app.

    O sea con la cookie de sesión al alcance. La lista es blanca a propósito: un
    formato nuevo se agrega a mano, no entra por descuido.
    """
    cliente.put("/api/configuracion", json=EMPRESA)
    r = cliente.post("/api/configuracion/logo",
                     files={"archivo": ("logo.svg", b"<svg onload='alert(1)'/>", "image/svg+xml")})
    assert r.status_code == 422
    assert "no admitido" in r.text
    # Control: el PNG del mismo tamaño sí entra.
    assert cliente.post("/api/configuracion/logo",
                        files={"archivo": ("logo.png", PNG, "image/png")}).status_code == 200


def test_un_logo_enorme_se_rechaza(cliente):
    cliente.put("/api/configuracion", json=EMPRESA)
    grande = PNG + b"\0" * (2 * 1024 * 1024)
    r = cliente.post("/api/configuracion/logo",
                     files={"archivo": ("logo.png", grande, "image/png")})
    assert r.status_code == 422
    assert "2048" in r.text


def test_el_logo_no_viaja_en_el_json_de_la_configuracion(cliente):
    """La barra lateral pide la configuración en cada carga: si el logo viniera
    adentro, cada navegación arrastraría la imagen entera."""
    cliente.put("/api/configuracion", json=EMPRESA)
    cliente.post("/api/configuracion/logo", files={"archivo": ("l.png", PNG, "image/png")})
    cuerpo = cliente.get("/api/configuracion").json()
    assert cuerpo["tiene_logo"] is True
    assert "logo" not in cuerpo


def test_un_operador_la_lee_pero_no_la_edita(cliente):
    """El membrete lo imprime cualquiera; la identidad fiscal la cambia un admin."""
    cliente.put("/api/configuracion", json=EMPRESA)
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    staff.post("/auth/login", json={"username": "marta", "password": "una-clave"})

    assert staff.get("/api/configuracion").status_code == 200
    assert staff.put("/api/configuracion", json=EMPRESA).status_code == 403
    assert staff.post("/api/configuracion/logo",
                      files={"archivo": ("l.png", PNG, "image/png")}).status_code == 403


def test_el_cambio_queda_en_el_log(cliente):
    cliente.put("/api/configuracion", json=EMPRESA)
    cliente.put("/api/configuracion", json={**EMPRESA, "razon_social": "Suitrans SA"})
    asientos = cliente.get("/api/auditoria?entidad=configuracion").json()
    assert asientos["total"] == 2
    ultimo = asientos["registros"][0]
    assert ultimo["accion"] == "modificacion"
    assert ultimo["datos_antes"]["razon_social"] == "Suitrans SRL"
    assert ultimo["datos_despues"]["razon_social"] == "Suitrans SA"


def test_sin_sesion_no_se_ve(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/configuracion").status_code == 401
        assert anonimo.get("/api/configuracion/logo").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
