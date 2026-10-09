"""La pre factura (ADR-032): se genera desde órdenes, se manda al cliente, y se factura por ARCA.

> 🔑 **Los datos son ficticios**: «Agro Norte», «Molino Sur», el CUIT 20-12345678-6. Ni un nombre ni un
> CUIT de un cliente real entran en una suite.

Lo que se mide acá, en el orden del flujo:

1. Generar: los ítems salen de las órdenes y son **los mismos que los de la factura**; las órdenes quedan
   reservadas, y una reservada no entra en otra pre factura.
2. Editar y anular: editar reemplaza las órdenes y anular las libera.
3. Facturar por ARCA, en una sola transacción: lo que queda si sale, y **que no quede nada** si no sale.
4. Que ya no se pueda registrar un comprobante a mano.
"""

from decimal import Decimal

import pytest
from libracore import email_sender
from libracore import pre_facturas as dominio_pre_facturas
from libracore.db import core as libracore_core
from sqlalchemy import text

from app.servicios.emisor_del_pdf import emisor_de
from tests.conftest import CUIT_EMISOR, URL_CORE, arca_responde, cargar_empresa
from tests.test_comprobantes import orden, pre_factura

pytestmark = pytest.mark.con_emisor


def _crear(cliente, datos, ordenes, **kw):
    r = pre_factura(cliente, datos, ordenes, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def _estado_de_la_orden(cliente, o):
    return cliente.get(f"/api/ordenes/{o['id']}").json()["estado"]


def _reservadas(cliente, pf_id=None):
    filtro = f"pre_factura_id={pf_id}" if pf_id else "reservada=true"
    return sorted(o["id"] for o in cliente.get(f"/api/ordenes?{filtro}").json())


# ── 1. Generar ──────────────────────────────────────────────────────────────


def test_generar_crea_la_pre_factura_con_numero_interno_y_reserva_las_ordenes(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "2500.55")

    pf = _crear(cliente, datos, [a, b])

    assert pf["numero_interno"] == "PF-0001"
    assert pf["estado"] == "pendiente"
    assert pf["cliente_razon"] == "Agro Norte"
    assert pf["cliente_cuit"] == "30-12345678-1"
    assert "razon_social_id" not in pf and "razon_social" not in pf, "el emisor es la empresa (ADR-035)"
    assert pf["orden_ids"] == [a["id"], b["id"]]
    assert pf["tipo_comprobante"] == 1
    assert pf["fecha_sugerida"] == "2026-08-15"
    # El total es la suma de lo que dicen las órdenes, como texto con dos decimales.
    assert Decimal(pf["total"]) == Decimal(a["total"]) + Decimal(b["total"])
    # Las órdenes siguen pendientes (la factura todavía no existe) pero reservadas.
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert _reservadas(cliente) == [a["id"], b["id"]]
    assert _reservadas(cliente, pf["id"]) == [a["id"], b["id"]]
    # Y ya no se ofrecen como libres.
    assert cliente.get("/api/ordenes?reservada=false").json() == []


def test_los_items_de_la_pre_factura_son_los_de_la_factura(cliente, datos):
    """Lo que el cliente ve antes tiene que ser lo que se le factura: el mismo detalle, precio y total."""
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "10.03")
    pf = _crear(cliente, datos, [a, b])
    comp = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").json()

    factura = _facturas_del_motor(comp["id"])
    assert [(i["description"], i["detalle"], i["qty"], i["unit_price"]) for i in pf["items"]] == [
        (i["description"], i["detalle"], i["qty"], i["unit_price"]) for i in factura["items"]]
    assert Decimal(pf["total"]) == Decimal(comp["total"]) == Decimal(str(factura["total"]))
    # La pre factura no manda ítems ni importes a nadie: salen de las órdenes.
    assert all(i["orden_id"] in (a["id"], b["id"]) for i in pf["items"])


def _facturas_del_motor(factura_id):
    from libracore.db import facturas as db_facturas

    with libracore_core.get_connection() as conn:
        return db_facturas.get_factura(factura_id, conn=conn)


