"""«Facturar pendientes» directo por ARCA, sin pre factura (ADR-048).

> 🔑 **Los datos son ficticios**: «Agro Norte», «Molino Sur», el CUIT 20-12345678-6. Ni un nombre ni un
> CUIT de un cliente real entran en una suite.

Hasta ADR-048 estas órdenes pasaban por una pre factura (ADR-032). Ahora `POST /api/comprobantes/desde-ordenes`
las emite en el momento. Lo que se mide, en el orden del flujo:

1. Que sale con CAE y **cierra todo junto**: el comprobante, las órdenes y la cuenta corriente.
2. Que **no queda nada** si no sale: sin certificado, ARCA que rechaza, ARCA que no da el número, dos configuraciones.
3. Que las órdenes se validan (del cliente, pendientes, sin repetir) y que **no se facturan dos veces**, ni siquiera con
   dos pedidos a la vez: lo que antes frenaba la reserva de la pre factura ahora lo frena la base.
4. La FCE: vencimiento, CBU y modalidad, y en qué cuenta se cobra.
5. Que la pre factura ya no existe: ni sus rutas, ni su tabla, ni su reserva.
"""

import threading
from decimal import Decimal

import pytest
from libracore.db import core as libracore_core
from sqlalchemy import text

from tests.conftest import CUIT_EMISOR, URL_CORE, arca_responde
from tests.test_comprobantes import facturar, orden

pytestmark = pytest.mark.con_emisor


def _estado_de_la_orden(cliente, o):
    return cliente.get(f"/api/ordenes/{o['id']}").json()["estado"]


def _factura_del_motor(factura_id):
    from libracore.db import facturas as db_facturas

    with libracore_core.get_connection() as conn:
        return db_facturas.get_factura(factura_id, conn=conn)


# ── 1. Sale con CAE y cierra todo junto ─────────────────────────────────────


def test_facturar_emite_por_arca_y_cierra_todo_junto(cliente, datos, emisor):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "2500.55")

    r = facturar(cliente, datos, [a, b])
    assert r.status_code == 201, r.text
    comp = r.json()
    # El número lo puso ARCA y el punto de venta es el de su configuración: no se tipean.
    assert comp["numero"] == 1 and comp["punto_venta"] == 1
    assert comp["cae"] == "75123456789012"
    assert comp["fecha"] == "2026-08-15"
    assert comp["sin_ordenes"] is False, "agrupa órdenes: el gate la compara contra ellas"
    assert Decimal(comp["total"]) == Decimal(a["total"]) + Decimal(b["total"])
    assert ("ultimo", 1, 1, CUIT_EMISOR) in emisor

    # Las órdenes pasaron a facturadas, con su comprobante.
    for o in (a, b):
        actual = cliente.get(f"/api/ordenes/{o['id']}").json()
        assert actual["estado"] == "facturada"
        assert actual["comprobante_id"] == comp["id"]
    # La deuda del cliente entró en la cuenta corriente con el número real.
    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    assert len(cuenta["movimientos"]) == 1
    mov = cuenta["movimientos"][0]["movimiento"]
    assert mov["concepto"] == "Factura A 0001-00000001"
    assert Decimal(mov["debe"]) == Decimal(comp["total"])
    assert mov["descripcion"] == f"Ordenes {a['id']}, {b['id']}"
    # Y el detalle del comprobante no marca alarma: lo que dice es lo que suman sus órdenes.
    assert cliente.get(f"/api/comprobantes/{comp['id']}").json()["coinciden"] is True
    assert cliente.get("/api/comprobantes/totales").json()["coinciden"] is True
    # Ya no hay órdenes pendientes que mostrar en «Facturar pendientes».
    assert cliente.get("/api/ordenes?facturada=false&estado=pendiente").json() == []


