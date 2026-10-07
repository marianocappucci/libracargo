"""Emitir por ARCA: F8.

Hasta acá este producto **registraba** comprobantes con un número tipeado a
mano. Ahora el número lo da ARCA y el comprobante nace con CAE, siempre con el
CUIT de «Datos de la empresa» (ADR-035): si no es el del certificado, no se emite.

> 🔑 **El test que manda es el del rechazo**: si ARCA dice que no, **no puede
> quedar comprobante**. Un comprobante con un número que ARCA no autorizó deja
> el correlativo tomado de este lado y libre del otro — y el próximo intento
> choca contra la unicidad de la base sin que nadie entienda por qué.
"""

import os
import stat
from decimal import Decimal
from pathlib import Path

import pytest
from libracore import arca_credenciales, config_manager
from libracore.db import arca_config as db_arca_config

from app.servicios import emision_arca

# Las fixtures `cliente` y `datos` salen del conftest; de acá sólo los
# helpers, que son funciones normales.
from tests.conftest import cargar_empresa, par_de_arca
from tests.test_comprobantes import facturado_a_mano, facturar, orden, pre_factura

CUIT = "20-12345678-6"


def _configurar_arca(cliente, *, cuit=CUIT, punto_venta=5,
                     ambiente="produccion", empresa=emision_arca.EMPRESA_ARCA):
    """Deja la instancia lista para emitir: el par en disco y el CUIT cargado.

    Es **una configuración por instancia**: así la guarda el motor. Sólo emite
    si su CUIT es el de la empresa (`cargar_empresa`).

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
def empresa_con_arca(cliente, datos):
    """La empresa, con el CUIT del certificado cargado (punto de venta 5)."""
    cargar_empresa(cliente)
    _configurar_arca(cliente)


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

def test_sin_arca_no_se_factura_y_lo_dice(cliente, datos):
    """🔑 Ya no hay otro camino: sin certificado de ARCA la pre factura espera, y no se registra a mano.

    La instancia del cliente **no tiene ningún certificado cargado** (ADR-032): hasta entonces genera y
    manda pre facturas, y el botón de facturar contesta qué falta sin tocar nada.
    """
    cargar_empresa(cliente)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 409, r.text
    assert "ARCA no está configurado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


# ── Emitir ──────────────────────────────────────────────────────────────────

def test_con_arca_el_numero_lo_da_arca(cliente, datos, empresa_con_arca, monkeypatch):
    """El número no se tipea: es el que sigue al último que autorizó ARCA, y el punto de venta el de la
    configuración de ARCA."""
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["numero"] == 42, "tenia que ser el ultimo autorizado + 1"
    assert comp["cae"] == "75123456789012"
    assert comp["cae_vencimiento"] == "2026-12-31"
    # El punto de venta sale de la configuración de ARCA, no del payload.
    assert comp["punto_venta"] == 5
    assert ("ultimo", 5, 1, "20-12345678-6") in pedidos


def test_la_cuenta_corriente_nombra_el_numero_real(cliente, datos, empresa_con_arca,
                                                   monkeypatch):
    """🔑 El concepto del movimiento se armaba con el número del payload. Con
    ARCA ese viene vacío, así que la cuenta corriente nombraría un comprobante
    inexistente."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a]).json()

    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    concepto = cuenta["movimientos"][0]["movimiento"]["concepto"]
    assert concepto == "Factura A 0005-00000042", concepto
    assert str(comp["numero"]) in concepto


# ── El rechazo, que es lo que importa ───────────────────────────────────────

def test_si_arca_rechaza_el_cae_no_queda_comprobante(cliente, datos, empresa_con_arca,
                                                     monkeypatch):
    """🔴 Ni comprobante, ni movimiento de cuenta, y las órdenes vuelven a
    pendientes.

    Un comprobante con un número que ARCA no autorizó deja el correlativo
    tomado de este lado y libre del otro: el próximo intento choca contra la
    unicidad de la base sin que nadie entienda por qué.
    """
    _arca_responde(monkeypatch, falla_cae="El comprobante ya fue autorizado")
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 502, r.text
    assert "ya fue autorizado" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    quedo = cliente.get(f"/api/ordenes/{a['id']}").json()
    assert quedo["estado"] == "pendiente", "la orden tenia que volver a pendiente"
    assert quedo["comprobante_id"] is None


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, empresa_con_arca,
                                                    monkeypatch):
    _arca_responde(monkeypatch, falla_numero="Computador no autorizado")
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 502
    assert "no autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"