def test_el_iva_de_la_pre_factura_suma_lo_mismo_que_el_de_la_factura(cliente, datos):
    """Cada orden redondea su IVA: `10.03 × 21%` es `2.1063`, que va a `2.11`. Dos veces eso es **4.22**.

    Con la alícuota nominal el total de la pre factura sería `24.2826 → 24.28` por casualidad, y con otros
    importes un centavo distinto del de la factura. Sale de lo que dicen las órdenes.
    """
    a = orden(cliente, datos, "10.03")
    b = orden(cliente, datos, "10.03")
    pf = _crear(cliente, datos, [a, b])
    assert Decimal(pf["total"]) == Decimal("24.28")

    c = orden(cliente, datos, "7.77")
    d = orden(cliente, datos, "13.31")
    e = orden(cliente, datos, "99.99")
    mezcladas = _crear(cliente, datos, [c, d, e])
    esperado = sum(Decimal(o["total"]) for o in (c, d, e))
    assert Decimal(mezcladas["total"]) == esperado


def test_una_factura_c_va_sin_iva_y_con_el_total_de_las_ordenes(cliente, datos):
    """Un comprobante clase C no discrimina IVA: el precio es el total de la orden y la alícuota 0."""
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a], tipo="factura_c")

    assert [i["iva_rate"] for i in pf["items"]] == [0.0]
    assert [i["unit_price"] for i in pf["items"]] == [1210.0]
    assert Decimal(pf["total"]) == Decimal(a["total"])
    comp = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert comp.status_code == 201, comp.text
    assert Decimal(comp.json()["total"]) == Decimal(a["total"])


def test_una_orden_reservada_no_entra_en_otra_pre_factura(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "500.00")
    primera = _crear(cliente, datos, [a])

    r = pre_factura(cliente, datos, [a, b])
    assert r.status_code == 409
    assert "PF-0001" in r.text and str(a["id"]) in r.text
    # No quedó nada a medias: ni la segunda pre factura ni la reserva de la orden libre.
    assert [p["id"] for p in cliente.get("/api/pre-facturas").json()["items"]] == [primera["id"]]
    assert _reservadas(cliente) == [a["id"]]


def test_una_orden_de_otro_cliente_no_entra(cliente, datos):
    a = orden(cliente, datos, "100.00")
    ajena = orden(cliente, datos, "200.00", cliente_id=datos["otro_cliente"])
    r = pre_factura(cliente, datos, [a, ajena])
    assert r.status_code == 422
    assert str(ajena["id"]) in r.text
    assert cliente.get("/api/pre-facturas").json()["items"] == []


def test_una_orden_ya_facturada_no_entra(cliente, datos):
    a = orden(cliente, datos, "100.00")
    primera = _crear(cliente, datos, [a])
    assert cliente.post(f"/api/pre-facturas/{primera['id']}/facturar").status_code == 201

    r = pre_factura(cliente, datos, [a])
    assert r.status_code == 409
    assert "facturada" in r.text