def test_los_items_del_comprobante_salen_de_las_ordenes(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "10.03")
    comp = facturar(cliente, datos, [a, b]).json()

    factura = _factura_del_motor(comp["id"])
    assert [(i["description"], i["qty"], i["unit_price"]) for i in factura["items"]] == [
        ("Flete", 1, 1000.0), ("Flete", 1, 10.03)]
    assert f"Orden {a['id']}" in factura["items"][0]["detalle"]
    assert Decimal(comp["total"]) == Decimal(str(factura["total"]))


def test_el_cuerpo_no_acepta_items_ni_importes_ni_punto_de_venta_ni_numero(cliente, datos):
    """Los importes salen de las órdenes: aceptarlos del cliente permitiría un comprobante que diga otro total."""
    a = orden(cliente, datos, "1000.00")
    base = {"fecha": "2026-08-15", "cliente_id": datos["cliente"], "tipo": "factura_a", "orden_ids": [a["id"]]}
    for extra in ({"punto_venta": 1}, {"numero": 7}, {"razon_social_id": 1}, {"total": "1.00"}, {"neto": "1.00"},
                  {"items": [{"description": "x", "qty": 1, "unit_price": 1}]}):
        r = cliente.post("/api/comprobantes/desde-ordenes", json=base | extra)
        assert r.status_code == 422, extra
    assert cliente.get("/api/comprobantes").json() == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"


def test_un_booleano_no_es_un_cliente_ni_un_numero(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    r = cliente.post("/api/comprobantes/desde-ordenes", json={
        "fecha": "2026-08-15", "cliente_id": True, "tipo": "factura_a", "orden_ids": [a["id"]]})
    assert r.status_code == 422


def test_una_factura_c_va_sin_iva_y_con_el_total_de_las_ordenes(cliente, datos, emisor):
    """Un comprobante clase C no discrimina IVA: todo el importe va como neto a ARCA y no se manda alícuota."""
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a], tipo="factura_c")
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["total"]) == Decimal(a["total"])
    pedido = next(p[1] for p in emisor if p[0] == "cae")
    assert pedido["tipo"] == 11
    assert (pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (1210.0, 0.0, 1210.0)


def test_el_iva_del_comprobante_suma_lo_mismo_que_el_de_cada_orden(cliente, datos):
    """Cada orden redondea su IVA: `10.03 × 21%` es `2.1063`, que va a `2.11`. Dos veces eso es **4.22**."""
    a = orden(cliente, datos, "10.03")
    b = orden(cliente, datos, "10.03")
    comp = facturar(cliente, datos, [a, b]).json()
    assert Decimal(comp["iva"]) == Decimal("4.22")
    assert Decimal(comp["total"]) == Decimal("24.28")


def test_facturar_con_otra_fecha_usa_esa_fecha(cliente, datos):
    a = orden(cliente, datos, "100.00")
    r = facturar(cliente, datos, [a], fecha="2026-08-30")
    assert r.status_code == 201, r.text
    assert r.json()["fecha"] == "2026-08-30"


def test_las_observaciones_quedan_en_el_comprobante(cliente, datos):
    a = orden(cliente, datos, "100.00")
    comp = facturar(cliente, datos, [a], observaciones="Entrega 14 de agosto").json()
    assert _factura_del_motor(comp["id"])["observaciones"] == "Entrega 14 de agosto"


def test_el_alta_deja_un_asiento_de_auditoria(cliente, datos):
    a = orden(cliente, datos, "100.00")
    comp = facturar(cliente, datos, [a]).json()
    registros = cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"]
    assert [(r["entidad_id"], r["accion"]) for r in registros] == [(comp["id"], "alta")]


# ── 2. Si no sale, no queda nada ────────────────────────────────────────────


def test_sin_certificado_no_se_factura_y_no_se_toca_nada(cliente, datos):
    """🔴 La instancia no tiene el par de ARCA cargado: el error lo dice y nada cambia."""
    from libracore.db import arca_config as db_arca_config

    for fila in db_arca_config.obtener_todas_arca_configs():
        db_arca_config.eliminar_arca_config(fila["empresa"])
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 409
    assert "ARCA no está configurado" in r.json()["detail"]
    assert "No se emitió nada" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert len(cliente.get("/api/ordenes?facturada=false&estado=pendiente").json()) == 1


def test_si_arca_rechaza_no_queda_nada_y_se_puede_reintentar(cliente, datos, monkeypatch):
    """El control de la transacción: un rechazo no deja comprobante, ni asiento, ni la orden facturada."""
    arca_responde(monkeypatch, falla_cae="El comprobante ya fue autorizado")
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 502, r.text
    assert "ya fue autorizado" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"] == []

    # Cuando ARCA vuelve, las mismas órdenes se facturan: no quedaron apartadas.
    arca_responde(monkeypatch)
    assert facturar(cliente, datos, [a]).status_code == 201


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, monkeypatch):
    arca_responde(monkeypatch, falla_numero="Computador no autorizado")
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 502
    assert "no autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"