# ── La guarda: sólo se emite con el CUIT de «Datos de la empresa» (ADR-035) ──
#
# 🔴 **Acá se perdió el `habilitado`.** La tabla propia tenía una bandera para
# "cargué el par y todavía no quiero emitir", y `arca_config` no la tiene. Lo
# que la reemplaza no es un flag equivalente: son los **dos pares**. Cargar el
# de homologación y dejar el selector ahí es el estado de "todavía no emito de
# verdad", y es mejor que la bandera porque además deja probar.

def test_si_el_cuit_de_arca_no_es_el_de_la_empresa_no_emite(cliente, datos, monkeypatch):
    """🔑 La guarda, y por qué es el CUIT: la empresa tiene uno y la configuración de ARCA, otro.

    La configuración de ARCA lleva el CUIT **que factura**, que es el de la empresa (aunque el certificado esté
    a nombre de otra persona que la representa). Si no coinciden, ARCA firmaría por un contribuyente que no es
    el emisor: la pre factura espera, y el mensaje dice los dos CUIT y cómo se corrige.

    Y el control importa tanto como el caso: la instancia SÍ tiene ARCA configurado. Sin eso, "no emitió"
    pasaría igual con la configuración vacía (ver `test_con_el_cuit_de_la_empresa_se_emite`).
    """
    cargar_empresa(cliente, cuit="30-99999999-7")
    _configurar_arca(cliente)   # el de CUIT = 20-12345678-6

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 409, r.text
    detalle = r.json()["detail"]
    assert "20-12345678-6" in detalle and "30-99999999-7" in detalle
    assert "CUIT que factura" in detalle
    assert "aunque el certificado esté a nombre de otra persona que la representa" in detalle
    assert pedidos == [], "no tenia que hablar con ARCA"
    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


def test_con_el_cuit_de_la_empresa_se_emite(cliente, datos, monkeypatch):
    """El control de la guarda: el mismo escenario con los dos CUIT iguales emite."""
    cargar_empresa(cliente, cuit="20-12345678-6")
    _configurar_arca(cliente, punto_venta=7)

    _arca_responde(monkeypatch, ultimo=10)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 11 and r.json()["punto_venta"] == 7


def test_el_cuit_matchea_con_guiones_y_sin_guiones(cliente, datos, monkeypatch):
    """El mismo CUIT escrito de las dos formas es el mismo CUIT.

    `configuracion_empresa.cuit` admite `20-12345678-6`; en la pantalla de ARCA se tipea como salga. Comparar
    los textos crudos haría que la empresa correcta **deje de poder emitir** con un 409 que dice que los dos
    CUIT difieren cuando son el mismo.
    """
    cargar_empresa(cliente, cuit="20-12345678-6")
    _configurar_arca(cliente, cuit="20123456786")

    _arca_responde(monkeypatch, ultimo=7)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 8


def test_una_empresa_sin_cuit_no_emite(cliente, datos, monkeypatch):
    """Sin CUIT en la empresa no hay con qué comparar, y adivinar sería facturar por otro."""
    cliente.put("/api/configuracion", json={"razon_social": "Sin CUIT SA"})
    _configurar_arca(cliente)

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 409, r.text
    assert "cargá el CUIT en Configuración → Datos de la empresa" in r.json()["detail"]
    assert pedidos == [], "no tenia que hablar con ARCA"
    assert cliente.get("/api/comprobantes").json() == []


def test_sin_los_datos_de_la_empresa_tampoco_emite(cliente, datos, monkeypatch):
    """La instancia recién entregada, sin «Datos de la empresa» cargados: el mismo mensaje."""
    _configurar_arca(cliente)

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 409, r.text
    assert "cargá el CUIT en Configuración → Datos de la empresa" in r.json()["detail"]
    assert pedidos == []


