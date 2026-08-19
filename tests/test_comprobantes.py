"""Comprobantes y facturar pendientes.

El criterio de F5 en el ROADMAP es que **los totales por razón social sean
reproducibles**, y eso es lo que más se prueba acá: el mismo importe contado por
los encabezados de los comprobantes y por las órdenes que agrupan.

> 🔑 **Cada alarma se prueba con su control.** Que el gate diga "coinciden" no
> significa nada si no se muestra que sabe decir lo contrario: por eso los tests
> del gate tuercen un dato **en la base** —simulando lo que va a llegar de la
> migración de F6— y verifican que ahí sí avisa.
"""

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from sqlalchemy import text

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"


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


def _crear(c, ruta, datos):
    r = c.post(ruta, json=datos)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def datos(cliente):
    """Los maestros mínimos para que una orden exista."""
    return {
        "cliente": _crear(cliente, "/api/terceros",
                          {"razon_social": "Agro Norte", "es_cliente": True}),
        "otro_cliente": _crear(cliente, "/api/terceros",
                               {"razon_social": "Molino Sur", "es_cliente": True}),
        "origen": _crear(cliente, "/api/localidades", {"nombre": "Suipacha"}),
        "destino": _crear(cliente, "/api/localidades", {"nombre": "Rosario"}),
        "razon": _crear(cliente, "/api/razones-sociales", {"nombre": "Suitrans"}),
        "otra_razon": _crear(cliente, "/api/razones-sociales", {"nombre": "Mauricio"}),
    }


def orden(cliente, datos, tarifa, *, cliente_id=None, razon_social_id=None, fecha="2026-08-10"):
    cuerpo = {
        "fecha": fecha,
        "cliente_id": cliente_id or datos["cliente"],
        "origen_id": datos["origen"], "destino_id": datos["destino"],
        "tarifa": tarifa,
    }
    if razon_social_id is not None:
        cuerpo["razon_social_id"] = razon_social_id
    r = cliente.post("/api/ordenes", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def facturar(cliente, datos, ordenes, *, numero=1, razon=None, tipo="factura_a",
             cliente_id=None, punto_venta=1, fecha="2026-08-15"):
    return cliente.post("/api/comprobantes", json={
        "fecha": fecha, "razon_social_id": razon or datos["razon"],
        "cliente_id": cliente_id or datos["cliente"], "tipo": tipo,
        "punto_venta": punto_venta, "numero": numero,
        "orden_ids": [o["id"] if isinstance(o, dict) else o for o in ordenes],
    })


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
        # La orden hereda la razon social del comprobante: es la columna por la
        # que despues suma el lado de las ordenes en el gate de totales.
        assert actual["razon_social_id"] == datos["razon"]

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


def test_los_totales_por_razon_social_dan_igual_por_los_dos_lados(cliente, datos):
    """El gate de F5, sobre dos razones sociales a la vez."""
    a = orden(cliente, datos, "1000.00")
    b = orden(cliente, datos, "2000.00")
    c = orden(cliente, datos, "500.00")
    assert facturar(cliente, datos, [a, b], numero=1).status_code == 201
    assert facturar(cliente, datos, [c], numero=1, razon=datos["otra_razon"]).status_code == 201

    filas = {f["razon_social_id"]: f for f in cliente.get("/api/comprobantes/totales").json()}
    assert set(filas) == {datos["razon"], datos["otra_razon"]}

    suitrans = filas[datos["razon"]]
    assert suitrans["coinciden"] is True
    assert Decimal(suitrans["neto_comprobantes"]) == Decimal("3000.00")
    assert Decimal(suitrans["neto_ordenes"]) == Decimal("3000.00")
    assert suitrans["cantidad_comprobantes"] == 1
    assert suitrans["cantidad_ordenes"] == 2

    mauricio = filas[datos["otra_razon"]]
    assert mauricio["coinciden"] is True
    assert Decimal(mauricio["neto_comprobantes"]) == Decimal("500.00")


def test_el_gate_avisa_cuando_la_orden_quedo_en_otra_razon_social(cliente, datos, sesion):
    """El control de la alarma: sin esto, "coinciden" no significaría nada.

    Se tuerce la razón social **de la orden** por SQL directo, que es lo que va a
    llegar de la migración de F6: en el legado `carga_razonsocial` y
    `factura_razonsocial` son dos enteros sueltos, sin tabla ni clave foránea
    que los obligue a decir lo mismo. La API no deja hacerlo — por eso el
    sabotaje va por debajo.
    """
    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a]).status_code == 201
    assert all(f["coinciden"] for f in cliente.get("/api/comprobantes/totales").json())

    sesion.execute(text("UPDATE ordenes_carga SET razon_social_id = :otra WHERE id = :id"),
                   {"otra": datos["otra_razon"], "id": a["id"]})
    sesion.commit()

    filas = {f["razon_social_id"]: f for f in cliente.get("/api/comprobantes/totales").json()}
    # El comprobante sigue en Suitrans y la orden se fue a Mauricio: las dos
    # filas tienen que avisar, y la razon social que sólo aparece de un lado
    # tiene que aparecer igual.
    assert filas[datos["razon"]]["coinciden"] is False
    assert Decimal(filas[datos["razon"]]["total_ordenes"]) == Decimal("0.00")
    assert filas[datos["otra_razon"]]["coinciden"] is False
    assert filas[datos["otra_razon"]]["cantidad_comprobantes"] == 0
    assert Decimal(filas[datos["otra_razon"]]["neto_ordenes"]) == Decimal("1000.00")


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
    assert facturar(cliente, datos, [a], numero=1).status_code == 201

    r = facturar(cliente, datos, [a, b], numero=2)
    assert r.status_code == 409
    assert str(a["id"]) in r.text
    # Y no quedo nada a medias: ni el comprobante nuevo ni la orden que sí
    # estaba pendiente.
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert cliente.get(f"/api/ordenes/{b['id']}").json()["estado"] == "pendiente"