def test_las_ordenes_repetidas_no_duplican_el_importe(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    r = cliente.post("/api/pre-facturas", json={
        "fecha": "2026-08-15", "cliente_id": datos["cliente"],
        "tipo": "factura_a", "orden_ids": [a["id"], a["id"]]})
    assert r.status_code == 422
    assert "repetida" in r.text


def test_una_orden_que_no_existe_da_404(cliente, datos):
    assert pre_factura(cliente, datos, [9999]).status_code == 404


def test_una_nota_de_credito_no_se_genera_sobre_ordenes(cliente, datos):
    a = orden(cliente, datos, "100.00")
    assert pre_factura(cliente, datos, [a], tipo="nota_credito_a").status_code == 422


def test_el_cuerpo_no_acepta_items_ni_punto_de_venta_ni_numero(cliente, datos):
    """Se sacó el registro a mano: ni los ítems ni el punto de venta ni el número se mandan."""
    a = orden(cliente, datos, "1000.00")
    base = {"fecha": "2026-08-15", "cliente_id": datos["cliente"],
            "tipo": "factura_a", "orden_ids": [a["id"]]}
    for extra in ({"punto_venta": 1}, {"numero": 7}, {"razon_social_id": 1},
                  {"items": [{"description": "x", "qty": 1, "unit_price": 1}]}):
        r = cliente.post("/api/pre-facturas", json=base | extra)
        assert r.status_code == 422, extra
    assert cliente.get("/api/pre-facturas").json()["items"] == []
    assert _reservadas(cliente) == []


def test_el_router_del_motor_no_deja_crear_ni_editar_con_items(cliente, datos):
    """Las rutas de crear y editar del motor se reemplazan: una pre factura sin órdenes no se podría facturar."""
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    sin_ordenes = {"cliente_razon": "Agro Norte", "items": [
        {"description": "Flete", "qty": 1, "unit_price": 100, "iva_rate": 0.21}]}
    assert cliente.post("/api/pre-facturas", json=sin_ordenes).status_code == 422
    assert cliente.put(f"/api/pre-facturas/{pf['id']}", json=sin_ordenes).status_code == 422


def test_una_fce_pide_el_vencimiento_y_el_cuit_del_cliente(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    sin_vencimiento = pre_factura(cliente, datos, [a], tipo="fce_a")
    assert sin_vencimiento.status_code == 422
    assert "vencimiento" in sin_vencimiento.text

    vencida = pre_factura(cliente, datos, [a], tipo="fce_a", fecha="2026-01-10", vencimiento="2026-01-20")
    assert vencida.status_code == 422
    assert "anterior a hoy" in vencida.text

    sin_fce = pre_factura(cliente, datos, [a], vencimiento="2099-01-01")
    assert sin_fce.status_code == 422
    assert "solo la factura de credito electronica" in sin_fce.text

    ajena = orden(cliente, datos, "100.00", cliente_id=datos["otro_cliente"])
    sin_cuit = pre_factura(cliente, datos, [ajena], tipo="fce_a", cliente_id=datos["otro_cliente"],
                           fecha="2099-01-01", vencimiento="2099-02-01")
    assert sin_cuit.status_code == 422
    assert "CUIT de 11" in sin_cuit.text

    ok = pre_factura(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01")
    assert ok.status_code == 201, ok.text
    assert ok.json()["tipo_comprobante"] == 201
    assert ok.json()["fecha_vencimiento_pago"] == "2099-02-01"


def test_una_orden_reservada_no_se_edita_ni_se_anula(cliente, datos):
    """La pre factura quedaría diciendo un importe que la orden ya no dice."""
    a = orden(cliente, datos, "1000.00")
    _crear(cliente, datos, [a])
    cuerpo = {"fecha": "2026-08-10", "cliente_id": datos["cliente"],
              "origen_id": datos["origen"], "destino_id": datos["destino"], "tarifa": "9999.00"}

    r = cliente.put(f"/api/ordenes/{a['id']}", json=cuerpo)
    assert r.status_code == 409
    assert "PF-0001" in r.text
    assert cliente.delete(f"/api/ordenes/{a['id']}").status_code == 409
    assert Decimal(cliente.get(f"/api/ordenes/{a['id']}").json()["tarifa"]) == Decimal("1000.00")


def test_ordenes_que_suman_cero_no_tienen_nada_que_facturar(cliente, datos):
    a = orden(cliente, datos, "0.00")
    r = pre_factura(cliente, datos, [a])
    assert r.status_code == 422
    assert "suman cero" in r.text


def test_un_cliente_que_no_existe_da_404(cliente, datos):
    a = orden(cliente, datos, "100.00")
    assert pre_factura(cliente, datos, [a], cliente_id=9999).status_code == 404


def test_el_listado_y_el_detalle_traen_lo_propio(cliente, datos):
    a = orden(cliente, datos, "100.00")
    b = orden(cliente, datos, "200.00", cliente_id=datos["otro_cliente"])
    primera = _crear(cliente, datos, [a])
    segunda = _crear(cliente, datos, [b], cliente_id=datos["otro_cliente"])

    listado = cliente.get("/api/pre-facturas").json()
    assert [p["numero_interno"] for p in listado["items"]] == ["PF-0002", "PF-0001"]
    assert listado["counts"]["pendiente"] == 2 and listado["counts"]["facturado"] == 0
    assert [p["id"] for p in cliente.get(f"/api/pre-facturas?cliente_id={datos['otro_cliente']}")
            .json()["items"]] == [segunda["id"]]
    assert [p["id"] for p in cliente.get("/api/pre-facturas?estado=aceptado").json()["items"]] == []
    assert cliente.get("/api/pre-facturas?estado=inventado").status_code == 422
    assert cliente.get(f"/api/pre-facturas/{primera['id']}").json()["orden_ids"] == [a["id"]]
    assert cliente.get("/api/pre-facturas/9999").status_code == 404


# ── 2. Editar y anular ──────────────────────────────────────────────────────


def _cuerpo_de_edicion(datos, ordenes, **cambios):
    return {"fecha": "2026-08-15", "tipo": "factura_a",
            "orden_ids": [o["id"] for o in ordenes]} | cambios


def test_editar_reemplaza_las_ordenes_y_libera_las_que_salen(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "500.00")
    c = orden(cliente, datos, "250.00")
    pf = _crear(cliente, datos, [a, b])

    r = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [b, c]))
    assert r.status_code == 200, r.text
    editada = r.json()
    assert editada["orden_ids"] == [b["id"], c["id"]]
    assert Decimal(editada["total"]) == Decimal(b["total"]) + Decimal(c["total"])
    assert editada["numero_interno"] == "PF-0001", "sigue siendo la misma pre factura"
    # `a` quedó libre y se puede incluir en otra; `c` quedó reservada.
    assert _reservadas(cliente) == [b["id"], c["id"]]
    assert cliente.get("/api/ordenes?reservada=false").json()[0]["id"] == a["id"]
    assert _crear(cliente, datos, [a])["numero_interno"] == "PF-0002"


def test_editar_cambia_tipo_y_fecha(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])

    r = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(
        datos, [a], tipo="factura_b", fecha="2026-08-20"))
    assert r.status_code == 200, r.text
    assert r.json()["tipo_comprobante"] == 6
    assert r.json()["fecha_sugerida"] == "2026-08-20"


