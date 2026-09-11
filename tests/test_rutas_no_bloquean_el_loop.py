"""Las rutas que tocan algo sincrónico no frenan el loop de uvicorn.

🔴 LibraCargo corre uvicorn con **un solo proceso**. Una ruta `async def` que
llama sincrónico a la base —la `Session` de SQLAlchemy— o a `openssl` por
subproceso frena el loop entero mientras dura: ningún otro request avanza,
`/health` incluido. En un test común no se ve, porque la ruta contesta bien: lo
que hace mal es retener a los demás. Acá se mide eso y nada más.

Cómo: una llamada de cada ruta se reemplaza por una que duerme con
`time.sleep` —bloquea el hilo donde corre, como la consulta real— y, mientras
duerme, se pide `/health` por el **mismo loop**. Si la ruta corre fuera del
loop, `/health` termina antes de que la llamada lenta se despierte; si lo
bloquea, `/health` no puede ni empezar hasta entonces. Se compara contra el
instante en que la llamada lenta **se despertó**, no contra un umbral de
tiempo, así que el resultado no depende de lo rápida que sea la máquina.

Donde la ruta llama a una corrutina que mezcla red con trabajo sincrónico —la
emisión ante ARCA: el WSAA firma el TRA con `openssl` y entre medio se lee la
base—, lo lento va **adentro** de esa corrutina. Pasar la ruta a `def` sin
sacar la corrutina del loop de uvicorn dejaría el test en rojo igual.

Es la misma medición que `tests/test_rutas_no_bloquean_el_loop.py` de
LibraCore, Contalibra y Restolibra. Cada test se probó contra la ruta como
estaba en `origin/develop`: se ponen rojos.
"""

import asyncio
import threading
import time

import httpx
import pytest

from app.routers import configuracion
from app.servicios import emision_arca
from tests.conftest import _crear
from tests.test_comprobantes import facturar, orden
from tests.test_configuracion import EMPRESA, PNG
from tests.test_emision_arca import CUIT, _configurar_arca

#: Lo que duerme la llamada reemplazada. Alcanza con que sea mucho más que lo
#: que tarda un `/health` sin carga.
LENTO = 0.5


class _Lento:
    """Una llamada sincrónica que tarda.

    `time.sleep` y no `asyncio.sleep` es el punto entero: una consulta a la
    base o `openssl` por subproceso no le ceden el control a nadie.
    """

    def __init__(self):
        self.entro = threading.Event()
        self.desperto_en: float | None = None

    def dormir(self):
        self.entro.set()
        time.sleep(LENTO)
        if self.desperto_en is None:
            self.desperto_en = time.monotonic()


def _mientras_duerme(cliente, lento: _Lento, pedir):
    """Corre `pedir(cliente)` con la sesión del `cliente` logueado y, con la
    llamada lenta ya adentro, un `/health` anónimo por el MISMO loop.

    Devuelve la respuesta del pedido, la de `/health` y el instante en que
    `/health` terminó.
    """

    async def _correr():
        transporte = httpx.ASGITransport(app=cliente.app)
        async with (
            httpx.AsyncClient(transport=transporte, base_url="https://testserver",
                              cookies=cliente.cookies) as quien_pide,
            httpx.AsyncClient(transport=transporte, base_url="https://testserver") as anonimo,
        ):
            tarea = asyncio.create_task(pedir(quien_pide))
            # La espera va a un hilo para no ocupar el loop con la espera misma.
            assert await asyncio.to_thread(lento.entro.wait, 10), (
                "la llamada lenta nunca empezó: el parche no intercepta la ruta")
            health = await anonimo.get("/health")
            health_termino = time.monotonic()
            respuesta = await asyncio.wait_for(tarea, 30)
        return respuesta, health, health_termino

    return asyncio.run(_correr())


def _no_bloqueo(lento: _Lento, health, health_termino: float):
    assert health.status_code == 200, health.text
    # Sin esto el test pasaría si el parche no interceptara nada: sin llamada
    # lenta, no hay nada que bloquee.
    assert lento.desperto_en is not None, "la parte lenta no llegó a correr"
    assert health_termino < lento.desperto_en, (
        f"/health terminó {health_termino - lento.desperto_en:.2f}s DESPUÉS de "
        "que se despertara la llamada lenta: la ruta bloqueó el loop mientras dormía"
    )


# ── POST /api/comprobantes ─────────────────────────────────────────────────


