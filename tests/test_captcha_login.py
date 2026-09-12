"""El captcha ALTCHA del login, con la función REAL de libraauth puesta.

El resto de la suite corre con el doble que aprueba todo (`_captcha_aprobado`
en el conftest), así que esto es lo único que se pondría rojo si alguien
sacara `captcha=True` de `app/routers/auth.py`: el desafío dejaría de existir
y el login sin captcha volvería a entrar.

La lógica del captcha —firma, vencimiento, anti-replay— la prueba libraauth.
Acá se mide el cableado: que la ruta esté, que no se cachee y que el login la
exija.
"""

from __future__ import annotations

import pytest
from altcha import Challenge, Payload, solve_challenge
from libraauth.captcha import Captcha
from libraauth.session_auth import CAPTCHA_INVALIDO

from tests.conftest import CAPTCHA_DE_ORIGINAL, CLAVE, SECRETO_DE_PRUEBA, USUARIO


@pytest.fixture
def captcha_real(cliente, _captcha_aprobado):
    """El `cliente` de la suite, con la función real de libraauth devuelta.

    Pide `cliente` primero porque ese fixture ya loguea al armarse, y con el
    captcha real ese login daría 400. Pide `_captcha_aprobado` por nombre para
    que el orden de desarme sea el inverso: acá se vuelve al doble y después el
    conftest vuelve a la original.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("libraauth.session_auth._captcha_de", CAPTCHA_DE_ORIGINAL)
        yield cliente


def _resolver(c) -> str:
    r = c.get("/auth/captcha")
    assert r.status_code == 200, r.text
    ch = Challenge.from_dict(r.json())
    return Payload(ch, solve_challenge(ch)).to_base64()


def test_el_desafio_tiene_la_forma_del_widget_y_no_se_cachea(captcha_real):
    r = captcha_real.get("/auth/captcha")
    assert r.status_code == 200, r.text
    desafio = r.json()
    assert isinstance(desafio.get("parameters"), dict)
    assert isinstance(desafio.get("signature"), str)
    assert "no-store" in r.headers.get("cache-control", "")


def test_login_sin_captcha_da_400_aun_con_la_clave_correcta(captcha_real):
    r = captcha_real.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    assert r.status_code == 400, r.text
    assert CAPTCHA_INVALIDO in r.text


def test_login_con_el_captcha_resuelto_entra_una_sola_vez(captcha_real):
    # Un `Captcha` barato en `app.state`, que es donde lo busca la función real:
    # con el costo de producción cada resolución tarda del orden de un segundo.
    captcha_real.app.state.captcha = Captcha(
        SECRETO_DE_PRUEBA, costo=1, contador_min=1, contador_rango=5
    )
    solucion = _resolver(captcha_real)
    cuerpo = {"username": USUARIO, "password": CLAVE, "captcha": solucion}

    r = captcha_real.post("/auth/login", json=cuerpo)
    assert r.status_code == 200, r.text

    # Control: la misma solución no sirve dos veces. Sin esto, el 200 de arriba
    # pasaría también con un router que no mirara el captcha.
    r = captcha_real.post("/auth/login", json=cuerpo)
    assert r.status_code == 400, r.text
    assert CAPTCHA_INVALIDO in r.text
