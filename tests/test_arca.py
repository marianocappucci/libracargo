"""La configuración de ARCA.

Los certificados de los tests se **generan acá**, no se guardan como fixtures:
un `.crt` de verdad en el repo es un archivo que caduca y que nadie sabe de
dónde salió, y para lo que se prueba —que el archivo parsee, que la pareja
coincida— uno recién hecho sirve igual.
"""

import datetime
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app
from app.servicios.arca import ArchivoInvalido, leer_certificado, leer_clave, son_pareja

USUARIO, CLAVE = "admin", "clave-de-prueba"


def _par(dias_de_vida: int = 730, cn: str = "suitrans"):
    """Devuelve (certificado_pem, clave_pem) recién generados."""
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    ahora = datetime.datetime.now(datetime.UTC)
    fin = ahora + datetime.timedelta(days=dias_de_vida)
    # El inicio siempre antes del fin: con `dias_de_vida` negativo -el caso del
    # certificado ya vencido- un inicio de "ayer" quedaria despues del fin, y
    # `cryptography` rechaza construirlo.
    inicio = min(ahora - datetime.timedelta(days=1), fin - datetime.timedelta(days=1))
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(fin)
        .sign(clave, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    clave_pem = clave.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, clave_pem


# --------------------------------------------------------------------- servicio

def test_un_certificado_valido_se_lee_con_su_vencimiento():
    cert, _ = _par(dias_de_vida=400)
    datos = leer_certificado(cert)
    assert "suitrans" in datos.sujeto
    assert not datos.vencido
    # El dato que evita la falla silenciosa: duran dos años y el día que vencen
    # la facturación deja de andar sin que nadie haya tocado nada.
    assert 395 <= datos.dias_para_vencer <= 400


def test_un_certificado_vencido_se_lee_igual_y_lo_dice():
    """No se rechaza: se informa. Rechazarlo dejaría al cliente sin poder ver
    cuál cargó ni por qué no funciona."""
    cert, _ = _par(dias_de_vida=-10)
    datos = leer_certificado(cert)
    assert datos.vencido


def test_lo_que_no_es_un_certificado_se_rechaza_con_un_mensaje_util():
    with pytest.raises(ArchivoInvalido) as err:
        leer_certificado(b"-----BEGIN CERTIFICATE REQUEST-----\nlo que sea\n")
    # El mensaje nombra el error real: subir el .csr en vez del .crt.
    assert "csr" in str(err.value).lower()


def test_una_clave_con_passphrase_se_rechaza():
    """ARCA se autentica sin nadie delante: no hay dónde escribir la contraseña."""
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    protegida = clave.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(b"secreta"),
    )
    with pytest.raises(ArchivoInvalido) as err:
        leer_clave(protegida)
    assert "contraseña" in str(err.value)


def test_subir_el_certificado_en_el_campo_de_la_clave_se_rechaza():
    cert, _ = _par()
    with pytest.raises(ArchivoInvalido):
        leer_clave(cert)


def test_la_pareja_se_verifica_de_verdad():
    """🔑 El chequeo que ningún nombre de archivo puede dar.

    Un certificado viejo con una clave nueva son dos archivos válidos, se ven
    perfectos en pantalla, y ARCA rechaza la autenticación con un error
    genérico que no habla de esto.
    """
    cert, clave = _par()
    otro_cert, otra_clave = _par()
    assert son_pareja(cert, clave) is True
    assert son_pareja(cert, otra_clave) is False
    assert son_pareja(otro_cert, clave) is False


# ----------------------------------------------------------------------- router

@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def razon(cliente):
    r = cliente.post("/api/razones-sociales",
                     json={"nombre": "Suitrans", "cuit": "30-11111111-1", "punto_venta": 1})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_una_razon_social_sin_configurar_aparece_igual(cliente, razon):
    """La lista es de lo que hay que configurar, no de lo que ya se configuró."""
    filas = cliente.get("/api/arca").json()
    assert len(filas) == 1
    assert filas[0]["razon_social"] == "Suitrans"
    assert filas[0]["certificado"] is None
    assert filas[0]["tiene_clave"] is False
    assert filas[0]["habilitado"] is False
    # El CUIT sale de la razón social: el certificado de ARCA es de un CUIT.
    assert filas[0]["cuit"] == "30-11111111-1"


def test_subir_el_par_y_habilitar(cliente, razon):
    cert, clave = _par()
    r = cliente.post(f"/api/arca/{razon}/certificado",
                     files={"archivo": ("suitrans.crt", cert, "application/x-x509-ca-cert")})
    assert r.status_code == 200, r.text
    assert r.json()["certificado"]["nombre"] == "suitrans.crt"
    assert r.json()["certificado"]["vencido"] is False

    r = cliente.post(f"/api/arca/{razon}/clave",
                     files={"archivo": ("suitrans.key", clave, "application/x-pem-file")})
    assert r.status_code == 200, r.text
    assert r.json()["tiene_clave"] is True
    assert r.json()["coinciden"] is True

    r = cliente.put(f"/api/arca/{razon}", json={"ambiente": "homologacion", "habilitado": True})
    assert r.status_code == 200, r.text
    assert r.json()["habilitado"] is True