def test_editar_una_orden_reservada_en_otra_o_ajena_se_rechaza_y_no_toca_nada(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "500.00")
    ajena = orden(cliente, datos, "200.00", cliente_id=datos["otro_cliente"])
    primera = _crear(cliente, datos, [a])
    _crear(cliente, datos, [b])

    r = cliente.put(f"/api/pre-facturas/{primera['id']}", json=_cuerpo_de_edicion(datos, [a, b]))
    assert r.status_code == 409
    assert "PF-0002" in r.text
    r = cliente.put(f"/api/pre-facturas/{primera['id']}", json=_cuerpo_de_edicion(datos, [a, ajena]))
    assert r.status_code == 422
    assert cliente.get(f"/api/pre-facturas/{primera['id']}").json()["orden_ids"] == [a["id"]]
    assert _reservadas(cliente, primera["id"]) == [a["id"]]


def test_editar_una_aceptada_la_devuelve_a_pendiente(cliente, datos):
    """El cliente aceptó **otros** datos: la marca de aceptada no se conserva sobre un contenido distinto."""
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "500.00")
    pf = _crear(cliente, datos, [a])
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/aceptar").json()["estado"] == "aceptado"

    # Sin cambios no se mueve el estado.
    sin_cambios = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [a]))
    assert sin_cambios.json()["estado"] == "aceptado"

    r = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [a, b]))
    assert r.json()["estado"] == "pendiente"
    assert r.json()["aceptado_por"] is None


def test_anular_libera_las_ordenes(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/anular", json={"motivo": "el cliente cambió el pedido"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "descartado"
    assert r.json()["resuelto_por"] == "admin"
    assert r.json()["motivo_descarte"] == "el cliente cambió el pedido"
    assert _reservadas(cliente) == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    # Se puede incluir en otra, y la anulada conserva su número (no se reusa).
    assert _crear(cliente, datos, [a])["numero_interno"] == "PF-0002"
    # Una anulada es final: ni se edita ni se factura ni se anula de nuevo.
    assert cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [a])).status_code == 409
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").status_code == 409
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/anular", json={}).status_code == 409


def test_aceptar_lo_marca_el_operador_y_queda_quien(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    r = cliente.post(f"/api/pre-facturas/{pf['id']}/aceptar")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aceptado"
    assert r.json()["aceptado_por"] == "admin"
    assert r.json()["aceptado_at"]


def test_editar_una_anulada_se_rechaza(cliente, datos):
    """Una anulada es final. Con las órdenes libres, lo que frena es el estado y no las órdenes."""
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    cliente.post(f"/api/pre-facturas/{pf['id']}/anular", json={})

    r = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [a]))
    assert r.status_code == 409
    assert "descartado" in r.text
    assert _reservadas(cliente) == []


def test_una_fila_de_la_bandeja_que_no_es_de_este_producto_no_se_edita_ni_se_factura(cliente, datos):
    """Una pre factura del motor sin su fila de `pre_facturas_cargo` (creada por fuera de la API)."""
    a = orden(cliente, datos, "1000.00")
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        ajena = dominio_pre_facturas.crear(
            origen_producto="libracargo", cliente_razon="Agro Norte", conn=conn, items=[
                {"description": "Flete", "qty": 1, "unit_price": 100, "iva_rate": 0.21}])
        conn.commit()

    assert cliente.put(f"/api/pre-facturas/{ajena['id']}", json=_cuerpo_de_edicion(datos, [a])).status_code == 404
    assert cliente.post(f"/api/pre-facturas/{ajena['id']}/facturar").status_code == 404
    # Y la de otro producto ni se ve.
    with libracore_core.get_connection() as conn:
        otra = dominio_pre_facturas.crear(
            origen_producto="otro-producto", cliente_razon="Agro Norte", conn=conn, items=[
                {"description": "Flete", "qty": 1, "unit_price": 100, "iva_rate": 0.21}])
        conn.commit()
    assert cliente.get(f"/api/pre-facturas/{otra['id']}").status_code == 404
    assert cliente.get(f"/api/pre-facturas/{otra['id']}/pdf").status_code == 404
    assert [p["id"] for p in cliente.get("/api/pre-facturas").json()["items"]] == [ajena["id"]]


