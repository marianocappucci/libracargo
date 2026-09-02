"""La configuración de ARCA, que desde el 2026-09-02 es la del motor.

Este archivo tenía 401 líneas y probaba un router propio: leer un certificado,
detectar la clave con passphrase, verificar que el par fuera pareja, subirlo,
habilitarlo. Todo eso vive ahora en LibraCore —`arca_certificados`,
`arca_router`— y tiene ahí su propia batería. Repetirla acá sería **medir el kit
desde el consumidor**: pasaría en verde aunque este producto no lo hubiera
montado bien.

Lo que queda es lo que es de este producto y de nadie más:

1. **El gate.** El router del motor no trae ninguno —lo pone quien lo monta— y
   acá se sube una clave privada.
2. **La ruta.** `/api/arca`, que es la que este producto ya publicó; el default
   del kit es otro.
3. **Que el montaje llegue a un `CERTS_DIR` y a una base de verdad.** Es lo que
   ninguna suite del kit puede decir: allá los dos son de mentira.
"""

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from libracore import config_manager

from app.main import crear_app
from tests.conftest import config_de_prueba, par_de_arca


def _subir(cliente, ambiente: str, cert: bytes, clave: bytes) -> None:
    """Sube el par de un ambiente. El `ambiente` viaja SIEMPRE, a propósito.

    Sin él el backend cae al selector, que casi siempre coincide — y esa
    coincidencia es lo que hace peligroso el descuido: anda en todas las pruebas
    y falla el día que alguien sube el par de producción parado en homologación.
    """
    r = cliente.post("/api/arca/certificado", params={"ambiente": ambiente},
                     files={"archivo": ("c.crt", cert, "application/x-x509-ca-cert")})
    assert r.status_code == 200, r.text
    r = cliente.post("/api/arca/clave", params={"ambiente": ambiente},
                     files={"archivo": ("c.key", clave, "application/x-pem-file")})
    assert r.status_code == 200, r.text


# ── 1. El gate, que lo pone este producto ──────────────────────────────────

def test_sin_sesion_no_se_toca_la_configuracion_de_arca(engine, monkeypatch):
    """🔴 El router del motor **no trae gate**: lo pone el `include_router`.

    Es una línea (`dependencies=[Depends(require_admin)]`) y sacarla no rompe
    nada visible: la pantalla sigue andando para el admin, que es quien la
    prueba. Lo que queda abierto es subir y **descargar el estado de** la clave
    privada del cliente sin estar logueado.
    """
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    anonimo = TestClient(crear_app(config_de_prueba(), sembrar_admin=False),
                         base_url="https://testserver")
    try:
        assert anonimo.get("/api/arca").status_code == 401
        assert anonimo.get("/api/arca/estado").status_code == 401
        assert anonimo.post("/api/arca/certificado",
                            files={"archivo": ("c.crt", b"lo que sea", "text/plain")}
                            ).status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)


# ── 2. La ruta ─────────────────────────────────────────────────────────────

def test_una_instancia_que_nunca_facturo_contesta_null_y_no_rompe(cliente):
    """El prefijo es de este producto, y el default del kit es `/config/arca`.

    `null` y no un 404: la pantalla tiene que poder abrirse en una instancia
    recién creada. Es además el estado de las tres instancias vivas al momento
    de escribir esto — `arca_config` vacía en las tres.
    """
    r = cliente.get("/api/arca")
    assert r.status_code == 200, r.text
    assert r.json() is None

    estado = cliente.get("/api/arca/estado")
    assert estado.status_code == 200, estado.text
    assert estado.json()["configurado"] is False


# ── 3. Que el montaje llegue a un disco y a una base de verdad ─────────────

def test_el_par_queda_escrito_en_el_CERTS_DIR_de_esta_instancia(cliente):
    """🔑 Lo que ninguna suite del kit puede decir.

    Allá `CERTS_DIR` y la base son de mentira. Acá se comprueba que la app que
    este producto arma escribe el certificado **en el directorio que después el
    backup se lleva**: si el montaje resolviera otro, la pantalla mostraría el
    certificado cargado igual —lo lee del mismo lugar donde lo escribió— y el
    ZIP saldría sin credenciales. Ver `test_respaldo`.
    """
    cert, clave = par_de_arca()
    _subir(cliente, "homologacion", cert, clave)

    escritos = {
        nombre: open(os.path.join(config_manager.CERTS_DIR, nombre), "rb").read()
        for nombre in os.listdir(config_manager.CERTS_DIR)
    }
    assert cert in escritos.values(), sorted(escritos)
    assert clave in escritos.values(), sorted(escritos)