def test_con_dos_configuraciones_de_arca_no_elige_una_para_facturar(cliente, datos):
    """El motor hace `arca_cfg[0]`; este producto se niega: facturar por otro contribuyente sin fallar es peor."""
    from libracore.db import arca_config as db_arca_config

    a = orden(cliente, datos, "1000.00")
    libracore_core.configure(URL_CORE)
    db_arca_config.crear_arca_config(
        empresa="colada", cuit="30-99999999-7", punto_venta=9,
        clave_path="", certificado_path="", ambiente="homologacion")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 409
    assert "colada" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []


def test_si_el_numero_que_da_arca_ya_esta_registrado_no_se_factura(cliente, datos, sesion):
    """Lo registrado a mano antes tiene el 0001-00000001: ARCA daría el mismo y chocaría, y se dice antes."""
    from tests.test_comprobantes import facturado_a_mano

    previa = orden(cliente, datos, "100.00")
    facturado_a_mano(sesion, datos, [previa], numero=1)
    a = orden(cliente, datos, "1000.00")

    r = facturar(cliente, datos, [a])
    assert r.status_code == 409
    assert "ya está registrado" in r.text
    assert _estado_de_la_orden(cliente, a) == "pendiente"


# ── 3. Las órdenes ──────────────────────────────────────────────────────────


def test_una_orden_ya_facturada_no_entra(cliente, datos):
    a = orden(cliente, datos, "100.00")
    assert facturar(cliente, datos, [a]).status_code == 201

    r = facturar(cliente, datos, [a])
    assert r.status_code == 409
    assert "facturada" in r.text
    assert len(cliente.get("/api/comprobantes").json()) == 1


def test_una_orden_de_otro_cliente_no_entra(cliente, datos):
    a = orden(cliente, datos, "100.00")
    ajena = orden(cliente, datos, "200.00", cliente_id=datos["otro_cliente"])
    r = facturar(cliente, datos, [a, ajena])
    assert r.status_code == 422
    assert str(ajena["id"]) in r.text
    assert cliente.get("/api/comprobantes").json() == []