# ── 3. El PDF y el correo ───────────────────────────────────────────────────


def test_el_pdf_sale_y_dice_que_no_es_fiscal(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])

    r = cliente.get(f"/api/pre-facturas/{pf['id']}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "PF-0001.pdf" in r.headers["content-disposition"]
    assert cliente.get("/api/pre-facturas/9999/pdf").status_code == 404


def test_el_emisor_del_pdf_es_la_empresa(cliente, datos, sesion):
    """El nombre, el CUIT, la condición de IVA, el domicilio y el logo son los de «Datos de la empresa» (ADR-035)."""
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    emisor = emisor_de(sesion, pf)
    assert emisor["nombre"] == "Transportes de Prueba SRL"
    assert emisor["cuit"] == CUIT_EMISOR
    assert emisor["iva_condition"] == "Responsable Inscripto"
    assert emisor["direccion"] == ""

    cargar_empresa(cliente, domicilio="Calle Falsa 123", localidad="Suipacha", provincia="Buenos Aires",
                   ingresos_brutos="123-456")
    emisor = emisor_de(sesion, pf)
    assert emisor["direccion"] == "Calle Falsa 123, Suipacha, Buenos Aires"
    assert emisor["iibb"] == "123-456"


def test_enviar_por_correo_la_marca_enviada_y_si_falla_queda_como_estaba(cliente, datos, monkeypatch):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    enviados = []
    monkeypatch.setattr(dominio_pre_facturas, "smtp_efectivo", lambda resolver: {
        "host": "smtp.ejemplo.test", "port": 587, "user": "u", "password": "p",
        "from_email": "facturacion@ejemplo.test", "from_name": "Suitrans"})
    monkeypatch.setattr(email_sender, "enviar_documento", lambda **kw: enviados.append(kw))

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "enviado"
    assert r.json()["enviado_a"] == "compras@agronorte.test"
    assert enviados[0]["to_email"] == "compras@agronorte.test"
    assert enviados[0]["pdf_bytes"].startswith(b"%PDF")
    assert enviados[0]["filename"] == "PF-0001.pdf"
    assert "no es una factura" in enviados[0]["cuerpo"]

    def falla(**kw):
        raise OSError("sin red")

    otra = _crear(cliente, datos, [orden(cliente, datos, "10.00")])
    monkeypatch.setattr(email_sender, "enviar_documento", falla)
    r = cliente.post(f"/api/pre-facturas/{otra['id']}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 502
    assert cliente.get(f"/api/pre-facturas/{otra['id']}").json()["estado"] == "pendiente"


def test_enviar_sin_smtp_dice_donde_configurarlo(cliente, datos, monkeypatch):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    monkeypatch.setattr(dominio_pre_facturas, "smtp_efectivo", lambda resolver: {
        "host": "", "port": 587, "user": "", "password": "", "from_email": "", "from_name": ""})
    r = cliente.post(f"/api/pre-facturas/{pf['id']}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 400
    assert "Configuración → Email" in r.text


# ── 4. Facturar por ARCA ────────────────────────────────────────────────────


def test_facturar_emite_por_arca_y_cierra_todo_junto(cliente, datos, emisor):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "2500.55")
    pf = _crear(cliente, datos, [a, b])

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 201, r.text
    comp = r.json()
    # El número lo puso ARCA y el punto de venta es el de su configuración: no se tipean.
    assert comp["numero"] == 1 and comp["punto_venta"] == 1
    assert comp["cae"] == "75123456789012"
    assert comp["fecha"] == "2026-08-15"
    assert Decimal(comp["total"]) == Decimal(pf["total"])
    assert ("ultimo", 1, 1, CUIT_EMISOR) in emisor

    # La pre factura quedó facturada y atada a su factura; ya no reserva nada.
    cerrada = cliente.get(f"/api/pre-facturas/{pf['id']}").json()
    assert cerrada["estado"] == "facturado"
    assert cerrada["factura_id"] == comp["id"]
    assert cerrada["resuelto_por"] == "admin"
    assert _reservadas(cliente) == []
    # Las órdenes pasaron a facturadas, con su comprobante, como siempre.
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
    # Y el detalle del comprobante no marca alarma: lo que dice es lo que suman sus órdenes.
    assert cliente.get(f"/api/comprobantes/{comp['id']}").json()["coinciden"] is True
    # La nueva facturada sale en los totales, que coinciden.
    assert cliente.get("/api/comprobantes/totales").json()["coinciden"] is True


def test_una_pre_factura_facturada_no_se_factura_dos_veces(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").status_code == 201

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "facturada" in r.text
    assert len(cliente.get("/api/comprobantes").json()) == 1


def test_se_puede_facturar_sin_haberla_aceptado_pero_tambien_aceptada(cliente, datos):
    """La conformidad la marca el operador y no es un paso obligatorio: lo que decide es la pantalla."""
    a = orden(cliente, datos, "100.00")
    b = orden(cliente, datos, "200.00")
    sin_aceptar = _crear(cliente, datos, [a])
    aceptada = _crear(cliente, datos, [b])
    cliente.post(f"/api/pre-facturas/{aceptada['id']}/aceptar")

    assert cliente.post(f"/api/pre-facturas/{sin_aceptar['id']}/facturar").status_code == 201
    assert cliente.post(f"/api/pre-facturas/{aceptada['id']}/facturar").status_code == 201


def test_si_cambio_el_cliente_no_se_factura_otra_cosa_y_editar_refresca_la_foto(cliente, datos):
    """El cliente va como foto en la pre factura: lo que se le mandó es lo que se factura, o se avisa."""
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte SA", "es_cliente": True, "cuit": "30-12345678-1"})

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "datos del cliente cambiaron" in r.text
    assert cliente.get("/api/comprobantes").json() == []

    editada = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [a])).json()
    assert editada["cliente_razon"] == "Agro Norte SA"
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").status_code == 201


def test_sin_ordenes_reservadas_no_se_factura(cliente, datos, sesion):
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    sesion.execute(text("DELETE FROM pre_factura_ordenes"))
    sesion.commit()

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "no tiene ordenes reservadas" in r.text


def test_si_el_numero_que_da_arca_ya_esta_registrado_no_se_factura(cliente, datos, sesion):
    """Lo registrado a mano antes tiene el 0001-00000001: ARCA daría el mismo y chocaría, y se dice antes."""
    from tests.test_comprobantes import facturado_a_mano

    previa = orden(cliente, datos, "100.00")
    facturado_a_mano(sesion, datos, [previa], numero=1)
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "ya está registrado" in r.text
    assert cliente.get(f"/api/pre-facturas/{pf['id']}").json()["estado"] == "pendiente"
    assert _estado_de_la_orden(cliente, a) == "pendiente"


def test_con_dos_configuraciones_de_arca_no_elige_una_para_facturar(cliente, datos):
    """El motor hace `arca_cfg[0]`; este producto se niega: facturar por otro contribuyente sin fallar es peor."""
    from libracore.db import arca_config as db_arca_config

    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    libracore_core.configure(URL_CORE)
    db_arca_config.crear_arca_config(
        empresa="colada", cuit="30-99999999-7", punto_venta=9,
        clave_path="", certificado_path="", ambiente="homologacion")

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "colada" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []


def test_facturar_con_otra_fecha_usa_esa_fecha(cliente, datos):
    """A los días de generarla, ARCA puede no aceptar la fecha vieja."""
    a = orden(cliente, datos, "100.00")
    pf = _crear(cliente, datos, [a])
    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar", json={"fecha": "2026-08-30"})
    assert r.status_code == 201, r.text
    assert r.json()["fecha"] == "2026-08-30"


def test_sin_certificado_no_se_factura_y_no_se_toca_nada(cliente, datos):
    """🔴 La instancia no tiene el par de ARCA cargado: el error lo dice y nada cambia."""
    from libracore.db import arca_config as db_arca_config

    for fila in db_arca_config.obtener_todas_arca_configs():
        db_arca_config.eliminar_arca_config(fila["empresa"])
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "ARCA no está configurado" in r.json()["detail"]
    assert "queda lista para facturar cuando esté resuelto" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert _reservadas(cliente, pf["id"]) == [a["id"]], "sigue reservada: la pre factura sigue abierta"
    abierta = cliente.get(f"/api/pre-facturas/{pf['id']}").json()
    assert abierta["estado"] == "pendiente" and abierta["factura_id"] is None


def test_si_arca_rechaza_la_pre_factura_sigue_abierta_y_no_queda_nada(cliente, datos, monkeypatch):
    """El control de la transacción: un rechazo no deja comprobante, ni asiento, ni la pre factura cerrada."""
    arca_responde(monkeypatch, falla_cae="El comprobante ya fue autorizado")
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 502, r.text
    assert "ya fue autorizado" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert _reservadas(cliente, pf["id"]) == [a["id"]]
    abierta = cliente.get(f"/api/pre-facturas/{pf['id']}").json()
    assert abierta["estado"] == "pendiente" and abierta["factura_id"] is None

    # Y se puede reintentar cuando ARCA vuelva: es la misma pre factura.
    arca_responde(monkeypatch)
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").status_code == 201


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, monkeypatch):
    arca_responde(monkeypatch, falla_numero="Computador no autorizado")
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 502
    assert "no autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/pre-facturas/{pf['id']}").json()["estado"] == "pendiente"


