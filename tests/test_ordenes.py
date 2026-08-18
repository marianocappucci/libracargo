"""Las órdenes de carga. El criterio de F3 es que los once listados del legado
sean uno solo con filtros, así que eso es lo que más se prueba acá.
"""

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

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


@pytest.fixture
def maestros(cliente):
    """Los maestros mínimos para poder dar de alta una orden.

    Se crean **por la API**, no insertando filas: si el alta de un maestro se
    rompiera, estos tests tienen que enterarse en vez de seguir andando sobre
    datos que la aplicación ya no sabe producir.
    """
    def alta(recurso, cuerpo):
        r = cliente.post(f"/api/{recurso}", json=cuerpo)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {
        "cliente": alta("terceros", {"razon_social": "Agro Norte", "es_cliente": True}),
        "cliente2": alta("terceros", {"razon_social": "Otro Cliente", "es_cliente": True}),
        "fletero": alta("terceros", {"razon_social": "Fletes SRL", "es_fletero": True}),
        "origen": alta("localidades", {"nombre": "Suipacha"}),
        "destino": alta("localidades", {"nombre": "Chivilcoy"}),
        "chofer": alta("choferes", {"nombre": "Juan Perez"}),
        "vehiculo": alta("vehiculos", {"patente_chasis": "AB123CD"}),
        "tipo": alta("tipos-carga", {"nombre": "Cereal"}),
    }


def orden_minima(m, **extra):
    base = {
        "fecha": "2026-08-18",
        "cliente_id": m["cliente"],
        "origen_id": m["origen"],
        "destino_id": m["destino"],
        "tarifa": "1000.00",
    }
    base.update(extra)
    return base


def test_el_alta_calcula_iva_y_total(cliente, maestros):
    """Los importes los calcula el SERVIDOR.

    En el legado la alícuota estaba fija en el JavaScript de la pantalla, así
    que el total llegaba ya calculado por el cliente: un importe equivocado era
    un pedido válido.
    """
    r = cliente.post("/api/ordenes", json=orden_minima(maestros))
    assert r.status_code == 201, r.text
    o = r.json()
    assert Decimal(o["iva"]) == Decimal("210.00")
    assert Decimal(o["total"]) == Decimal("1210.00")
    assert o["estado"] == "pendiente"
    assert o["comprobante_id"] is None


def test_lo_que_manda_el_cliente_como_total_se_ignora(cliente, maestros):
    """El control del test de arriba: si el cuerpo pudiera fijar el total,
    calcularlo bien en el camino feliz no probaría nada."""
    r = cliente.post("/api/ordenes",
                     json=orden_minima(maestros, iva="0.01", total="1.00"))
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["total"]) == Decimal("1210.00")


def test_la_alicuota_no_esta_fija_en_21(cliente, maestros):
    """El relevamiento con el cliente sobre otras alícuotas sigue abierto, y el
    legado las tenía fijas en el JavaScript."""
    r = cliente.post("/api/ordenes", json=orden_minima(maestros, alicuota_iva="10.5"))
    assert Decimal(r.json()["iva"]) == Decimal("105.00")


def test_el_origen_no_puede_ser_el_destino(cliente, maestros):
    """La base también lo impide, pero como 500 con el nombre de un CHECK."""
    r = cliente.post("/api/ordenes",
                     json=orden_minima(maestros, destino_id=maestros["origen"]))
    assert r.status_code == 422
    assert "origen y el destino" in r.text