def test_las_ordenes_repetidas_no_duplican_el_importe(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    r = cliente.post("/api/comprobantes/desde-ordenes", json={
        "fecha": "2026-08-15", "cliente_id": datos["cliente"],
        "tipo": "factura_a", "orden_ids": [a["id"], a["id"]]})
    assert r.status_code == 422
    assert "repetida" in r.text


def test_una_orden_que_no_existe_da_404(cliente, datos):
    r = facturar(cliente, datos, [9999])
    assert r.status_code == 404 and "9999" in r.text


def test_un_cliente_que_no_existe_da_404(cliente, datos):
    a = orden(cliente, datos, "100.00")
    assert facturar(cliente, datos, [a], cliente_id=9999).status_code == 404


def test_una_nota_no_se_factura_sobre_ordenes(cliente, datos):
    a = orden(cliente, datos, "100.00")
    for tipo in ("nota_credito_a", "nota_debito_a"):
        r = facturar(cliente, datos, [a], tipo=tipo)
        assert r.status_code == 422, tipo
        assert "una nota no se factura desde aca" in r.text


def test_ordenes_que_suman_cero_no_tienen_nada_que_facturar(cliente, datos):
    a = orden(cliente, datos, "0.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 422
    assert "suman cero" in r.text


def test_las_ordenes_que_no_se_facturaron_siguen_pendientes_y_libres_para_editar(cliente, datos):
    """Sin la reserva de la pre factura, una orden pendiente se edita y se anula como siempre."""
    a = orden(cliente, datos, "1000.00")
    cuerpo = {"fecha": "2026-08-10", "cliente_id": datos["cliente"],
              "origen_id": datos["origen"], "destino_id": datos["destino"], "tarifa": "1500.00"}
    assert cliente.put(f"/api/ordenes/{a['id']}", json=cuerpo).status_code == 200
    assert cliente.delete(f"/api/ordenes/{a['id']}").status_code == 200


def test_dos_pedidos_a_la_vez_por_las_mismas_ordenes_facturan_una_sola_vez(cliente, datos, monkeypatch):
    """🔴 Lo que antes frenaba la reserva de la pre factura: el segundo espera (`FOR UPDATE`) y las halla facturadas.

    Sin eso, un doble clic emitía dos comprobantes por las mismas órdenes. Se simulan dos pedidos que llegan juntos,
    con el primero dormido adentro de ARCA.
    """
    import asyncio
    import time

    a = orden(cliente, datos, "1000.00")
    pedidos = arca_responde(monkeypatch)
    from app.servicios import emision_arca

    real = emision_arca.arca_wsfe.solicitar_cae
    adentro = threading.Event()

    async def cae_lento(*args, **kwargs):
        adentro.set()
        await asyncio.sleep(0.5)
        return await real(*args, **kwargs)

    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", cae_lento)
    respuestas = []

    def pedir():
        respuestas.append(facturar(cliente, datos, [a]).status_code)

    primero = threading.Thread(target=pedir)
    primero.start()
    assert adentro.wait(10)
    time.sleep(0.1)
    segundo = threading.Thread(target=pedir)
    segundo.start()
    primero.join()
    segundo.join()

    assert sorted(respuestas) == [201, 409], respuestas
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert len([p for p in pedidos if p[0] == "cae"]) == 1, "ARCA autorizó una sola vez"


# ── 4. FCE ──────────────────────────────────────────────────────────────────


def test_una_fce_pide_el_vencimiento_y_el_cuit_del_cliente(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    sin_vencimiento = facturar(cliente, datos, [a], tipo="fce_a")
    assert sin_vencimiento.status_code == 422
    assert "vencimiento" in sin_vencimiento.text

    vencida = facturar(cliente, datos, [a], tipo="fce_a", fecha="2026-01-10", vencimiento="2026-01-20")
    assert vencida.status_code == 422
    assert "anterior a hoy" in vencida.text

    sin_fce = facturar(cliente, datos, [a], vencimiento="2099-01-01")
    assert sin_fce.status_code == 422
    assert "solo la factura de credito electronica" in sin_fce.text

    ajena = orden(cliente, datos, "100.00", cliente_id=datos["otro_cliente"])
    sin_cuit = facturar(cliente, datos, [ajena], tipo="fce_a", cliente_id=datos["otro_cliente"],
                        fecha="2099-01-01", vencimiento="2099-02-01")
    assert sin_cuit.status_code == 422
    assert "CUIT de 11" in sin_cuit.text
    assert cliente.get("/api/comprobantes").json() == []


def test_facturar_una_fce_sale_con_vencimiento_cbu_y_modalidad(cliente, datos, emisor):
    cliente.put("/api/arca", json={
        "empresa": "agencia", "cuit": CUIT_EMISOR, "punto_venta": 1, "ambiente": "produccion",
        "alias": "", "fce_cbu": "0000003100012345678901", "fce_transmision": "sca"})
    a = orden(cliente, datos, "5000.00")

    r = facturar(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01")
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["tipo"] == "fce_a"
    assert comp["fch_vto_pago"] == "2099-02-01"
    assert comp["fce_cbu"] == "0000003100012345678901"
    assert comp["fce_transmision"] == "SCA"
    pedido = next(p[1] for p in emisor if p[0] == "cae")
    assert pedido["fch_vto_pago"] == "2099-02-01"


CBU_NACION = "0110599520000001234567"
CBU_GALICIA = "0070999030004001234567"


def _dos_cuentas(cliente):
    """La empresa cobra en dos cuentas; la de Galicia es la predeterminada."""
    r = cliente.put("/api/arca", json={
        "empresa": "agencia", "cuit": CUIT_EMISOR, "punto_venta": 1, "ambiente": "produccion", "alias": "",
        "fce_cbus": [{"cbu": CBU_NACION, "alias": "agencia.nacion", "etiqueta": "Nación"},
                     {"cbu": CBU_GALICIA, "alias": "agencia.galicia", "etiqueta": "Galicia"}],
        "fce_cbu": CBU_GALICIA, "fce_transmision": "SCA"})
    assert r.status_code == 200, r.text


def test_las_cuentas_para_cobrar_una_fce_y_la_predeterminada(cliente):
    _dos_cuentas(cliente)
    r = cliente.get("/api/comprobantes/fce/cuentas").json()
    assert [c["alias"] for c in r["cuentas"]] == ["agencia.nacion", "agencia.galicia"]
    assert r["predeterminada"] == CBU_GALICIA
    assert r["transmision"] == "SCA"


def test_una_fce_elegida_por_alias_se_factura_en_esa_cuenta_y_no_en_la_predeterminada(cliente, datos, emisor):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "5000.00")
    r = facturar(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01",
                 cuenta="agencia.nacion")
    assert r.status_code == 201, r.text
    assert r.json()["fce_cbu"] == CBU_NACION, "se guarda el CBU aunque se elija por alias"
    pedido = next(p[1] for p in emisor if p[0] == "cae")
    assert pedido["fce_cbu"] == CBU_NACION, "a ARCA va el CBU elegido, no el de la configuración"


def test_una_fce_sin_elegir_cuenta_sale_con_la_predeterminada(cliente, datos, emisor):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "5000.00")
    r = facturar(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01")
    assert r.status_code == 201, r.text
    assert r.json()["fce_cbu"] == CBU_GALICIA


def test_una_cuenta_que_no_esta_cargada_no_se_acepta_y_no_queda_nada(cliente, datos):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "5000.00")
    r = facturar(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01",
                 cuenta="2850590940090418135201")
    assert r.status_code == 422
    assert "no está entre los cargados" in r.text
    assert cliente.get("/api/comprobantes").json() == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"


def test_una_factura_comun_no_lleva_cuenta_aunque_se_mande(cliente, datos):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a], cuenta="agencia.nacion")
    assert r.status_code == 201, r.text
    assert r.json()["fce_cbu"] is None


