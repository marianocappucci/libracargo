"""Comprobantes y facturar pendientes.

El criterio de F5 en el ROADMAP es que **los totales facturados sean
reproducibles**, y eso es lo que más se prueba acá: el mismo importe contado por
los encabezados de los comprobantes y por las órdenes que agrupan.

> 🔑 **Cada alarma se prueba con su control.** Que el gate diga "coinciden" no
> significa nada si no se muestra que sabe decir lo contrario: por eso los tests
> del gate tuercen un dato **en la base** —simulando lo que va a llegar de la
> migración de F6— y verifican que ahí sí avisa.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.testing import crear_schema_de_auth
from sqlalchemy import select, text

from app.main import crear_app
from app.models import EstadoOrden, OrdenCarga, RolCuenta, TipoComprobante
from app.servicios import comprobantes, cuentas
from tests.conftest import comprobante_de_prueba, config_de_prueba, vaciar_auth

# Todos arrancan con la empresa lista para emitir por ARCA (simulada): ver `emisor` en el conftest.
pytestmark = pytest.mark.con_emisor


def orden(cliente, datos, tarifa, *, cliente_id=None, fecha="2026-08-10"):
    cuerpo = {
        "fecha": fecha,
        "cliente_id": cliente_id or datos["cliente"],
        "origen_id": datos["origen"], "destino_id": datos["destino"],
        "tarifa": tarifa,
    }
    r = cliente.post("/api/ordenes", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def pre_factura(cliente, datos, ordenes, *, tipo="factura_a", cliente_id=None,
                fecha="2026-08-15", vencimiento=None, cuenta=None):
    """Genera la pre factura de las órdenes. Sin punto de venta ni número: no se tipean más (ADR-032)."""
    cuerpo = {
        "fecha": fecha,
        "cliente_id": cliente_id or datos["cliente"], "tipo": tipo,
        "orden_ids": [o["id"] if isinstance(o, dict) else o for o in ordenes],
    }
    if vencimiento is not None:
        cuerpo["fecha_vencimiento_pago"] = vencimiento
    if cuenta is not None:
        cuerpo["fce_cbu"] = cuenta
    return cliente.post("/api/pre-facturas", json=cuerpo)


def facturar(cliente, datos, ordenes, **kw):
    """El camino de siempre: pre factura y después ARCA. Devuelve la respuesta de lo **último que se hizo**.

    Si la pre factura no se pudo generar (otro cliente, una orden ya facturada...), es ésa. Si se generó,
    es la de `POST /api/pre-facturas/{id}/facturar`: el comprobante, o el error de la emisión. Los tests que
    usan esto tienen que correr con la empresa lista para emitir (marca `con_emisor`).
    """
    r = pre_factura(cliente, datos, ordenes, **kw)
    if r.status_code != 201:
        return r
    return cliente.post(f"/api/pre-facturas/{r.json()['id']}/facturar")


def facturado_a_mano(sesion, datos, ordenes, *, tipo=TipoComprobante.FACTURA_A, punto_venta=1,
                     numero=1, fecha=date(2026, 8, 15)):
    """Un comprobante **sin CAE** con sus órdenes y su asiento: lo que había registrado a mano antes de ADR-032.

    Ya no se puede crear por la API (la facturación sale de una pre factura y siempre emite por ARCA), pero
    lo registrado así y lo migrado del legado siguen existiendo, y se anulan como siempre. Los tests de
    esa anulación, de los totales y del listado arman el dato **por abajo**, con las mismas funciones que
    usaba el alta (`servicios.comprobantes`, `servicios.cuentas`).
    """
    filas = list(sesion.scalars(select(OrdenCarga).where(
        OrdenCarga.id.in_([o["id"] if isinstance(o, dict) else o for o in ordenes]))))
    suma = comprobantes.sumar_ordenes(filas)
    comp = comprobante_de_prueba(
        sesion, tipo=tipo, punto_venta=punto_venta, numero=numero, fecha=fecha,
        cliente_id=datos["cliente"], neto=suma.neto, iva=suma.iva, total=suma.total)
    for orden_ in filas:
        orden_.comprobante_id = comp.id
        orden_.estado = EstadoOrden.FACTURADA
    cuentas.asentar(
        sesion, fecha=fecha, tercero_id=datos["cliente"], rol=RolCuenta.CLIENTE,
        concepto=comprobantes.etiqueta(tipo, punto_venta, numero),
        descripcion="Ordenes " + ", ".join(str(o.id) for o in filas),
        debe=suma.total, haber=0, comprobante_id=comp.id)
    sesion.commit()
    return comp


def test_facturar_pendientes_agrupa_las_ordenes_en_un_comprobante(cliente, datos):
    """El comprobante suma sus órdenes, y las órdenes quedan apuntando a él."""
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "2500.55")

    r = facturar(cliente, datos, [a, b])
    assert r.status_code == 201, r.text
    comp = r.json()

    # El neto es la suma de las tarifas y el IVA la suma de los IVA de cada
    # orden, no el IVA recalculado sobre el neto: con alicuotas o redondeos
    # distintos por orden, las dos cuentas no dan lo mismo.
    assert Decimal(comp["neto"]) == Decimal("3500.55")
    assert Decimal(comp["iva"]) == Decimal(a["iva"]) + Decimal(b["iva"])
    assert Decimal(comp["total"]) == Decimal(a["total"]) + Decimal(b["total"])

    for o in (a, b):
        actual = cliente.get(f"/api/ordenes/{o['id']}").json()
        assert actual["estado"] == "facturada"
        assert actual["comprobante_id"] == comp["id"]

    # Y la lista de pendientes ya no las trae.
    pendientes = cliente.get("/api/ordenes?facturada=false").json()
    assert pendientes == []


def test_facturar_deja_la_deuda_en_la_cuenta_del_cliente(cliente, datos):
    """El comprobante y su asiento entran juntos, en una sola transacción."""
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a]).json()

    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    assert len(cuenta["movimientos"]) == 1
    mov = cuenta["movimientos"][0]["movimiento"]
    assert mov["comprobante_id"] == comp["id"]
    assert Decimal(mov["debe"]) == Decimal(comp["total"])
    assert Decimal(mov["haber"]) == Decimal("0.00")
    # El concepto se lee como el papel, sin cruzar ids a mano.
    assert mov["concepto"] == "Factura A 0001-00000001"
    assert cuenta["coinciden"] is True
    assert Decimal(cuenta["saldo"]) == Decimal(comp["total"])


def test_los_totales_dan_igual_por_los_dos_lados(cliente, datos, sesion):
    """El gate de F5: lo facturado, contado por los encabezados y por las órdenes.

    Uno sale por ARCA (pre factura); el otro es lo que ya estaba registrado a mano, dato de antes de ADR-032.
    """
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "2000.00")
    c = orden(cliente, datos, "500.00")
    assert facturar(cliente, datos, [a, b]).status_code == 201
    facturado_a_mano(sesion, datos, [c], punto_venta=2)

    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is True
    assert Decimal(total["neto_comprobantes"]) == Decimal("3500.00")
    assert Decimal(total["neto_ordenes"]) == Decimal("3500.00")
    assert total["cantidad_comprobantes"] == 2
    assert total["cantidad_ordenes"] == 3


def test_el_gate_avisa_cuando_la_orden_no_dice_lo_que_el_comprobante(cliente, datos, sesion):
    """El control de la alarma: sin esto, "coinciden" no significaría nada.

    Se tuerce el importe **de la orden** por SQL directo, que es lo que puede llegar de una migración o de
    una mano en la base: la API no deja hacerlo, por eso el sabotaje va por debajo.
    """
    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a]).status_code == 201
    assert cliente.get("/api/comprobantes/totales").json()["coinciden"] is True

    sesion.execute(text("UPDATE ordenes_carga SET tarifa = tarifa + 1, total = total + 1 WHERE id = :id"),
                   {"id": a["id"]})
    sesion.commit()

    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is False
    assert Decimal(total["neto_comprobantes"]) == Decimal("1000.00")
    assert Decimal(total["neto_ordenes"]) == Decimal("1001.00")


def test_el_detalle_avisa_cuando_el_comprobante_no_dice_lo_que_sus_ordenes(cliente, datos, sesion):
    """Mismo control, a nivel de un comprobante."""
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a]).json()
    detalle = cliente.get(f"/api/comprobantes/{comp['id']}").json()
    assert detalle["coinciden"] is True
    assert len(detalle["ordenes"]) == 1
    assert Decimal(detalle["suma_de_ordenes"]["total"]) == Decimal(comp["total"])

    sesion.execute(text("UPDATE ordenes_carga SET total = total + 1 WHERE id = :id"),
                   {"id": a["id"]})
    sesion.commit()
    assert cliente.get(f"/api/comprobantes/{comp['id']}").json()["coinciden"] is False


def test_una_orden_no_se_factura_dos_veces(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "500.00")
    assert facturar(cliente, datos, [a]).status_code == 201

    r = facturar(cliente, datos, [a, b])
    assert r.status_code == 409
    assert str(a["id"]) in r.text
    # Y no quedo nada a medias: ni el comprobante nuevo ni la orden que sí
    # estaba pendiente.
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert cliente.get(f"/api/ordenes/{b['id']}").json()["estado"] == "pendiente"


def test_un_comprobante_es_de_un_solo_cliente(cliente, datos):
    a = orden(cliente, datos, "100.00")
    ajena = orden(cliente, datos, "200.00", cliente_id=datos["otro_cliente"])
    r = facturar(cliente, datos, [a, ajena])
    assert r.status_code == 422
    assert cliente.get("/api/comprobantes").json() == []


def test_una_nota_de_credito_no_se_registra_sobre_ordenes(cliente, datos):
    a = orden(cliente, datos, "100.00")
    r = facturar(cliente, datos, [a], tipo="nota_credito_a")
    assert r.status_code == 422


def test_no_se_factura_una_orden_que_no_existe(cliente, datos):
    r = facturar(cliente, datos, [9999])
    assert r.status_code == 404
    assert "9999" in r.text


def test_anular_devuelve_las_ordenes_y_revierte_la_cuenta(cliente, datos, sesion):
    """La reversión es un asiento nuevo: la cuenta corriente no se reescribe.

    Un comprobante **sin CAE** (registrado a mano antes de ADR-032, o migrado): con CAE no se anula desde
    acá, se acredita con una nota de crédito.
    """
    a = orden(cliente, datos, "1000.00")
    # Número 77: con el 1 chocaría con el que da ARCA al volver a facturar (que arranca del último + 1).
    comp = facturado_a_mano(sesion, datos, [a], numero=77)
    comp = {"id": comp.id, "fecha": comp.fecha.isoformat()}

    r = cliente.delete(f"/api/comprobantes/{comp['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["anulado"] is True

    actual = cliente.get(f"/api/ordenes/{a['id']}").json()
    assert actual["estado"] == "pendiente"
    assert actual["comprobante_id"] is None

    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    assert len(cuenta["movimientos"]) == 2, "el asiento original tiene que seguir estando"
    assert Decimal(cuenta["saldo"]) == Decimal("0.00")
    assert cuenta["coinciden"] is True
    # La reversion lleva la fecha del comprobante: con un corte anterior a hoy,
    # la cuenta no puede mostrar una deuda que los totales ya no reconocen.
    assert cuenta["movimientos"][-1]["movimiento"]["fecha"] == comp["fecha"]

    # Sale de los totales por los dos lados a la vez.
    total = cliente.get("/api/comprobantes/totales").json()
    assert total["cantidad_comprobantes"] == 0 and total["cantidad_ordenes"] == 0
    assert Decimal(total["total_comprobantes"]) == Decimal("0.00") and total["coinciden"] is True
    # Y el detalle no marca alarma por quedarse sin órdenes: lo que chequea un
    # anulado es que no le haya quedado ninguna colgada.
    detalle = cliente.get(f"/api/comprobantes/{comp['id']}").json()
    assert detalle["ordenes"] == []
    assert detalle["coinciden"] is True

    # Y la orden se puede volver a facturar.
    assert facturar(cliente, datos, [a]).status_code == 201


def test_un_comprobante_anulado_no_se_anula_dos_veces(cliente, datos, sesion):
    a = orden(cliente, datos, "100.00")
    comp = facturado_a_mano(sesion, datos, [a])
    assert cliente.delete(f"/api/comprobantes/{comp.id}").status_code == 200
    assert cliente.delete(f"/api/comprobantes/{comp.id}").status_code == 409
    # Y no dejó un segundo asiento de reversión.
    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    assert len(cuenta["movimientos"]) == 2


def test_la_orden_facturada_no_se_modifica_ni_se_anula(cliente, datos):
    """Cambiarle la tarifa dejaría al comprobante diciendo otro importe."""
    a = orden(cliente, datos, "1000.00")
    facturar(cliente, datos, [a])
    cuerpo = {"fecha": "2026-08-10", "cliente_id": datos["cliente"],
              "origen_id": datos["origen"], "destino_id": datos["destino"],
              "tarifa": "9999.00"}
    assert cliente.put(f"/api/ordenes/{a['id']}", json=cuerpo).status_code == 409
    assert cliente.delete(f"/api/ordenes/{a['id']}").status_code == 409
    assert Decimal(cliente.get(f"/api/ordenes/{a['id']}").json()["tarifa"]) == Decimal("1000.00")


def test_los_totales_se_acotan_por_la_fecha_del_comprobante(cliente, datos):
    """El rango se aplica del mismo lado en las dos cuentas.

    Si el lado de las órdenes filtrara por la fecha de la **orden**, los dos
    conjuntos no serían el mismo y el gate diría "no coinciden" por el recorte.
    Acá la orden es de julio y su comprobante de agosto: con el rango de agosto
    tienen que entrar los dos o ninguno.
    """
    a = orden(cliente, datos, "1000.00", fecha="2026-07-20")
    assert facturar(cliente, datos, [a], fecha="2026-08-15").status_code == 201

    dentro = cliente.get("/api/comprobantes/totales?desde=2026-08-01&hasta=2026-08-31").json()
    assert dentro["cantidad_comprobantes"] == 1
    assert dentro["coinciden"] is True
    assert Decimal(dentro["neto_ordenes"]) == Decimal("1000.00")

    fuera = cliente.get("/api/comprobantes/totales?desde=2026-09-01").json()
    assert fuera["cantidad_comprobantes"] == 0 and fuera["cantidad_ordenes"] == 0
    assert Decimal(fuera["total_comprobantes"]) == Decimal("0.00")
    assert fuera["coinciden"] is True


def test_el_listado_filtra_y_no_esconde_los_anulados(cliente, datos, sesion):
    a = orden(cliente, datos, "100.00")
    b = orden(cliente, datos, "200.00")
    uno = facturado_a_mano(sesion, datos, [a], numero=1)
    facturado_a_mano(sesion, datos, [b], numero=2, punto_venta=2)
    cliente.delete(f"/api/comprobantes/{uno.id}")

    assert len(cliente.get("/api/comprobantes").json()) == 2
    assert len(cliente.get("/api/comprobantes?anulado=true").json()) == 1
    assert len(cliente.get("/api/comprobantes?anulado=false").json()) == 1
    por_cliente = cliente.get(f"/api/comprobantes?cliente_id={datos['otro_cliente']}").json()
    assert por_cliente == []


def test_sin_sesion_no_se_ven_los_comprobantes(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/comprobantes").status_code == 401
        assert anonimo.get("/api/comprobantes/totales").status_code == 401
        # Las pre facturas (de donde sale ahora todo comprobante) tienen el mismo gate.
        assert anonimo.get("/api/pre-facturas").status_code == 401
        assert anonimo.post("/api/pre-facturas", json={}).status_code == 401
        assert anonimo.post("/api/pre-facturas/1/facturar").status_code == 401
    finally:
        vaciar_auth(engine)


def test_el_iva_del_comprobante_es_la_suma_del_de_cada_orden(cliente, datos):
    """Sumar los IVA ya redondeados no da lo mismo que recalcular sobre el neto.

    Estas dos tarifas están elegidas para que se note: `10.03 * 21%` es
    `2.1063`, que redondea a `2.11`, y dos veces eso son **4.22**. Aplicar la
    alícuota sobre el neto total —`20.06 * 21%` es `4.2126`— da **4.21**. Un
    centavo, sobre las 4.337 órdenes del legado y repetido en cada comprobante,
    es la clase de diferencia que después nadie puede explicar.

    Sumar lo que ya está guardado hace que el comprobante sea exactamente el de
    sus órdenes, que es lo que el gate de la fase compara.
    """
    a = orden(cliente, datos, "10.03")
    b = orden(cliente, datos, "10.03")
    comp = facturar(cliente, datos, [a, b]).json()

    assert Decimal(comp["neto"]) == Decimal("20.06")
    assert Decimal(comp["iva"]) == Decimal("4.22")
    # El otro camino, escrito: si el servidor recalculara sobre el neto, este
    # test seria rojo por un centavo.
    otro_camino = (Decimal("20.06") * Decimal("21") / Decimal(100)).quantize(Decimal("0.01"))
    assert otro_camino == Decimal("4.21")
    assert Decimal(comp["iva"]) != otro_camino
    assert Decimal(comp["total"]) == Decimal("24.28")
    # Y el gate no marca alarma: los dos lados suman lo mismo por construccion.
    assert cliente.get(f"/api/comprobantes/{comp['id']}").json()["coinciden"] is True


def test_una_orden_migrada_con_origen_igual_a_destino_se_puede_leer(cliente, datos, sesion):
    """🔴 La regla de entrada no puede rechazar lo que **ya está guardado**.

    `OrdenOut` heredaba de `OrdenIn`, y con la herencia se llevaba su validador.
    Sobre los datos de Suitrans —33 órdenes que salen y llegan a la misma
    localidad, legítimas y admitidas por el `CHECK` desde ADR-015— el listado
    devolvía **500**, y sólo con un límite chico parecía andar, porque esas filas
    no entraban en la página.

    La fila se inserta por SQL con `origen_legado`, que es exactamente como
    entra por la migración; la API no la deja crear, y eso lo prueba el control
    de abajo.
    """
    a = orden(cliente, datos, "1000.00")
    sesion.execute(text(
        "UPDATE ordenes_carga SET destino_id = origen_id, origen_legado = 'carga:99' "
        "WHERE id = :id"), {"id": a["id"]})
    sesion.commit()

    listado = cliente.get("/api/ordenes")
    assert listado.status_code == 200, listado.text[:300]
    assert [o["id"] for o in listado.json()] == [a["id"]]
    assert cliente.get(f"/api/ordenes/{a['id']}").status_code == 200

    # Control: por la API sigue sin poder crearse una así.
    rechazada = cliente.post("/api/ordenes", json={
        "fecha": "2026-08-10", "cliente_id": datos["cliente"],
        "origen_id": datos["origen"], "destino_id": datos["origen"], "tarifa": "100.00"})
    assert rechazada.status_code == 422
    assert "origen y el destino" in rechazada.text