def test_un_solo_listado_resuelve_los_filtros_del_legado(cliente, maestros):
    """El criterio de F3: once pantallas del legado, un endpoint.

    Se cargan tres órdenes que se distinguen en un solo campo cada una, y se
    pide cada filtro por separado. Si alguno mirara la columna equivocada,
    devolvería las tres.
    """
    m = maestros
    a = cliente.post("/api/ordenes", json=orden_minima(m, fecha="2026-08-01",
                                                       remito="R-100")).json()
    b = cliente.post("/api/ordenes", json=orden_minima(
        m, fecha="2026-08-15", cliente_id=m["cliente2"], fletero_id=m["fletero"])).json()
    c = cliente.post("/api/ordenes", json=orden_minima(
        m, fecha="2026-08-30", chofer_id=m["chofer"], vehiculo_id=m["vehiculo"],
        tipo_carga_id=m["tipo"], observaciones="carga delicada")).json()

    def ids(consulta):
        r = cliente.get(f"/api/ordenes?{consulta}")
        assert r.status_code == 200, r.text
        return {x["id"] for x in r.json()}

    assert ids("") == {a["id"], b["id"], c["id"]}
    assert ids(f"cliente_id={m['cliente2']}") == {b["id"]}
    assert ids(f"fletero_id={m['fletero']}") == {b["id"]}
    assert ids(f"chofer_id={m['chofer']}") == {c["id"]}
    assert ids(f"vehiculo_id={m['vehiculo']}") == {c["id"]}
    assert ids(f"tipo_carga_id={m['tipo']}") == {c["id"]}
    assert ids("q=R-100") == {a["id"]}
    assert ids("q=delicada") == {c["id"]}
    assert ids("desde=2026-08-10") == {b["id"], c["id"]}
    assert ids("hasta=2026-08-10") == {a["id"]}
    assert ids("desde=2026-08-10&hasta=2026-08-20") == {b["id"]}
    assert ids("estado=pendiente") == {a["id"], b["id"], c["id"]}
    # Y los filtros se COMBINAN, que es lo que en el legado obligaba a una
    # pantalla nueva por cada par.
    assert ids(f"desde=2026-08-10&cliente_id={m['cliente2']}") == {b["id"]}
    assert ids(f"desde=2026-08-20&cliente_id={m['cliente2']}") == set()


def test_el_filtro_de_facturadas_distingue_las_tres_respuestas(cliente, maestros):
    """`facturada` sin valor es *las dos*, y es distinto de `false`.

    En el legado "facturar pendientes" era una pantalla propia.
    """
    o = cliente.post("/api/ordenes", json=orden_minima(maestros)).json()
    assert {x["id"] for x in cliente.get("/api/ordenes?facturada=false").json()} == {o["id"]}
    assert cliente.get("/api/ordenes?facturada=true").json() == []
    assert {x["id"] for x in cliente.get("/api/ordenes").json()} == {o["id"]}


def test_el_orden_es_estable_entre_consultas(cliente, maestros):
    """Dos órdenes del mismo día sin desempate salen en un orden que la base
    puede cambiar, y una lista que se reordena sola no se puede revisar."""
    ids = [cliente.post("/api/ordenes", json=orden_minima(maestros)).json()["id"]
           for _ in range(4)]
    primera = [x["id"] for x in cliente.get("/api/ordenes").json()]
    assert primera == sorted(ids, reverse=True)
    assert primera == [x["id"] for x in cliente.get("/api/ordenes").json()]


def test_una_orden_anulada_no_se_borra_ni_se_edita(cliente, maestros):
    o = cliente.post("/api/ordenes", json=orden_minima(maestros)).json()
    baja = cliente.delete(f"/api/ordenes/{o['id']}")
    assert baja.status_code == 200
    assert baja.json()["estado"] == "anulada"
    # Sigue existiendo: es la contrapartida de los movimientos de cuenta.
    assert cliente.get(f"/api/ordenes/{o['id']}").status_code == 200
    r = cliente.put(f"/api/ordenes/{o['id']}", json=orden_minima(maestros))
    assert r.status_code == 409
    assert "anulada" in r.text


def test_la_edicion_recalcula_los_importes(cliente, maestros):
    o = cliente.post("/api/ordenes", json=orden_minima(maestros)).json()
    r = cliente.put(f"/api/ordenes/{o['id']}",
                    json=orden_minima(maestros, tarifa="2000.00"))
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["total"]) == Decimal("2420.00")


def test_la_auditoria_de_importes_compara_lo_guardado_con_la_cuenta(cliente, maestros):
    """Sirve para las órdenes migradas, donde el importe viene del `float` del
    legado y no de esta cuenta."""
    o = cliente.post("/api/ordenes", json=orden_minima(maestros)).json()
    a = cliente.get(f"/api/ordenes/{o['id']}/importes").json()
    assert Decimal(a["total_calculado"]) == Decimal(a["total_guardado"])


def test_sin_sesion_no_se_ven_las_ordenes(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/ordenes").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