def test_si_una_orden_cambio_en_la_base_no_se_factura_otra_cosa(cliente, datos, sesion):
    """Las órdenes reservadas no se editan por la API; si cambian por debajo, la factura no sale distinta."""
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    sesion.execute(text("UPDATE ordenes_carga SET tarifa = 2000, iva = 420, total = 2420 WHERE id = :i"),
                   {"i": a["id"]})
    sesion.commit()

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 409
    assert "cambiaron desde que se genero" in r.text
    assert cliente.get("/api/comprobantes").json() == []

    # Se actualiza editándola, y ahí sí.
    actualizada = cliente.put(f"/api/pre-facturas/{pf['id']}", json=_cuerpo_de_edicion(datos, [a]))
    assert Decimal(actualizada.json()["total"]) == Decimal("2420.00")
    assert cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").status_code == 201


def test_facturar_una_fce_sale_con_vencimiento_cbu_y_modalidad(cliente, datos, emisor):
    cliente.put("/api/arca", json={
        "empresa": "agencia", "cuit": CUIT_EMISOR, "punto_venta": 1, "ambiente": "produccion",
        "alias": "", "fce_cbu": "0000003100012345678901", "fce_transmision": "sca"})
    a = orden(cliente, datos, "5000.00")
    pf = _crear(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01")

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar", json={"fecha": "2099-01-01"})
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["tipo"] == "fce_a"
    assert comp["fch_vto_pago"] == "2099-02-01"
    assert comp["fce_cbu"] == "0000003100012345678901"
    assert comp["fce_transmision"] == "SCA"
    pedido = next(p[1] for p in emisor if p[0] == "cae")
    assert pedido["fch_vto_pago"] == "2099-02-01"


# ── 4b. En qué cuenta se cobra la FCE (libracore ADR-040) ───────────────────

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
    pf = _crear(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01",
                cuenta="agencia.nacion")
    assert pf["fce_cbu"] == CBU_NACION, "se guarda el CBU aunque se elija por alias"
    assert pf["fce_cuenta"] == {"cbu": CBU_NACION, "alias": "agencia.nacion", "etiqueta": "Nación"}

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar", json={"fecha": "2099-01-01"})
    assert r.status_code == 201, r.text
    assert r.json()["fce_cbu"] == CBU_NACION
    pedido = next(p[1] for p in emisor if p[0] == "cae")
    assert pedido["fce_cbu"] == CBU_NACION, "a ARCA va el CBU elegido, no el de la configuración"


def test_una_fce_sin_elegir_cuenta_sale_con_la_predeterminada(cliente, datos, emisor):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "5000.00")
    pf = _crear(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01")
    assert pf["fce_cbu"] is None
    assert pf["fce_cuenta"]["cbu"] == CBU_GALICIA, "se muestra dónde se va a cobrar"

    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar", json={"fecha": "2099-01-01"})
    assert r.status_code == 201, r.text
    assert r.json()["fce_cbu"] == CBU_GALICIA


def test_una_cuenta_que_no_esta_cargada_no_se_acepta(cliente, datos):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "5000.00")
    r = pre_factura(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01",
                    cuenta="2850590940090418135201")
    assert r.status_code == 422
    assert "no está entre los cargados" in r.text
    assert _reservadas(cliente) == [], "no quedó nada reservado"


