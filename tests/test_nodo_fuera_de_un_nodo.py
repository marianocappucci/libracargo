"""Fuera de un nodo, y en una instancia sin nodo vinculado, nada cambia (ADR-056).

Suitrans (cliente real, ≈4.300 órdenes) opera hoy en la web, sin nodo. Todo lo que suma el nodo —el outbox, los ids
provisorios, los 409 `solo_en_el_nodo`, la cola de ARCA— tiene que comportarse ahí **exactamente como antes**. Cada
test de acá es un camino que esa instancia usa todos los días: cargar una orden, anotar un cobro, facturar. Y el
control negativo de cada uno: con un nodo vinculado el mismo pedido sí cambia (`test_nodo_solo_en_el_nodo.py`).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from libracore.cola_arca import FueraDeUnNodo, arrancar_cola_al_volver, encolar, procesar_cola
from libracore.db import core
from libracore.ganchos_de_caja import SIN_GANCHOS
from libraedge import aprovisionamiento as aprov

from app import offline
from app.servicios import subida

# Todos arrancan con la empresa lista para emitir por ARCA (simulada): ver `emisor` en el conftest.
pytestmark = pytest.mark.con_emisor


@pytest.fixture(autouse=True)
def _sin_identidad_de_nodo(monkeypatch):
    """Una instancia común, como Suitrans: ninguna variable de LibraEdge."""
    for variable in ("LIBRAEDGE_NODE_ID", "LIBRACARGO_EDGE_NODE_ID", "LIBRAEDGE_PREFIJO", "LIBRAEDGE_ESTADO",
                     "LIBRAEDGE_CENTRAL_URL", "LIBRAEDGE_NODE_SECRET"):
        monkeypatch.delenv(variable, raising=False)


def cuantas(tabla: str) -> int:
    with core.get_connection() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0])


def nada_encolado():
    for tabla in ("sync_outbox", "local_sequences", "libraedge_mapeo", "node_identity", "cola_arca"):
        assert cuantas(tabla) == 0, f"fuera de un nodo no se escribe nada en {tabla}"


def test_la_instancia_no_es_un_nodo_ni_tiene_un_nodo_vinculado(cliente):
    assert offline.nodo() is None
    assert offline.hay_nodo_vinculado() is False
    assert offline.CONEXION.es_nodo() is False
    assert offline.CONEXION.sin_conexion() is False, "fuera de un nodo nunca está «sin conexión»"


def test_cargar_una_orden_y_anotar_un_cobro_es_como_siempre(cliente, datos):
    r = cliente.post("/api/ordenes", json={
        "fecha": "2026-10-20", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00"})
    assert r.status_code == 201, r.text
    assert r.json()["id"] > 0, "el id es el de la secuencia: ninguno provisorio fuera de un nodo"
    c = cliente.post("/api/caja", json={
        "fecha": "2026-10-21", "tipo": "ingreso", "concepto": "Cobro", "importe": "500.00",
        "tercero_id": datos["cliente"], "rol": "cliente", "descripcion": "Cheque", "recibo": "0001-1"})
    assert c.status_code == 201, c.text
    corregido = cliente.put(f"/api/caja/{c.json()['id']}", json={
        "fecha": "2026-10-21", "tipo": "ingreso", "concepto": "Cobro corregido", "importe": "600.00",
        "tercero_id": datos["cliente"], "rol": "cliente"})
    assert corregido.status_code == 200, "corregir sigue siendo posible en el central"
    assert cliente.delete(f"/api/caja/{c.json()['id']}").status_code == 200
    nada_encolado()


def test_un_gasto_y_un_tercero_nuevo_son_como_siempre(cliente, datos):
    nuevo = cliente.post("/api/terceros", json={"razon_social": "Gomería Norte", "es_proveedor": True})
    assert nuevo.status_code == 201 and nuevo.json()["id"] > 0
    fletero = cliente.post("/api/terceros", json={"razon_social": "Fletes del Sur", "es_fletero": True}).json()["id"]
    g = cliente.post("/api/gastos", json={
        "fecha": "2026-10-22", "proveedor_id": nuevo.json()["id"], "fletero_id": fletero, "descripcion": "Cubiertas",
        "importe": "800.00"})
    assert g.status_code == 201 and g.json()["id"] > 0
    nada_encolado()


def test_facturar_sale_por_arca_como_siempre_y_no_pasa_por_la_cola(cliente, datos, emisor):
    o = cliente.post("/api/ordenes", json={
        "fecha": "2026-10-20", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00"}).json()
    r = cliente.post("/api/comprobantes/desde-ordenes", json={
        "fecha": "2026-10-20", "cliente_id": datos["cliente"], "tipo": "factura_a", "orden_ids": [o["id"]]})
    assert r.status_code == 201, r.text
    assert r.json()["cae"] == "75123456789012", "CAE en el momento, con el certificado de la instancia"
    nada_encolado()


def test_los_oyentes_del_nodo_no_hacen_nada_fuera_de_un_nodo(cliente, sesion):
    subida.tocar(sesion, "orden", 1)
    assert subida.CLAVE not in sesion.info
    with pytest.raises(RuntimeError, match="no es un nodo"):
        offline.encolar_operacion(None, "cargo.orden", "orden", 1, {})
    # Los ganchos de caja se arman igual en las dos puntas y fuera de un nodo no encolan (no hay a quién subirle).
    offline.GANCHOS_DE_CAJA.al_registrar_movimiento(None, {"movimiento_id": 1})
    offline.GANCHOS_DE_CAJA.al_anular_movimiento(None, {"movimiento_id": 1})
    assert offline.GANCHOS_DE_CAJA.al_abrir_turno is SIN_GANCHOS.al_abrir_turno


def test_la_cola_de_arca_se_rehusa_y_no_arranca_fuera_de_un_nodo(cliente):
    import asyncio

    cola = offline.cola()
    with pytest.raises(FueraDeUnNodo):
        encolar(cola, "cpe", "orden-1", datos={})
    assert arrancar_cola_al_volver(cola) is None and offline.arrancar_cola() is None
    assert asyncio.run(procesar_cola(cola))["es_nodo"] is False


def test_un_nodo_registrado_no_cambia_a_la_instancia_que_no_es_el_nodo_pero_si_tiene_uno_vinculado(cliente, datos):
    """El control negativo: el mismo pedido de arriba cambia en cuanto hay un nodo vinculado."""
    with core.get_connection() as conn:
        aprov.registrar(conn, offline.aprovisionamiento, "oficina-1", sucursal="1")
    assert offline.hay_nodo_vinculado() is True
    r = cliente.post("/api/ordenes", json={
        "fecha": "2026-10-20", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_nodo"
    assert Decimal("0") == Decimal(cuantas("ordenes_carga"))