def test_las_ordenes_repetidas_no_duplican_el_importe(cliente, datos):
    """El `IN` la trae una vez: sin el chequeo, el pedido pasaría con otro total."""
    a = orden(cliente, datos, "1000.00")
    r = cliente.post("/api/comprobantes", json={
        "fecha": "2026-08-15", "razon_social_id": datos["razon"],
        "cliente_id": datos["cliente"], "tipo": "factura_a",
        "punto_venta": 1, "numero": 1, "orden_ids": [a["id"], a["id"]],
    })
    assert r.status_code == 422
    assert "repetida" in r.text


def test_el_numero_es_unico_por_razon_social_tipo_y_punto_de_venta(cliente, datos):
    """El legado numeraba por `(numero, razon_social)`: sin tipo ni punto de venta."""
    a = orden(cliente, datos, "100.00")
    b = orden(cliente, datos, "200.00")
    c = orden(cliente, datos, "300.00")
    assert facturar(cliente, datos, [a], numero=7).status_code == 201

    repetido = facturar(cliente, datos, [b], numero=7)
    assert repetido.status_code == 409
    assert "uq_comprobantes_numeracion" in repetido.text
    # La orden que iba en el comprobante rechazado sigue pendiente.
    assert cliente.get(f"/api/ordenes/{b['id']}").json()["estado"] == "pendiente"

    # El mismo número en OTRA razón social sí entra: son dos talonarios.
    assert facturar(cliente, datos, [b], numero=7, razon=datos["otra_razon"]).status_code == 201
    # Y el mismo número en otro punto de venta, también.
    assert facturar(cliente, datos, [c], numero=7, punto_venta=2).status_code == 201


def test_un_comprobante_es_de_un_solo_cliente(cliente, datos):
    a = orden(cliente, datos, "100.00")
    ajena = orden(cliente, datos, "200.00", cliente_id=datos["otro_cliente"])
    r = facturar(cliente, datos, [a, ajena])
    assert r.status_code == 422
    assert cliente.get("/api/comprobantes").json() == []


def test_no_se_factura_una_orden_de_otra_razon_social(cliente, datos):
    """Pisarla en silencio movería plata de una razón social a la otra."""
    a = orden(cliente, datos, "100.00", razon_social_id=datos["otra_razon"])
    r = facturar(cliente, datos, [a])
    assert r.status_code == 422
    assert "razon social" in r.text


def test_una_nota_de_credito_no_se_registra_sobre_ordenes(cliente, datos):
    a = orden(cliente, datos, "100.00")
    r = facturar(cliente, datos, [a], tipo="nota_credito_a")
    assert r.status_code == 422


def test_no_se_factura_una_orden_que_no_existe(cliente, datos):
    r = facturar(cliente, datos, [9999])
    assert r.status_code == 404
    assert "9999" in r.text


def test_anular_devuelve_las_ordenes_y_revierte_la_cuenta(cliente, datos):
    """La reversión es un asiento nuevo: la cuenta corriente no se reescribe."""
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a]).json()

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
    assert cliente.get("/api/comprobantes/totales").json() == []
    # Y el detalle no marca alarma por quedarse sin órdenes: lo que chequea un
    # anulado es que no le haya quedado ninguna colgada.
    detalle = cliente.get(f"/api/comprobantes/{comp['id']}").json()
    assert detalle["ordenes"] == []
    assert detalle["coinciden"] is True

    # Y la orden se puede volver a facturar.
    assert facturar(cliente, datos, [a], numero=2).status_code == 201


def test_un_comprobante_anulado_no_se_anula_dos_veces(cliente, datos):
    a = orden(cliente, datos, "100.00")
    comp = facturar(cliente, datos, [a]).json()
    assert cliente.delete(f"/api/comprobantes/{comp['id']}").status_code == 200
    assert cliente.delete(f"/api/comprobantes/{comp['id']}").status_code == 409
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
    assert len(dentro) == 1
    assert dentro[0]["coinciden"] is True
    assert Decimal(dentro[0]["neto_ordenes"]) == Decimal("1000.00")

    assert cliente.get("/api/comprobantes/totales?desde=2026-09-01").json() == []


def test_el_listado_filtra_y_no_esconde_los_anulados(cliente, datos):
    a = orden(cliente, datos, "100.00")
    b = orden(cliente, datos, "200.00")
    uno = facturar(cliente, datos, [a], numero=1).json()
    facturar(cliente, datos, [b], numero=2, razon=datos["otra_razon"])
    cliente.delete(f"/api/comprobantes/{uno['id']}")

    assert len(cliente.get("/api/comprobantes").json()) == 2
    assert len(cliente.get("/api/comprobantes?anulado=true").json()) == 1
    assert len(cliente.get("/api/comprobantes?anulado=false").json()) == 1
    por_razon = cliente.get(f"/api/comprobantes?razon_social_id={datos['otra_razon']}").json()
    assert [c["numero"] for c in por_razon] == [2]


def test_sin_sesion_no_se_ven_los_comprobantes(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/comprobantes").status_code == 401
        assert anonimo.get("/api/comprobantes/totales").status_code == 401
        assert anonimo.post("/api/comprobantes", json={}).status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)


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