def _arca_con(monkeypatch, lento: _Lento, donde: str):
    """Las dos llamadas a ARCA, con `lento` adentro de la que diga `donde`.

    `autenticar` es donde en producción se firma el TRA con `openssl` —la
    parte de `numero_que_sigue`—; `solicitar_cae` es la de `pedir_cae`.
    """

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        if donde == "numera":
            lento.dormir()
        return {"token": "TKN", "sign": "SGN"}

    async def ultimo_numero(pv, tipo, cuit, token, sign, ambiente):
        return 41

    async def solicitar_cae(factura, cuit, token, sign, ambiente):
        if donde == "pide-cae":
            lento.dormir()
        return {"cae": "75123456789012", "cae_vto": "20261231"}

    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "ultimo_numero_autorizado", ultimo_numero)
    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", solicitar_cae)


@pytest.mark.parametrize("donde", ["registra", "numera", "pide-cae"])
def test_facturar_no_frena_el_loop(cliente, datos, monkeypatch, donde):
    """🔑 Tres lugares, porque la ruta tiene tres tramos que bloquean:

    - `registra`: sin ARCA, lo lento es la base (`emite_por_arca`, que lee la
      razón social y `arca_config`). Una ruta `async` la hace en el loop.
    - `numera` y `pide-cae`: con ARCA, lo lento va ADENTRO de las corrutinas
      de `emision_arca`. Es el caso que un `await` desde el loop no resuelve
      aunque la ruta fuera `def`.
    """
    lento = _Lento()
    if donde == "registra":
        razon, numero = datos["razon"], 7
        real = emision_arca.emite_por_arca

        def emite_lento(sesion, razon_social_id):
            lento.dormir()
            return real(sesion, razon_social_id)

        monkeypatch.setattr(emision_arca, "emite_por_arca", emite_lento)
    else:
        razon = _crear(cliente, "/api/razones-sociales", {
            "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
        })
        _configurar_arca(cliente)
        numero = None
        _arca_con(monkeypatch, lento, donde)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)

    respuesta, health, fin = _mientras_duerme(
        cliente, lento, lambda c: c.post("/api/comprobantes", json={
            "fecha": "2026-08-15", "razon_social_id": razon,
            "cliente_id": datos["cliente"], "tipo": "factura_a",
            "punto_venta": 1, "numero": numero, "orden_ids": [a["id"]],
        }))

    assert respuesta.status_code == 201, respuesta.text
    comp = respuesta.json()
    if donde == "registra":
        assert comp["numero"] == 7
    else:
        assert comp["numero"] == 42, "tenía que ser el último autorizado + 1"
        assert comp["cae"] == "75123456789012"
    _no_bloqueo(lento, health, fin)


def test_si_arca_rechaza_sigue_sin_quedar_comprobante(cliente, datos, monkeypatch):
    """🔴 El control de que el arreglo no movió la transacción: con la ruta en
    `def` y el CAE pedido en un loop propio, un rechazo de ARCA sigue sin dejar
    comprobante — el pedido de CAE va adentro de la misma transacción."""
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    _configurar_arca(cliente)

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        return {"token": "TKN", "sign": "SGN"}

    async def ultimo_numero(pv, tipo, cuit, token, sign, ambiente):
        return 41

    async def solicitar_cae(factura, cuit, token, sign, ambiente):
        raise RuntimeError("El comprobante ya fue autorizado")

    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "ultimo_numero_autorizado", ultimo_numero)
    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", solicitar_cae)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)

    r = facturar(cliente, datos, [a], razon=razon, numero=None)
    assert r.status_code == 502, r.text
    assert "ya fue autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


# ── POST /api/configuracion/logo ───────────────────────────────────────────


def test_subir_el_logo_no_frena_el_loop(cliente, monkeypatch):
    """Lo lento es la lectura de la configuración, que es la base."""
    r = cliente.put("/api/configuracion", json=EMPRESA)
    assert r.status_code == 200, r.text
    lento = _Lento()
    real = configuracion._traer

    def traer_lento(sesion):
        lento.dormir()
        return real(sesion)

    monkeypatch.setattr(configuracion, "_traer", traer_lento)

    respuesta, health, fin = _mientras_duerme(cliente, lento, lambda c: c.post(
        "/api/configuracion/logo", files={"archivo": ("logo.png", PNG, "image/png")}))

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["tiene_logo"] is True
    _no_bloqueo(lento, health, fin)
    # El archivo tiene que haber llegado entero, leído del `SpooledTemporaryFile`.
    assert cliente.get("/api/configuracion/logo").content == PNG