def test_avisa_cuando_el_certificado_y_la_clave_no_son_pareja(cliente, razon):
    """🔴 Dos archivos validos que juntos no sirven para facturar."""
    cert, _ = _par()
    _, otra_clave = _par()
    cliente.post(f"/api/arca/{razon}/certificado", files={"archivo": ("c.crt", cert, "text/plain")})
    r = cliente.post(f"/api/arca/{razon}/clave",
                     files={"archivo": ("k.key", otra_clave, "text/plain")})
    assert r.status_code == 200, r.text
    # Los dos archivos son válidos, y aun así esto no sirve para facturar.
    assert r.json()["coinciden"] is False


def test_no_se_puede_habilitar_sin_credenciales(cliente, razon):
    """El estado 'habilitado sin certificado' no se puede ni representar: hay un
    CHECK en la base, y acá el 422 explica qué falta."""
    r = cliente.put(f"/api/arca/{razon}", json={"ambiente": "produccion", "habilitado": True})
    assert r.status_code == 422
    assert "certificado" in r.text


def test_cambiar_el_certificado_deshabilita(cliente, razon):
    """Cambiar una mitad puede romper la pareja: se apaga hasta que alguien
    vuelva a decir que sí."""
    cert, clave = _par()
    cliente.post(f"/api/arca/{razon}/certificado", files={"archivo": ("c.crt", cert, "text/plain")})
    cliente.post(f"/api/arca/{razon}/clave", files={"archivo": ("k.key", clave, "text/plain")})
    cliente.put(f"/api/arca/{razon}", json={"ambiente": "homologacion", "habilitado": True})

    otro_cert, _ = _par()
    r = cliente.post(f"/api/arca/{razon}/certificado",
                     files={"archivo": ("otro.crt", otro_cert, "text/plain")})
    assert r.json()["habilitado"] is False


def test_la_clave_privada_no_sale_nunca_por_la_api(cliente, razon):
    """🔴 El control que no puede faltar: se sube la clave y se revisa que ningún
    endpoint la devuelva, ni entera ni en pedazos."""
    cert, clave = _par()
    cliente.post(f"/api/arca/{razon}/certificado", files={"archivo": ("c.crt", cert, "text/plain")})
    cliente.post(f"/api/arca/{razon}/clave", files={"archivo": ("k.key", clave, "text/plain")})

    # Un trozo reconocible del PEM, que no sea el encabezado generico.
    trozo = clave.decode().splitlines()[2]
    assert len(trozo) > 20
    for ruta in ("/api/arca", f"/api/arca/{razon}"):
        respuesta = cliente.get(ruta) if ruta == "/api/arca" else cliente.put(
            ruta, json={"ambiente": "homologacion", "habilitado": True})
        assert trozo not in respuesta.text, f"{ruta} devolvio parte de la clave privada"
        assert "BEGIN PRIVATE KEY" not in respuesta.text


def test_borrar_saca_las_dos_mitades(cliente, razon):
    cert, clave = _par()
    cliente.post(f"/api/arca/{razon}/certificado", files={"archivo": ("c.crt", cert, "text/plain")})
    cliente.post(f"/api/arca/{razon}/clave", files={"archivo": ("k.key", clave, "text/plain")})
    r = cliente.delete(f"/api/arca/{razon}/credenciales")
    assert r.status_code == 200, r.text
    assert r.json()["certificado"] is None
    assert r.json()["tiene_clave"] is False
    assert r.json()["habilitado"] is False


def test_un_archivo_cualquiera_se_rechaza_en_la_pantalla(cliente, razon):
    """Es el punto de esta pantalla: fallar acá y no al emitir el primer
    comprobante, con un error de ARCA que no habla de la causa."""
    r = cliente.post(f"/api/arca/{razon}/certificado",
                     files={"archivo": ("foto.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")})
    assert r.status_code == 422
    r = cliente.post(f"/api/arca/{razon}/clave",
                     files={"archivo": ("vacio.key", b"", "text/plain")})
    assert r.status_code == 422