def test_el_cuit_de_arca_no_se_compara_con_el_titular_del_certificado(cliente, datos, monkeypatch):
    """🔑 Una persona física puede tener el certificado y facturar por la empresa (delegación).

    El certificado de `par_de_arca()` es de un sujeto cualquiera (`CN=test`), que no es el CUIT de la empresa
    ni el de `arca_config`; si la guarda mirara el sujeto del `.crt`, esto no emitiría. Emite porque la regla es
    **sólo** `arca_config.cuit == empresa.cuit`.
    """
    cargar_empresa(cliente)
    _configurar_arca(cliente)

    _arca_responde(monkeypatch, ultimo=3)
    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a]).status_code == 201


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
    cargar_empresa(cliente)
    _configurar_arca(cliente)
    db_arca_config.crear_arca_config(
        empresa="colada", cuit="30-99999999-7", punto_venta=9,
        clave_path="", certificado_path="", ambiente="homologacion",
    )

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
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
    cargar_empresa(cliente)
    _configurar_arca(cliente, empresa="un-slug-que-nadie-espera")

    _arca_responde(monkeypatch, ultimo=99)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 100


def test_sin_el_par_en_disco_no_emite_aunque_la_fila_exista(cliente, datos,
                                                            monkeypatch):
    """Una fila con el CUIT y sin archivos es una instancia a medio configurar.

    Pasa de verdad: el `PUT` de la pantalla crea la fila antes de que nadie suba
    nada. Salir a ARCA desde ahí da un error de autenticación que no habla de la
    causa; lo correcto es decir que falta el certificado.
    """
    cargar_empresa(cliente)
    r = cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT, "punto_venta": 5,
        "ambiente": "homologacion", "alias": "",
    })
    assert r.status_code == 200, r.text

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 409, r.text
    assert "falta el certificado o la clave de ARCA" in r.json()["detail"]
    assert pedidos == [], "no tenia que hablar con ARCA"


def test_el_selector_manda_cual_de_los_dos_pares_firma(cliente, datos, monkeypatch):
    """🔑 Lo que toda esta línea de trabajo vino a habilitar.

    Con los dos pares cargados, mover `ambiente` cambia **con cuál se firma** —y
    no obliga a pisar un archivo. Se mide el path que recibe `autenticar`, que
    es lo único que distingue un par del otro: el ambiente que se le pasa
    coincide en los dos casos por venir del mismo lugar, así que asertar sólo
    sobre él pasaría con el par equivocado.
    """
    cargar_empresa(cliente)
    _configurar_arca(cliente, ambiente="homologacion")
    certificado, clave = par_de_arca()
    for tramo, archivo in (("certificado", certificado), ("clave", clave)):
        assert cliente.post(f"/api/arca/{tramo}", params={"ambiente": "produccion"},
                            files={"archivo": ("c", archivo, "text/plain")},
                            ).status_code == 200

    pedidos = _arca_responde(monkeypatch, ultimo=1)
    a = orden(cliente, datos, "1000.00")
    facturar(cliente, datos, [a])
    con_homologacion = [p for p in pedidos if p[0] == "autenticar"][0]
    assert con_homologacion[1] == "homologacion"

    assert cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT, "punto_venta": 5,
        "ambiente": "produccion", "alias": "",
    }).status_code == 200

    pedidos = _arca_responde(monkeypatch, ultimo=1)
    b = orden(cliente, datos, "1000.00")
    facturar(cliente, datos, [b])
    con_produccion = [p for p in pedidos if p[0] == "autenticar"][0]
    assert con_produccion[1] == "produccion"
    assert con_produccion[2] != con_homologacion[2], (
        "los dos ambientes firmaron con el MISMO archivo de certificado")


# ── El ensayo contra homologacion ──────────────────────────────────────────


@pytest.fixture
def empresa_en_homologacion(cliente, datos):
    """La instancia configurada para PROBAR: el selector en homologación."""
    cargar_empresa(cliente)
    _configurar_arca(cliente, ambiente="homologacion")


def test_el_ensayo_recorre_el_camino_entero_contra_arca(cliente, datos,
                                                        empresa_en_homologacion,
                                                        monkeypatch):
    """🔑 El valor del ensayo es que NO es una simulación local.

    Pide el número correlativo, arma el pedido y trae el CAE, todo contra el
    WSFE de homologación. Si sólo devolviera un cartel, no probaría nada de lo
    que se rompe al cortar a producción.
    """
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])

    assert r.status_code == 200, r.text   # 200 y no 201: no se creó nada
    cuerpo = r.json()
    assert cuerpo["ensayo"] is True
    assert cuerpo["ambiente"] == "homologacion"
    assert cuerpo["numero"] == 42, "el número lo tenía que dar ARCA igual"
    assert cuerpo["cae"] == "75123456789012"
    assert "id" not in cuerpo, "un ensayo no tiene id porque no tiene fila"

    # Y hablo con ARCA de verdad: las tres llamadas del camino de emisión.
    assert [p[0] for p in pedidos] == ["autenticar", "ultimo", "cae"], pedidos
    assert pedidos[0][1] == "homologacion"


