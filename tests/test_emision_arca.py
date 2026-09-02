"""Emitir por ARCA: F8.

Hasta acá este producto **registraba** comprobantes con un número tipeado a
mano. Ahora, cuando la razón social tiene ARCA habilitado, el número lo da ARCA
y el comprobante nace con CAE.

> 🔑 **El test que manda es el del rechazo**: si ARCA dice que no, **no puede
> quedar comprobante**. Un comprobante con un número que ARCA no autorizó deja
> el correlativo tomado de este lado y libre del otro — y el próximo intento
> choca contra la unicidad de la base sin que nadie entienda por qué.
"""

from decimal import Decimal

import pytest
from libracore.db import arca_config as db_arca_config

from app.servicios import emision_arca

# Las fixtures `cliente` y `datos` salen del conftest; de acá sólo los
# helpers, que son funciones normales.
from tests.conftest import _crear, par_de_arca
from tests.test_comprobantes import facturar, orden

CUIT = "20-28993360-4"


def _configurar_arca(cliente, *, cuit=CUIT, punto_venta=5,
                     ambiente="homologacion", empresa=emision_arca.EMPRESA_ARCA):
    """Deja la instancia lista para emitir: el par en disco y el CUIT cargado.

    Es **una configuración por instancia**, no una por razón social: así la
    guarda el motor. Cuál de las razones sociales emite lo dice el CUIT.

    ⚠️ **El `PUT` va primero, y no es indistinto.** El upload también crea la
    fila si no existe, pero con el slug por defecto del producto; un `PUT`
    posterior con otro `empresa` crea una **segunda** fila en vez de renombrar
    la primera —`guardar()` usa el slug del payload derecho, y sólo cae en la
    fila activa cuando llega vacío—. Guardando primero, el upload encuentra la
    fila activa y escribe en ésa.
    """
    r = cliente.put("/api/arca", json={
        "empresa": empresa, "cuit": cuit, "punto_venta": punto_venta,
        "ambiente": ambiente, "alias": "",
    })
    assert r.status_code == 200, r.text
    certificado, clave = par_de_arca()
    for tramo, archivo in (("certificado", certificado), ("clave", clave)):
        r = cliente.post(f"/api/arca/{tramo}", params={"ambiente": ambiente},
                         files={"archivo": (f"c.{tramo}", archivo, "text/plain")})
        assert r.status_code == 200, r.text


@pytest.fixture
def razon_con_arca(cliente, datos):
    """Una razón social cuyo CUIT es el del certificado cargado."""
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    _configurar_arca(cliente)
    return razon


def _arca_responde(monkeypatch, *, ultimo=41, cae="75123456789012",
                   cae_vto="20261231", falla_numero=None, falla_cae=None):
    """Mockea las dos llamadas a ARCA. Devuelve la lista de lo que se le pidió."""
    pedidos = []

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        pedidos.append(("autenticar", ambiente, cert, key))
        return {"token": "TKN", "sign": "SGN"}

    async def ultimo_numero(pv, tipo, cuit, token, sign, ambiente):
        pedidos.append(("ultimo", pv, tipo, cuit))
        if falla_numero:
            raise RuntimeError(falla_numero)
        return ultimo

    async def solicitar_cae(factura, cuit, token, sign, ambiente):
        pedidos.append(("cae", factura))
        if falla_cae:
            raise RuntimeError(falla_cae)
        return {"cae": cae, "cae_vto": cae_vto}

    # `autenticar` y no `autenticar_con_bytes`: desde que el par lo guarda el
    # motor, lo que viaja son los **paths** que resuelve
    # `arca_credenciales.paths_en_disco`.
    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "ultimo_numero_autorizado", ultimo_numero)
    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", solicitar_cae)
    return pedidos


# ── El camino que sostiene la instancia viva ────────────────────────────────

def test_sin_arca_sigue_registrando_con_numero_a_mano(cliente, datos):
    """🔑 El control que evita la regresión.

    La instancia del cliente **no tiene ningún certificado cargado**. Si emitir
    reemplazara al alta de forma literal, se quedaría sin poder facturar.
    """
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a], numero=7)
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["numero"] == 7
    assert comp.get("cae") in (None, "")