def test_subir_el_par_de_un_ambiente_no_toca_el_del_otro(cliente):
    """El motivo por el que este producto se movió al motor, extremo a extremo.

    Con un solo par guardado, probar contra homologación obligaba a **pisar** el
    certificado de producción — una operación destructiva y de ida y vuelta,
    justo sobre la credencial que después tiene que quedar bien. Acá se ve que
    conviven: se sube uno y el otro sigue donde estaba, con su vencimiento.

    Se mira `pares`, que es lo que la pantalla muestra, y no el archivo: el dato
    que convierte el corte a facturación real en una decisión y no en un salto a
    ciegas es justamente ése.
    """
    produccion = par_de_arca()
    _subir(cliente, "produccion", *produccion)
    estado = cliente.get("/api/arca/estado").json()
    assert estado["pares"]["produccion"]["completo"] is True
    assert estado["pares"]["homologacion"]["completo"] is False

    homologacion = par_de_arca()
    _subir(cliente, "homologacion", *homologacion)
    estado = cliente.get("/api/arca/estado").json()
    assert estado["pares"]["homologacion"]["completo"] is True
    assert estado["pares"]["produccion"]["completo"] is True, (
        "subir el par de homologación pisó el de producción")
    # Y son dos certificados distintos, no el mismo leído dos veces.
    assert (estado["pares"]["produccion"]["sujeto"]
            == estado["pares"]["homologacion"]["sujeto"]), "los helpers usan el mismo CN"
    assert produccion[0] != homologacion[0], "el control: son dos pares distintos"


def test_la_clave_privada_no_sale_nunca_por_la_api(cliente):
    """No es paranoia: es una pantalla que abre cualquier administrador.

    Se mira el cuerpo crudo y no una clave del JSON: el modo de fallar es que
    aparezca en un campo que a nadie se le ocurrió mirar.
    """
    cert, clave = par_de_arca()
    _subir(cliente, "homologacion", cert, clave)

    for ruta in ("/api/arca", "/api/arca/estado"):
        cuerpo = cliente.get(ruta).content
        assert b"PRIVATE KEY" not in cuerpo, ruta
        assert clave.strip() not in cuerpo, ruta


def test_lo_que_no_es_un_certificado_se_rechaza_antes_de_tocar_el_disco(cliente):
    """La validación del kit, ejercitada a través de ESTE montaje.

    No repite la batería de `arca_certificados` —eso es del motor—: comprueba
    que el camino que arma este producto la atraviesa. Un mount que la esquivara
    escribiría los bytes que lleguen.
    """
    r = cliente.post("/api/arca/certificado", params={"ambiente": "homologacion"},
                     files={"archivo": ("c.crt", b"esto no es un PEM", "text/plain")})
    assert r.status_code == 422, r.text
    assert not os.path.isdir(config_manager.CERTS_DIR) or not os.listdir(
        config_manager.CERTS_DIR), "escribió el archivo igual"


@pytest.mark.parametrize("ambiente", ["", "prod", "PRODUCCION_"])
def test_un_ambiente_desconocido_no_cae_a_produccion(cliente, ambiente):
    """🔴 El destino de un upload es un archivo que se **sobrescribe**.

    Ante un ambiente que no reconoce, el kit contesta 422 y no escribe. Se prueba
    desde acá porque lo que se está midiendo es que este producto no le pase por
    arriba con un default propio: el vacío cae al selector —`homologacion` en una
    instancia nueva— y cualquier otra cosa se rechaza.
    """
    cert, _ = par_de_arca()
    r = cliente.post("/api/arca/certificado", params={"ambiente": ambiente},
                     files={"archivo": ("c.crt", cert, "text/plain")})
    if ambiente == "":
        assert r.status_code == 200, r.text
        assert r.json()["pares"]["produccion"]["completo"] is False, (
            "sin ambiente cayó al par de PRODUCCIÓN")
    else:
        assert r.status_code == 422, r.text