def test_el_ensayo_NO_deja_nada(cliente, datos, empresa_en_homologacion, monkeypatch):
    """🔴 Las tres mitades del daño que un comprobante de prueba haría acá.

    En otro producto alcanzaría con marcar la fila y filtrarla. Acá el
    comprobante **mueve la cuenta corriente** del cliente y **cierra las
    órdenes**, que después no se pueden volver a facturar. Se miran las tres:
    con una sola, aflojar el rollback pasaría en verde.
    """
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")

    assert facturar(cliente, datos, [a]).status_code == 200

    assert cliente.get("/api/comprobantes").json() == [], "quedó el comprobante"
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()[
        "movimientos"] == [], "movió la cuenta corriente del cliente"
    quedo = cliente.get(f"/api/ordenes/{a['id']}").json()
    assert quedo["estado"] == "pendiente", "cerró la orden"
    assert quedo["comprobante_id"] is None
    (pf,) = cliente.get("/api/pre-facturas").json()["items"]
    assert pf["estado"] == "pendiente" and pf["factura_id"] is None, "cerró la pre factura"


def test_el_ensayo_no_deja_asiento_de_auditoria(cliente, datos,
                                                empresa_en_homologacion, monkeypatch):
    """Un alta que se revirtió no es un alta.

    Registrarla sería un log que miente en la dirección más cara: dice que
    existe un comprobante que nadie va a encontrar.
    """
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")
    facturar(cliente, datos, [a])

    r = cliente.get("/api/auditoria", params={"entidad": "comprobante"})
    assert r.json()["registros"] == [], r.json()


def test_la_misma_pre_factura_se_puede_facturar_de_verdad_despues_del_ensayo(
        cliente, datos, empresa_en_homologacion, monkeypatch):
    """🔑 Lo que el ensayo tiene que dejar posible, y es el punto de todo esto.

    Probar con el cliente y **después** cortar a facturación real sobre la
    misma pre factura. Si el ensayo la cerrara (o cerrara sus órdenes), el
    corte empezaría con la operación a medio facturar.
    """
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")
    pf = pre_factura(cliente, datos, [a]).json()
    ensayo = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert ensayo.status_code == 200, ensayo.text
    abierta = cliente.get(f"/api/pre-facturas/{pf['id']}").json()
    assert abierta["estado"] == "pendiente" and abierta["factura_id"] is None, \
        "el ensayo no cierra la pre factura"

    # El corte: el selector pasa a producción.
    assert cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT, "punto_venta": 5,
        "ambiente": "produccion", "alias": "",
    }).status_code == 200
    certificado, clave = par_de_arca()
    for tramo, archivo in (("certificado", certificado), ("clave", clave)):
        assert cliente.post(f"/api/arca/{tramo}", params={"ambiente": "produccion"},
                            files={"archivo": ("c", archivo, "text/plain")},
                            ).status_code == 200

    _arca_responde(monkeypatch, ultimo=7)
    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 8, "la numeración real arranca donde dice ARCA"
    assert cliente.get(f"/api/pre-facturas/{pf['id']}").json()["estado"] == "facturado"


def test_con_el_selector_en_produccion_se_guarda_como_siempre(cliente, datos,
                                                              empresa_con_arca,
                                                              monkeypatch):
    """El control que hace que los de arriba signifiquen algo.

    Sin esto, "no queda nada" pasaría igual con un alta que no guarda nunca.
    """
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    assert r.json()["cae"] == "75123456789012"
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"]


# ── Los importes que se le mandan ───────────────────────────────────────────

