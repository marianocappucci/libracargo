"""El log de accesos: quién entró, quién salió, y quién lo intentó sin lograrlo.

🔴 **Esta mitad no existía en este producto, y no era sólo un log que faltaba.**
`libraauth` registra los accesos si el producto configura
`app.state.auth_events`, y es **opt-in por ausencia**: sin esa línea no se
registra nada *y además* `contar_fallidos_seguro` devuelve 0 — que significa
"nadie agotó intentos"—, con lo que **el rate limiting del login nunca
dispara**. Los otros cinco productos de la familia sí lo cablean.

Medido el 2026-08-22 antes de arreglarlo: `auth_log` existía y tenía **cero
filas en las tres instancias**, incluida la de Suitrans en producción. O sea
que no había registro de quién entraba, y el login no tenía freno contra fuerza
bruta.

Lo que fijan estos tests, en orden de lo que se rompe sin que se note:

1. Que los eventos **se escriban**. Sin esto no hay log ni contador.
2. 🔴 Que el bloqueo **dispare de verdad**, punta a punta por HTTP. Es lo único
   que distingue "el repositorio está cableado" de "la defensa funciona": el
   cableado se puede tener y el contador fallar igual — pasó en tres productos
   con `auth_log.ts` de tipo TEXT.
3. Que el endpoint devuelva los accesos con la MISMA forma que el `AccesoLog`
   de `libra-ui`, que es lo que rinde la pantalla compartida en el resto.
4. Que sea admin-only: quién entró y desde qué IP no es dato de cualquiera.
"""

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

ADMIN, CLAVE = "admin", "clave-de-prueba"


def _app(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", ADMIN)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    return TestClient(crear_app(cfg), base_url="https://testserver")


@pytest.fixture
def sin_loguear(engine, sesion, monkeypatch):
    """Un cliente que todavía no entró: los tests de login necesitan hacerlo
    ellos, no encontrarlo hecho."""
    c = _app(engine, monkeypatch)
    yield c
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def cliente(sin_loguear):
    assert sin_loguear.post(
        "/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    return sin_loguear


def accesos(c):
    r = c.get("/api/auditoria/accesos")
    assert r.status_code == 200, r.text
    return r.json()


def test_entrar_queda_registrado(cliente):
    """El caso base: sin esto no hay nada que mirar ni que contar."""
    eventos = accesos(cliente)

    assert [e["evento"] for e in eventos] == ["login"]
    assert eventos[0]["username"] == ADMIN


def test_el_intento_fallido_tambien_queda(sin_loguear):
    """**El evento que más importa** — un login que sale bien es rutina; el que
    falla es la señal. Y se anota el username TIPEADO, que puede no existir:
    un barrido contra usuarios inventados es justamente lo que hay que ver."""
    sin_loguear.post("/auth/login", json={"username": "fantasma", "password": "x"})

    eventos = accesos_de_admin(sin_loguear)
    assert [e["evento"] for e in eventos] == ["login_fallido"]
    assert eventos[0]["username"] == "fantasma"


def accesos_de_admin(c):
    """Los accesos son admin-only, así que hay que entrar para leerlos."""
    assert c.post("/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    todos = accesos(c)
    # Se descarta el `login` que acaba de hacer este helper: lo que el test
    # quiere ver es lo de antes.
    return [e for e in todos if e["evento"] != "login"]


def test_salir_queda_registrado(cliente):
    cliente.post("/auth/logout")

    assert "logout" in [e["evento"] for e in accesos_de_admin(cliente)]


def test_a_los_cinco_intentos_fallidos_el_login_BLOQUEA(sin_loguear):
    """🔴 **El test que prueba que la defensa existe**, y el que este producto
    no habría pasado hasta hoy.

    Punta a punta por HTTP, no mirando el repositorio: tener el repositorio
    cableado no alcanza — en Gestiolibra, MedLibra y VentaLibra estaba cableado
    y el bloqueo igual no disparaba, porque el contador reventaba contra una
    columna `ts` de tipo TEXT y el error se tragaba devolviendo 0.

    El umbral del motor es 5 en 15 minutos. El sexto tiene que dar **429**.
    """
    for _ in range(5):
        r = sin_loguear.post("/auth/login", json={"username": "fantasma", "password": "x"})
        assert r.status_code == 401, "un intento fallido tiene que dar 401"

    bloqueado = sin_loguear.post(
        "/auth/login", json={"username": "fantasma", "password": "x"})

    assert bloqueado.status_code == 429, (
        "el sexto intento no bloqueó: el rate limiting del login está inerte")


def test_el_bloqueo_alcanza_tambien_a_la_clave_CORRECTA(sin_loguear):
    """🔴 El control que distingue un bloqueo de un 401 con otro número.

    Si el sexto intento diera 429 sólo por tener la clave mal, no habría
    bloqueo: habría un mensaje distinto para el mismo rechazo. Lo que prueba
    que la puerta está cerrada es que **ni la clave buena entra**.
    """
    for _ in range(5):
        sin_loguear.post("/auth/login", json={"username": ADMIN, "password": "mal"})

    r = sin_loguear.post("/auth/login", json={"username": ADMIN, "password": CLAVE})

    assert r.status_code == 429, "con la clave correcta entró: no estaba bloqueado"


def test_el_bloqueo_queda_anotado(sin_loguear):
    """Un bloqueo es un evento en sí mismo: es la firma de un ataque, y sin
    anotarlo el log muestra cinco fallidos y después silencio."""
    for _ in range(6):
        sin_loguear.post("/auth/login", json={"username": "fantasma", "password": "x"})

    # El admin tampoco puede entrar (está bloqueado por IP), así que se lee la
    # tabla por el repositorio en vez de por HTTP.
    from libraauth.auth_events import LOGIN_BLOQUEADO
    repo = sin_loguear.app.state.auth_events
    assert LOGIN_BLOQUEADO in [e["evento"] for e in repo.listar()]


def test_los_accesos_tienen_la_forma_que_rinde_libra_ui(cliente):
    """La pantalla compartida de los otros cinco productos espera estos campos.
    Si acá divergiera, la pestaña se vería distinta sin que nadie lo decidiera.
    """
    evento = accesos(cliente)[0]

    assert set(evento) == {"id", "ts", "evento", "username", "ip", "detalle"}
    assert isinstance(evento["ts"], str) and len(evento["ts"]) >= 19, evento["ts"]


def test_los_accesos_son_solo_para_admin(sin_loguear):
    """Quién entró y desde qué IP no es dato de cualquiera — y sin login, menos."""
    assert sin_loguear.get("/api/auditoria/accesos").status_code in (401, 403)


def test_el_arranque_avisaria_si_alguien_saca_el_cableado(cliente):
    """El chequeo del motor sobre esta app tiene que dar limpio.

    Es el control positivo de que `verificar_registro_de_accesos` puede decir
    "está todo bien" — y el que se pondría rojo el día que alguien borre la
    línea de `app.state.auth_events`, que es exactamente como este producto
    llegó hasta acá.
    """
    from libraauth.auth_events import advertir_si_no_hay_registro

    assert advertir_si_no_hay_registro(cliente.app) == ""