def test_sin_arca_y_sin_numero_lo_dice(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    r = cliente.post("/api/comprobantes", json={
        "fecha": "2026-08-15", "razon_social_id": datos["razon"],
        "cliente_id": datos["cliente"], "tipo": "factura_a",
        "punto_venta": 1, "orden_ids": [a["id"]],
    })
    assert r.status_code == 422
    assert "numero" in r.json()["detail"].lower()


# ── Emitir ──────────────────────────────────────────────────────────────────

def test_con_arca_el_numero_lo_da_arca(cliente, datos, razon_con_arca, monkeypatch):
    """Y el del payload se ignora: ARCA rechaza cualquiera que no sea el que
    sigue, así que mandarlo no tiene sentido."""
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)

    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=999)
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["numero"] == 42, "tenia que ser el ultimo autorizado + 1"
    assert comp["cae"] == "75123456789012"
    assert comp["cae_vencimiento"] == "2026-12-31"
    # El punto de venta sale de la razon social, no del payload.
    assert comp["punto_venta"] == 5
    assert ("ultimo", 5, 1, "20-28993360-4") in pedidos


def test_la_cuenta_corriente_nombra_el_numero_real(cliente, datos, razon_con_arca,
                                                   monkeypatch):
    """🔑 El concepto del movimiento se armaba con el número del payload. Con
    ARCA ese viene vacío, así que la cuenta corriente nombraría un comprobante
    inexistente."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    comp = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None).json()

    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    concepto = cuenta["movimientos"][0]["movimiento"]["concepto"]
    assert concepto == "Factura A 0005-00000042", concepto
    assert str(comp["numero"]) in concepto


# ── El rechazo, que es lo que importa ───────────────────────────────────────

def test_si_arca_rechaza_el_cae_no_queda_comprobante(cliente, datos, razon_con_arca,
                                                     monkeypatch):
    """🔴 Ni comprobante, ni movimiento de cuenta, y las órdenes vuelven a
    pendientes.

    Un comprobante con un número que ARCA no autorizó deja el correlativo
    tomado de este lado y libre del otro: el próximo intento choca contra la
    unicidad de la base sin que nadie entienda por qué.
    """
    _arca_responde(monkeypatch, falla_cae="El comprobante ya fue autorizado")
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)

    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None)
    assert r.status_code == 502, r.text
    assert "ya fue autorizado" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    quedo = cliente.get(f"/api/ordenes/{a['id']}").json()
    assert quedo["estado"] == "pendiente", "la orden tenia que volver a pendiente"
    assert quedo["comprobante_id"] is None


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, razon_con_arca,
                                                    monkeypatch):
    _arca_responde(monkeypatch, falla_numero="Computador no autorizado")
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)

    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None)
    assert r.status_code == 502
    assert "no autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"


# ── La guarda: factura UNA razón social, y la elige el CUIT ────────────────
#
# 🔴 **Acá se perdió el `habilitado`.** La tabla propia tenía una bandera para
# "cargué el par y todavía no quiero emitir", y `arca_config` no la tiene. Lo
# que la reemplaza no es un flag equivalente: son los **dos pares**. Cargar el
# de homologación y dejar el selector ahí es el estado de "todavía no emito de
# verdad", y es mejor que la bandera porque además deja probar.

def test_una_razon_social_con_otro_cuit_no_emite(cliente, datos, monkeypatch):
    """🔑 La guarda que reemplaza al `habilitado`, y por qué es el CUIT.

    El certificado de ARCA es **de un CUIT**. Una razón social con otro CUIT no
    puede emitir con ese par —ARCA lo rechazaría— así que sigue registrando a
    mano, que es exactamente lo que hacía antes sin habilitar.

    Y el control importa tanto como el caso: la instancia SÍ tiene ARCA
    configurado. Sin eso, "no emitió" pasaría igual con la configuración vacía.
    """
    _configurar_arca(cliente)
    otra = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Otra SA", "cuit": "30-99999999-7", "punto_venta": 3,
    })

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=otra)
    r = facturar(cliente, datos, [a], razon=otra, numero=11)
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 11, "tenia que registrar con el numero a mano"
    assert pedidos == [], "no tenia que hablar con ARCA"


def test_el_cuit_matchea_con_guiones_y_sin_guiones(cliente, datos, monkeypatch):
    """El mismo CUIT escrito de las dos formas es el mismo CUIT.

    `razones_sociales.cuit` admite `20-28993360-4`; en la pantalla compartida se
    tipea como salga. Comparar los textos crudos haría que la razón social
    correcta **deje de emitir** y vuelva al alta manual — un rojo que no se ve,
    porque el alta sigue andando.
    """
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Con Guiones SA", "cuit": "20-28993360-4", "punto_venta": 5,
    })
    _configurar_arca(cliente, cuit="20289933604")

    _arca_responde(monkeypatch, ultimo=7)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    r = facturar(cliente, datos, [a], razon=razon, numero=None)
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 8


def test_una_razon_social_sin_cuit_no_emite(cliente, datos, monkeypatch):
    """Sin CUIT no hay con qué comparar, y adivinar sería facturar por otro."""
    _configurar_arca(cliente)
    sin_cuit = _crear(cliente, "/api/razones-sociales", {"nombre": "Sin CUIT SA"})

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=sin_cuit)
    r = facturar(cliente, datos, [a], razon=sin_cuit, numero=4)
    assert r.status_code == 201, r.text
    assert pedidos == [], "no tenia que hablar con ARCA"


def test_con_dos_configuraciones_activas_no_elige_por_indice(cliente, datos,
                                                             monkeypatch):
    """🔴 El motor hace `arca_cfg[0]`. Este producto no puede.

    `libracore.arca_facturacion` elige la primera fila activa porque los
    productos que lo usan son de instancia única con una sola empresa. Este
    modela N razones sociales: con dos filas, elegir por índice **factura con el
    CUIT equivocado sin fallar** — el comprobante sale, lo firma otro
    contribuyente, y aparece en el libro IVA de un tercero.

    La segunda fila no se puede crear desde la pantalla, pero sí desde un
    script, un `curl` o un restore de otra instancia. Por eso la guarda está en
    el camino de emisión, que es el que hace daño.
    """
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    _configurar_arca(cliente)
    db_arca_config.crear_arca_config(
        empresa="colada", cuit="30-99999999-7", punto_venta=9,
        clave_path="", certificado_path="", ambiente="homologacion",
    )

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    r = facturar(cliente, datos, [a], razon=razon, numero=None)
    assert r.status_code == 409, r.text
    assert "colada" in r.json()["detail"], "el mensaje tiene que nombrar las filas"
    assert pedidos == [], "salio a ARCA sin saber con que CUIT"
    assert cliente.get("/api/comprobantes").json() == [], "quedo comprobante"


def test_guardar_con_otro_slug_despues_de_subir_deja_DOS_filas(cliente):
    """Lo encontró un test que quería medir otra cosa, y es del router compartido.

    El upload crea la fila si no existe, con el slug por defecto del producto.
    Un `PUT` posterior con otro `empresa` **no la renombra**: crea una segunda,
    porque `guardar()` sólo cae en la fila activa cuando el payload llega con el
    slug vacío. En este producto la pantalla manda siempre el mismo, así que no
    se dispara desde la UI — pero sí desde un `curl` o un script, y el resultado
    es una instancia con dos configuraciones y ninguna señal.

    Se deja escrito acá, y no como un pendiente: es la razón por la que
    `ArcaAmbiguo` existe del lado de la emisión.
    """
    certificado, clave = par_de_arca()
    assert cliente.post("/api/arca/certificado", params={"ambiente": "homologacion"},
                        files={"archivo": ("c.crt", certificado, "text/plain")},
                        ).status_code == 200
    assert cliente.put("/api/arca", json={
        "empresa": "otro-slug", "cuit": CUIT, "punto_venta": 1,
        "ambiente": "homologacion", "alias": "",
    }).status_code == 200

    filas = {c["empresa"] for c in db_arca_config.obtener_todas_arca_configs()}
    assert filas == {emision_arca.EMPRESA_ARCA, "otro-slug"}, filas


def test_la_emision_encuentra_la_fila_aunque_el_slug_sea_otro(cliente, datos,
                                                              monkeypatch):
    """🔑 El slug no puede producir la falla muda que documenta el motor.

    Cuatro productos leen su configuración con un slug **fijo**, y ahí una fila
    creada como `default` es una pantalla que dice "Guardado" y una facturación
    que dice "ARCA no está configurado". Acá la emisión resuelve **la fila
    activa** y no el slug, justamente para que un literal de más en el frontend
    —que vive en otro lenguaje y no lo mira ningún import— no pueda causarlo.
    """
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    _configurar_arca(cliente, empresa="un-slug-que-nadie-espera")

    _arca_responde(monkeypatch, ultimo=99)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    r = facturar(cliente, datos, [a], razon=razon, numero=None)
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 100


def test_sin_el_par_en_disco_no_emite_aunque_la_fila_exista(cliente, datos,
                                                            monkeypatch):
    """Una fila con el CUIT y sin archivos es una instancia a medio configurar.

    Pasa de verdad: el `PUT` de la pantalla crea la fila antes de que nadie suba
    nada. Salir a ARCA desde ahí da un error de autenticación que no habla de la
    causa; registrar a mano es lo correcto.
    """
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    r = cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT, "punto_venta": 5,
        "ambiente": "homologacion", "alias": "",
    })
    assert r.status_code == 200, r.text

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    assert facturar(cliente, datos, [a], razon=razon, numero=6).status_code == 201
    assert pedidos == [], "no tenia que hablar con ARCA"


def test_el_selector_manda_cual_de_los_dos_pares_firma(cliente, datos, monkeypatch):
    """🔑 Lo que toda esta línea de trabajo vino a habilitar.

    Con los dos pares cargados, mover `ambiente` cambia **con cuál se firma** —y
    no obliga a pisar un archivo. Se mide el path que recibe `autenticar`, que
    es lo único que distingue un par del otro: el ambiente que se le pasa
    coincide en los dos casos por venir del mismo lugar, así que asertar sólo
    sobre él pasaría con el par equivocado.
    """
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    _configurar_arca(cliente, ambiente="homologacion")
    certificado, clave = par_de_arca()
    for tramo, archivo in (("certificado", certificado), ("clave", clave)):
        assert cliente.post(f"/api/arca/{tramo}", params={"ambiente": "produccion"},
                            files={"archivo": ("c", archivo, "text/plain")},
                            ).status_code == 200

    pedidos = _arca_responde(monkeypatch, ultimo=1)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    facturar(cliente, datos, [a], razon=razon, numero=None)
    con_homologacion = [p for p in pedidos if p[0] == "autenticar"][0]
    assert con_homologacion[1] == "homologacion"

    assert cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT, "punto_venta": 5,
        "ambiente": "produccion", "alias": "",
    }).status_code == 200

    pedidos = _arca_responde(monkeypatch, ultimo=1)
    b = orden(cliente, datos, "1000.00", razon_social_id=razon)
    facturar(cliente, datos, [b], razon=razon, numero=None)
    con_produccion = [p for p in pedidos if p[0] == "autenticar"][0]
    assert con_produccion[1] == "produccion"
    assert con_produccion[2] != con_homologacion[2], (
        "los dos ambientes firmaron con el MISMO archivo de certificado")


# ── Los importes que se le mandan ───────────────────────────────────────────

def test_la_factura_c_va_sin_iva_discriminado(cliente, datos, razon_con_arca,
                                              monkeypatch):
    """No es una simplificación: ARCA exige `ImpIVA = 0` e `ImpNeto = ImpTotal`
    para los tipos C, y rechaza el comprobante si se manda el IVA aparte."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    facturar(cliente, datos, [a], razon=razon_con_arca, numero=None, tipo="factura_c")

    enviado = [p[1] for p in pedidos if p[0] == "cae"][0]
    assert enviado["tipo"] == 11
    assert enviado["iva_amount"] == 0.0
    assert enviado["subtotal"] == enviado["total"]


def test_la_factura_a_manda_el_iva_aparte(cliente, datos, razon_con_arca, monkeypatch):
    """La otra mitad: sin esto, "el IVA va en cero" pasaría igual con un
    servicio que siempre manda cero."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    comp = facturar(cliente, datos, [a], razon=razon_con_arca,
                    numero=None, tipo="factura_a").json()

    enviado = [p[1] for p in pedidos if p[0] == "cae"][0]
    assert enviado["tipo"] == 1
    assert enviado["iva_amount"] > 0
    assert enviado["iva_amount"] == float(Decimal(comp["iva"]))
    assert enviado["subtotal"] == float(Decimal(comp["neto"]))