# ── 5. La pre factura ya no existe ──────────────────────────────────────────


def test_las_rutas_de_la_pre_factura_ya_no_existen(cliente, datos):
    """🔴 ADR-048: ni listar, ni crear, ni facturar, ni su PDF, ni sus acciones."""
    a = orden(cliente, datos, "1000.00")
    for metodo, ruta in (("get", "/api/pre-facturas"), ("post", "/api/pre-facturas"),
                         ("get", "/api/pre-facturas/1"), ("put", "/api/pre-facturas/1"),
                         ("post", "/api/pre-facturas/1/facturar"), ("get", "/api/pre-facturas/1/pdf"),
                         ("post", "/api/pre-facturas/1/enviar-email"), ("post", "/api/pre-facturas/1/aceptar"),
                         ("post", "/api/pre-facturas/1/anular")):
        r = getattr(cliente, metodo)(ruta)
        assert r.status_code in (404, 405), (metodo, ruta, r.status_code)
    rutas = cliente.app.openapi()["paths"]
    assert not [r for r in rutas if "pre-factura" in r], [r for r in rutas if "pre-factura" in r]
    assert _estado_de_la_orden(cliente, a) == "pendiente"


def test_las_ordenes_ya_no_se_filtran_por_reserva(cliente):
    """`reservada` y `pre_factura_id` eran de la pre factura: el esquema de la API ya no los ofrece."""
    parametros = {p["name"] for p in cliente.app.openapi()["paths"]["/api/ordenes"]["get"]["parameters"]}
    assert {"reservada", "pre_factura_id"}.isdisjoint(parametros)
    assert "facturada" in parametros