def test_editar_cambia_la_cuenta_y_vacio_vuelve_a_la_predeterminada(cliente, datos):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "5000.00")
    pf = _crear(cliente, datos, [a], tipo="fce_a", fecha="2099-01-01", vencimiento="2099-02-01")
    cuerpo = {"tipo": "fce_a", "fecha": "2099-01-01", "fecha_vencimiento_pago": "2099-02-01",
              "orden_ids": [a["id"]]}

    r = cliente.put(f"/api/pre-facturas/{pf['id']}", json=cuerpo | {"fce_cbu": CBU_NACION})
    assert r.status_code == 200, r.text
    assert r.json()["fce_cbu"] == CBU_NACION
    r = cliente.put(f"/api/pre-facturas/{pf['id']}", json=cuerpo | {"fce_cbu": ""})
    assert r.json()["fce_cbu"] is None
    assert r.json()["fce_cuenta"]["cbu"] == CBU_GALICIA


def test_una_factura_comun_no_lleva_cuenta_aunque_se_mande(cliente, datos):
    _dos_cuentas(cliente)
    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a], cuenta="agencia.nacion")
    assert pf["fce_cbu"] is None and pf["fce_cuenta"] is None


# ── 5. Ya no hay registro a mano ────────────────────────────────────────────


def test_ya_no_se_puede_registrar_un_comprobante_a_mano(cliente, datos):
    """Se sacó del todo: ni sin certificado ni con él. `POST /api/comprobantes` ya no existe."""
    a = orden(cliente, datos, "1000.00")
    cuerpo = {"fecha": "2026-08-15", "cliente_id": datos["cliente"],
              "tipo": "factura_a", "punto_venta": 1, "numero": 7, "orden_ids": [a["id"]]}
    r = cliente.post("/api/comprobantes", json=cuerpo)
    assert r.status_code == 405
    assert cliente.get("/api/comprobantes").json() == []
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert _reservadas(cliente) == []