def test_la_factura_c_va_sin_iva_discriminado(cliente, datos, empresa_con_arca,
                                              monkeypatch):
    """No es una simplificación: ARCA exige `ImpIVA = 0` e `ImpNeto = ImpTotal`
    para los tipos C, y rechaza el comprobante si se manda el IVA aparte."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00")
    facturar(cliente, datos, [a], tipo="factura_c")

    enviado = [p[1] for p in pedidos if p[0] == "cae"][0]
    assert enviado["tipo"] == 11
    assert enviado["iva_amount"] == 0.0
    assert enviado["subtotal"] == enviado["total"]


def test_la_factura_a_manda_el_iva_aparte(cliente, datos, empresa_con_arca, monkeypatch):
    """La otra mitad: sin esto, "el IVA va en cero" pasaría igual con un
    servicio que siempre manda cero."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a], tipo="factura_a").json()

    enviado = [p[1] for p in pedidos if p[0] == "cae"][0]
    assert enviado["tipo"] == 1
    assert enviado["iva_amount"] > 0
    assert enviado["iva_amount"] == float(Decimal(comp["iva"]))
    assert enviado["subtotal"] == float(Decimal(comp["neto"]))


# ── La condición de IVA del receptor (RG 5616) ──────────────────────────────

@pytest.mark.parametrize("condicion, codigo", [
    ("responsable_inscripto", 1),
    ("monotributo", 6),
    ("exento", 4),
    ("consumidor_final", 5),
    # «No sé»: el motor decide o falla con un mensaje; acá no se inventa.
    ("no_categorizado", 0),
])
def test_el_pedido_de_cae_lleva_la_condicion_de_iva_del_cliente(
        cliente, datos, empresa_con_arca, monkeypatch, condicion, codigo):
    """ARCA rechaza el comprobante sin la condición del receptor. LibraCargo se
    la pasa al motor con el código de la familia (`cliente_iva_cond`)."""
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True, "condicion_iva": condicion,
        "cuit": "30-12345678-1",
    })
    assert r.status_code == 200, r.text
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    (factura,) = [p[1] for p in pedidos if p[0] == "cae"]
    assert factura["cliente_iva_cond"] == codigo


def test_todas_las_condiciones_del_dominio_tienen_codigo():
    """Una condición nueva en el enum sin mapear tiene que romper acá."""
    from app.models.enums import CondicionIVA

    assert set(emision_arca.CODIGO_IVA_DE_LA_FAMILIA) == set(CondicionIVA)


def test_el_sobre_que_sale_hacia_arca_lleva_la_condicion_de_iva_del_receptor(
        cliente, datos, empresa_con_arca, monkeypatch):
    """**El test que no mockea `solicitar_cae`**: corre el del motor y mira el
    SOAP que sale. Los de arriba prueban que LibraCargo pasa el dato; éste prueba
    que **llega a ARCA**, que es lo que la RG 5616 exige.

    Falla con un `libracore` que ignore `cliente_iva_cond` (como el v1.118.0,
    donde el WSFE nunca lo leyó): ahí el pedido sale sin la condición y ARCA lo
    rechaza con el error 10246. Que este test esté en rojo es el aviso de que
    falta el bump.
    """
    import xml.etree.ElementTree as ET

    cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True,
        "condicion_iva": "responsable_inscripto", "cuit": "30-12345678-1",
    })
    enviados = []

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        return {"token": "TKN", "sign": "SGN"}

    async def soap(url, accion, cuerpo):
        enviados.append((accion, cuerpo))
        if accion == "FECompUltimoAutorizado":
            return ET.fromstring("<r><CbteNro>41</CbteNro></r>")
        return ET.fromstring(
            "<r><FECAEDetResponse><Resultado>A</Resultado><CAE>75123456789012</CAE>"
            "<CAEFchVto>20261231</CAEFchVto></FECAEDetResponse></r>")

    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "_soap", soap)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    (pedido,) = [c for acc, c in enviados if acc == "FECAESolicitar"]
    assert "<CondicionIVAReceptorId>1</CondicionIVAReceptorId>" in pedido