def test_las_tablas_de_la_pre_factura_ya_no_existen(engine):
    from sqlalchemy import inspect

    tablas = set(inspect(engine).get_table_names())
    assert {"pre_facturas_cargo", "pre_factura_ordenes"}.isdisjoint(tablas)
    # La bandeja es del motor y la usan otros productos: no se dropea.
    assert "comprobantes_pendientes" in tablas


def test_ya_no_se_puede_registrar_un_comprobante_a_mano(cliente, datos):
    """Se sacó del todo: ni sin certificado ni con él. `POST /api/comprobantes` no existe."""
    a = orden(cliente, datos, "1000.00")
    cuerpo = {"fecha": "2026-08-15", "cliente_id": datos["cliente"],
              "tipo": "factura_a", "punto_venta": 1, "numero": 7, "orden_ids": [a["id"]]}
    assert cliente.post("/api/comprobantes", json=cuerpo).status_code == 405
    assert cliente.get("/api/comprobantes").json() == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"


def test_la_api_no_nombra_el_punto_de_venta_ni_el_numero_en_ninguna_entrada(cliente):
    """Ni al facturar órdenes, ni la factura directa, ni la nota de débito: el esquema de la API no los ofrece."""
    esquemas = cliente.app.openapi()["components"]["schemas"]
    for nombre in ("FacturarOrdenesIn", "FacturaDirectaIn", "ConceptoIn", "NotaDeDebitoIn", "NotaDeCreditoIn"):
        assert {"punto_venta", "numero"}.isdisjoint(esquemas[nombre]["properties"]), nombre
    for viejo in ("PreFacturaIn", "PreFacturaEditarIn", "FacturarPreFacturaIn", "FacturarIn"):
        assert viejo not in esquemas, viejo


def test_la_anulacion_de_un_comprobante_sin_cae_migrado_sigue_existiendo(cliente, datos, sesion):
    """Lo que ya estaba registrado a mano (o migrado del legado) se sigue anulando como siempre."""
    from datetime import date

    from app.models.enums import TipoComprobante
    from tests.conftest import comprobante_de_prueba

    comp = comprobante_de_prueba(
        sesion, tipo=TipoComprobante("factura_a"), punto_venta=3, numero=77,
        fecha=date(2026, 5, 10), cliente_id=datos["cliente"], neto=100, iva=21, total=121)
    r = cliente.delete(f"/api/comprobantes/{comp.id}")
    assert r.status_code == 200, r.text
    assert r.json()["anulado"] is True


def test_anular_el_comprobante_deja_las_ordenes_libres_para_facturar_de_nuevo(cliente, datos, sesion):
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a]).json()
    # Un comprobante con CAE no se anula desde acá (hace falta una nota de crédito): se simula uno sin CAE.
    sesion.execute(text("UPDATE facturas SET cae = '' WHERE id = :i"), {"i": comp["id"]})
    sesion.commit()

    assert cliente.delete(f"/api/comprobantes/{comp['id']}").status_code == 200
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert facturar(cliente, datos, [a]).status_code == 201