def test_la_api_no_nombra_el_punto_de_venta_ni_el_numero_en_ninguna_entrada(cliente):
    """Ni en el cuerpo de generar, ni de editar, ni de facturar: el esquema de la API no los ofrece."""
    esquemas = cliente.get("/openapi.json").json()["components"]["schemas"]
    for nombre in ("PreFacturaIn", "PreFacturaEditarIn", "FacturarPreFacturaIn"):
        assert {"punto_venta", "numero"}.isdisjoint(esquemas[nombre]["properties"]), nombre
    assert "FacturarIn" not in esquemas


def test_la_anulacion_de_un_comprobante_sin_cae_migrado_sigue_existiendo(cliente, datos, sesion):
    """Lo que ya estaba registrado a mano (o migrado del legado) se sigue anulando como siempre."""
    from tests.conftest import comprobante_de_prueba

    comp = comprobante_de_prueba(
        sesion, tipo=_tipo("factura_a"), punto_venta=3, numero=77,
        fecha=_fecha("2026-05-10"), cliente_id=datos["cliente"], neto=100, iva=21, total=121)
    r = cliente.delete(f"/api/comprobantes/{comp.id}")
    assert r.status_code == 200, r.text
    assert r.json()["anulado"] is True


def _tipo(valor):
    from app.models.enums import TipoComprobante

    return TipoComprobante(valor)


def _fecha(iso):
    from datetime import date

    return date.fromisoformat(iso)


# ── 6. Anular el comprobante devuelve las órdenes, y se pueden volver a pre facturar ─


def test_anular_el_comprobante_deja_las_ordenes_libres_para_otra_pre_factura(cliente, datos, sesion):
    """Las reservas se borran al facturar: una orden que vuelve a pendientes no queda atada a la vieja."""
    from app.models.operacion import ComprobanteCargo

    a = orden(cliente, datos, "1000.00")
    pf = _crear(cliente, datos, [a])
    comp = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar").json()
    # Un comprobante con CAE no se anula desde acá (hace falta una nota de crédito): se simula uno sin CAE.
    sesion.execute(text("UPDATE facturas SET cae = '' WHERE id = :i"), {"i": comp["id"]})
    sesion.commit()
    assert sesion.get(ComprobanteCargo, comp["id"]) is not None

    assert cliente.delete(f"/api/comprobantes/{comp['id']}").status_code == 200
    assert _estado_de_la_orden(cliente, a) == "pendiente"
    assert _crear(cliente, datos, [a])["numero_interno"] == "PF-0002"