# ── Anular ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tipo", ["factura_a", "factura_b", "factura_c"])
def test_un_comprobante_con_cae_no_se_anula_desde_aca(cliente, datos, empresa_con_arca,
                                                      monkeypatch, tipo):
    """🔴 Anular acá no llega a ARCA: el comprobante seguiría vigente allá mientras las órdenes
    vuelven a pendientes y se pueden facturar otra vez —dos facturas por lo mismo—, y la cuenta
    corriente quedaría revertida contra algo que ARCA y el cliente siguen teniendo."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a], tipo=tipo).json()
    assert comp["cae"], "el punto de partida: un comprobante con CAE"

    r = cliente.delete(f"/api/comprobantes/{comp['id']}")

    assert r.status_code == 409, r.text
    assert "tiene CAE" in r.text and "nota de credito" in r.text
    assert cliente.get(f"/api/comprobantes/{comp['id']}").json()["comprobante"]["anulado"] is False
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "facturada", \
        "las órdenes no tienen que reabrirse"
    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    assert len(cuenta["movimientos"]) == 1, "no tiene que haber una reversión en la cuenta"


def test_lo_registrado_a_mano_sin_cae_se_sigue_anulando(cliente, datos, sesion):
    """El control de lo de arriba: `cae IS NULL` es lo registrado a mano antes de ADR-032 y lo migrado del
    legado, y eso se anula como siempre. Ya no se puede crear por la API: se arma el dato por abajo."""
    a = orden(cliente, datos, "1000.00")
    comp = facturado_a_mano(sesion, datos, [a], numero=7)
    assert comp.cae is None

    assert cliente.delete(f"/api/comprobantes/{comp.id}").status_code == 200
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


# ── La clave privada de ARCA, en disco ──────────────────────────────────────

def _modo(ruta) -> int:
    return stat.S_IMODE(os.stat(ruta).st_mode)


def _claves_subidas() -> list[Path]:
    return sorted(Path(config_manager.CERTS_DIR).glob("*.key"))


def test_la_clave_privada_que_sube_la_pantalla_queda_cerrada(cliente, datos):
    """🔴 Con `libracore` v1.119.0 la clave quedaba en 644: legible por cualquiera dentro del
    contenedor. Desde v1.121.0 se escribe en 0600, sin pasar por un instante abierta."""
    _configurar_arca(cliente)

    (clave,) = _claves_subidas()
    assert _modo(clave) & 0o077 == 0, f"la clave quedó en {oct(_modo(clave))}"


def test_una_clave_ya_guardada_abierta_se_cierra_al_resolver_las_credenciales(cliente, datos):
    """Las instancias vivas tienen la clave en 644: se corrigen solas al actualizar el motor,
    porque toda emisión pasa por `paths_en_disco`."""
    _configurar_arca(cliente)
    (clave,) = _claves_subidas()
    os.chmod(clave, 0o644)        # como la dejaba el motor anterior

    arca_credenciales.paths_en_disco(emision_arca.configuracion_de_la_instancia())

    assert _modo(clave) & 0o077 == 0, f"la clave siguió en {oct(_modo(clave))}"


# ── El CUIT del cliente, dicho antes de ir a ARCA ───────────────────────────
#
# 🔑 **La regla no vive acá: es `arca_wsfe.problema_del_receptor` de libracore** (el arreglo de fondo
# vive siempre en el motor), con sus propios tests en el motor. Lo que se prueba en este archivo es
# la **integración del producto**: que `facturar` conteste con un 422 que nombra al cliente **antes
# de pedirle nada a ARCA**, y que lo haga delegando en el motor y no con una copia propia.
#
# Contexto, medido contra ARCA de homologación el 2026-10-03: los clientes migrados de Suitrans traen
# un `1` de relleno como CUIT (12 de 75) y dos con el dígito verificador mal. Una Factura A con CUIT
# `1` vuelve `[10013]` y `[10015]` (un 502 que no explica nada); con el verificador mal, una **B** se
# rechaza (`10015`) y una **A ARCA la autoriza con CAE** y sólo avisa (`10238`).

def _cliente_con_cuit(cliente, datos, cuit, condicion="responsable_inscripto"):
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True,
        "condicion_iva": condicion, "cuit": cuit,
    })
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("cuit, dice", [
    ("1", "'1'"),              # el relleno del sistema viejo
    ("", "no tiene CUIT"),     # sin CUIT
    ("30-7093", "'30-7093'"),  # a medio cargar
])
def test_una_factura_a_sin_cuit_valido_se_rechaza_antes_de_ir_a_arca(
        cliente, datos, empresa_con_arca, monkeypatch, cuit, dice):
    pedidos = _arca_responde(monkeypatch)
    _cliente_con_cuit(cliente, datos, cuit)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a], tipo="factura_a")

    assert r.status_code == 422, r.text
    assert "Agro Norte" in r.text and dice in r.text and "ficha del cliente" in r.text, r.text
    assert pedidos == [], "no se le pidio nada a ARCA: ni ticket ni numero"
    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


@pytest.mark.parametrize("tipo", ["factura_a", "factura_b", "factura_c"])
def test_un_cuit_de_11_digitos_con_verificador_mal_se_rechaza_en_toda_clase(
        cliente, datos, empresa_con_arca, monkeypatch, tipo):
    """Con 11 dígitos el verificador tiene que cerrar **en toda clase**: una B se rechaza en ARCA y una A se
    autoriza con una observación («la CUIT no existe»), y esa factura habría que anularla después."""
    pedidos = _arca_responde(monkeypatch)
    _cliente_con_cuit(cliente, datos, "20-12345678-0")   # CUIT ficticio con el dígito verificador mal
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a], tipo=tipo)

    assert r.status_code == 422, r.text
    assert "dígito verificador" in r.text and "20-12345678-0" in r.text, r.text
    assert pedidos == []


def test_una_fce_con_el_verificador_mal_tambien_se_rechaza_antes_de_ir_a_arca(
        cliente, datos, empresa_con_arca, monkeypatch):
    from tests.test_fce import _facturar

    pedidos = _arca_responde(monkeypatch)
    _cliente_con_cuit(cliente, datos, "20-12345678-0")
    a = orden(cliente, datos, "1000.00")

    r = _facturar(cliente, datos, [a])

    assert r.status_code == 422, r.text
    assert "dígito verificador" in r.text, r.text
    assert pedidos == []


@pytest.mark.parametrize("tipo", ["factura_b", "factura_c"])
def test_una_clase_b_o_c_sigue_saliendo_a_un_cliente_sin_cuit(
        cliente, datos, empresa_con_arca, monkeypatch, tipo):
    """Un consumidor final no tiene CUIT: el `1` o la ausencia no se tocan en B y C."""
    pedidos = _arca_responde(monkeypatch)
    _cliente_con_cuit(cliente, datos, "1", condicion="consumidor_final")
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a], tipo=tipo)

    assert r.status_code == 201, r.text
    assert any(p[0] == "cae" for p in pedidos)


def test_la_ficha_del_cliente_sigue_aceptando_cualquier_cuit(cliente, datos):
    """La validación es de la emisión, no del alta: el `1` migrado se puede seguir editando."""
    _cliente_con_cuit(cliente, datos, "1")
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte SA", "es_cliente": True,
        "condicion_iva": "responsable_inscripto", "cuit": "1",
    })
    assert r.status_code == 200, r.text


def test_la_guarda_es_la_del_motor_y_no_una_copia_propia(cliente, datos, empresa_con_arca, monkeypatch):
    """🔑 Si el motor dice que el receptor no sirve, `facturar` lo repite tal cual: no decide nada.

    El motor responde algo que ninguna regla local diría, y el 422 lo lleva. Y el producto no tiene su
    propio validador de CUIT: si reaparece, esta regla (`reglas/producto.md`) volvió a romperse.
    """
    pedidos = _arca_responde(monkeypatch)
    monkeypatch.setattr(emision_arca.arca_wsfe, "problema_del_receptor",
                        lambda factura: "el motor dice que este receptor no sirve")
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a], tipo="factura_b")

    assert r.status_code == 422, r.text
    assert "el motor dice que este receptor no sirve" in r.text, r.text
    assert pedidos == []
    assert not hasattr(emision_arca, "cuit_con_verificador_valido"), "una copia propia del validador"


def test_el_pedido_de_cae_lleva_el_cuit_tal_cual_y_el_nombre_del_cliente(
        cliente, datos, empresa_con_arca, monkeypatch):
    """El producto no normaliza el CUIT (lo hace el motor) y le pasa el nombre para que el mensaje lo diga."""
    pedidos = _arca_responde(monkeypatch)
    _cliente_con_cuit(cliente, datos, "30.12345678.1")
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a], tipo="factura_a")

    assert r.status_code == 201, r.text
    (factura,) = [p[1] for p in pedidos if p[0] == "cae"]
    assert factura["cliente_cuit"] == "30.12345678.1"
    assert factura["cliente_razon"] == "Agro Norte"