def test_sin_sesion_no_se_toca_la_configuracion_de_arca(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/arca").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)


# --------------------------------------------------------------- probar conexion

def _con_par(cliente, razon, *, cert=None, clave=None):
    """Deja el par cargado en esa razón social y devuelve lo que subió."""
    if cert is None or clave is None:
        cert, clave = _par()
    assert cliente.post(f"/api/arca/{razon}/certificado",
                        files={"archivo": ("c.crt", cert, "application/x-x509-ca-cert")}
                        ).status_code == 200
    assert cliente.post(f"/api/arca/{razon}/clave",
                        files={"archivo": ("c.key", clave, "application/x-pem-file")}
                        ).status_code == 200
    return cert, clave


def _wsaa(monkeypatch, *, falla=None):
    """Reemplaza la autenticación real. Devuelve la lista de llamadas.

    🔑 La lista **también sirve de control negativo**: los casos que tienen que
    cortarse antes de salir a la red se verifican con `llamadas == []`, no sólo
    con el código de respuesta. Sin eso, un 400 que igual hubiera llamado a ARCA
    pasaría el test.
    """
    from app.routers import arca as router_arca

    llamadas = []

    async def autenticar(certificado, clave, ambiente, servicio="wsfe"):
        llamadas.append({"ambiente": ambiente, "servicio": servicio,
                         "certificado": certificado, "clave": clave})
        if falla:
            raise RuntimeError(falla)
        return {"token": "UN-TOKEN", "sign": "UNA-FIRMA",
                "expiracion": "2026-08-31T23:59:59-03:00"}

    monkeypatch.setattr(router_arca.arca_wsaa, "autenticar_con_bytes", autenticar)
    return llamadas


def test_probar_autentica_y_no_devuelve_el_ticket(cliente, razon, monkeypatch):
    """El token y la firma son credenciales de sesión: no salen por la API."""
    cert, clave = _con_par(cliente, razon)
    llamadas = _wsaa(monkeypatch)

    r = cliente.post(f"/api/arca/{razon}/probar")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["ok"] is True
    assert cuerpo["cuit"] == "30-11111111-1"
    assert cuerpo["servicio"] == "wsfe"
    assert cuerpo["expira"] == "2026-08-31T23:59:59-03:00"
    assert "UN-TOKEN" not in r.text and "UNA-FIRMA" not in r.text
    assert "token" not in cuerpo and "sign" not in cuerpo
    # Y el par que se mandó a firmar es el que está guardado, no otro.
    assert llamadas[0]["certificado"] == cert
    assert llamadas[0]["clave"] == clave


def test_probar_usa_el_ambiente_guardado_y_el_servicio_de_la_emision(
        cliente, razon, monkeypatch):
    """Probar contra homologación un ARCA de producción no probaría nada."""
    _con_par(cliente, razon)
    assert cliente.put(f"/api/arca/{razon}",
                       json={"ambiente": "produccion", "habilitado": True}
                       ).status_code == 200
    llamadas = _wsaa(monkeypatch)

    r = cliente.post(f"/api/arca/{razon}/probar")

    assert r.status_code == 200, r.text
    assert llamadas == [dict(llamadas[0])]
    assert llamadas[0]["ambiente"] == "produccion"
    # El mismo servicio que autentica `emision_arca`: probar contra otro diría
    # que el certificado anda y dejaría afuera la relación que hace falta.
    assert llamadas[0]["servicio"] == "wsfe"
    assert r.json()["ambiente"] == "produccion"


def test_probar_sin_credenciales_no_sale_a_la_red(cliente, razon, monkeypatch):
    llamadas = _wsaa(monkeypatch)

    r = cliente.post(f"/api/arca/{razon}/probar")

    assert r.status_code == 400
    assert "certificado" in r.json()["detail"]
    assert llamadas == []


def test_probar_con_media_credencial_no_sale_a_la_red(cliente, razon, monkeypatch):
    cert, _ = _par()
    assert cliente.post(f"/api/arca/{razon}/certificado",
                        files={"archivo": ("c.crt", cert, "application/x-x509-ca-cert")}
                        ).status_code == 200
    llamadas = _wsaa(monkeypatch)

    r = cliente.post(f"/api/arca/{razon}/probar")

    assert r.status_code == 400
    assert llamadas == []


def test_probar_con_un_par_que_no_coincide_lo_dice_sin_preguntarle_a_arca(
        cliente, razon, monkeypatch):
    """El rechazo sería seguro, y su texto hablaría de la firma y no de la causa."""
    cert, _ = _par()
    _, otra_clave = _par()
    _con_par(cliente, razon, cert=cert, clave=otra_clave)
    llamadas = _wsaa(monkeypatch)

    r = cliente.post(f"/api/arca/{razon}/probar")

    assert r.status_code == 400
    assert "no son pareja" in r.json()["detail"]
    assert llamadas == []


def test_si_arca_rechaza_el_texto_de_arca_llega_a_la_pantalla(cliente, razon, monkeypatch):
    """Es el caso que este botón existe para mostrar: par impecable, ARCA que no.

    El texto distingue "el certificado no está habilitado para wsfe" de "la hora
    del servidor está corrida", y las dos se arreglan en lugares distintos.
    """
    _con_par(cliente, razon)
    _wsaa(monkeypatch, falla="Computador no autorizado a acceder al servicio")

    r = cliente.post(f"/api/arca/{razon}/probar")

    assert r.status_code == 502
    assert "Computador no autorizado" in r.json()["detail"]


def test_probar_no_crea_la_configuracion_ni_cambia_nada(cliente, razon, monkeypatch):
    """Probar es una consulta: no da de alta la fila ni toca `habilitado`."""
    _con_par(cliente, razon)
    antes = cliente.get("/api/arca").json()
    _wsaa(monkeypatch)

    assert cliente.post(f"/api/arca/{razon}/probar").status_code == 200

    assert cliente.get("/api/arca").json() == antes


def test_probar_una_razon_social_que_no_existe_es_404(cliente, razon, monkeypatch):
    llamadas = _wsaa(monkeypatch)
    assert cliente.post("/api/arca/99999/probar").status_code == 404
    assert llamadas == []
