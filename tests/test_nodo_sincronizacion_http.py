"""La sincronización por HTTP, de punta a punta, contra las rutas reales del central (ADR-056).

Los otros tests aplican las operaciones con el receptor de LibraEdge; acá van por `POST /sync/v1/push` con el secreto
del nodo, para probar el cableado entero: el montaje del router, la autenticación, el control de esquema, el
despachador del producto, el ticket de ARCA que presta el central (con `wsfe` y con `wscpe`) y la carga inicial.
"""
from __future__ import annotations

import pytest

from tests.conftest import arca_responde
from tests.nodo_apoyo import NODO


@pytest.fixture
def cabeceras(escenario):
    from libracore.db import core
    from libraedge.sync.esquema import CABECERA, version_de_alembic

    conn = core.conectar(escenario.url_central)
    try:
        version = version_de_alembic(conn)
    finally:
        conn.close()
    return {"Authorization": f"Bearer {escenario.secreto}", CABECERA: version}


def test_el_push_del_nodo_se_aplica_en_el_central_por_la_ruta_real(escenario, cabeceras):
    o = escenario.cliente.post("/api/ordenes", json={
        "fecha": "2026-10-20", "cliente_id": escenario.datos["cliente"], "origen_id": escenario.datos["origen"],
        "destino_id": escenario.datos["destino"], "tarifa": "1000.00"}).json()
    operaciones = escenario.pendientes()
    assert [op.operation_type for op in operaciones] == ["cargo.orden"]
    with escenario.en_el_central():
        r = escenario.cliente.post("/sync/v1/push", json=operaciones[0].como_dict(), headers=cabeceras)
        assert r.status_code == 200, r.text
        assert r.json()["result"] == "accepted"
        # El mismo push otra vez: el receptor lo deduplica.
        assert escenario.cliente.post("/sync/v1/push", json=operaciones[0].como_dict(),
                                      headers=cabeceras).json()["result"] == "duplicate"
        # Un secreto que no es el del nodo no entra.
        assert escenario.cliente.post("/sync/v1/push", json=operaciones[0].como_dict(),
                                      headers={**cabeceras, "Authorization": "Bearer otro"}).status_code == 401
    assert escenario.sql_central("SELECT COUNT(*) FROM ordenes_carga") == [(1,)]
    assert o["id"] < 0


def test_un_esquema_distinto_no_sincroniza(escenario, cabeceras):
    with escenario.en_el_central():
        r = escenario.cliente.post("/sync/v1/push", json={
            "operation_id": "x:1", "node_id": NODO, "sequence": 1, "operation_type": "cargo.orden",
            "aggregate_type": "orden", "aggregate_id": "x", "occurred_at": "2026-10-24T00:00:00+00:00",
            "schema_version": 1, "payload": {}}, headers={**cabeceras, "X-LibraEdge-Esquema": "alembic_version=viejo"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "esquema_incompatible"


def test_una_operacion_que_el_central_no_conoce_va_a_revision_y_no_se_pierde(escenario, cabeceras):
    with escenario.en_el_central():
        r = escenario.cliente.post("/sync/v1/push", json={
            "operation_id": "x:2", "node_id": NODO, "sequence": 2, "operation_type": "cargo.invento",
            "aggregate_type": "x", "aggregate_id": "x", "occurred_at": "2026-10-24T00:00:00+00:00",
            "schema_version": 1, "payload": {}}, headers=cabeceras)
    assert r.status_code == 200 and r.json()["result"] == "rejected"
    assert "sin manejador para cargo.invento" in r.json()["error"]
    assert escenario.sql_central("SELECT status FROM sync_inbox WHERE operation_id = 'x:2'") == [("manual_review",)]


def test_el_central_le_presta_al_nodo_el_ticket_de_wsfe_y_dice_que_no_tiene_el_de_wscpe(escenario, cabeceras,
                                                                                       monkeypatch):
    arca_responde(monkeypatch)
    with escenario.en_el_central():
        wsfe = escenario.cliente.post("/sync/v1/ticket-arca", json={"node_id": NODO, "servicio": "wsfe"},
                                      headers=cabeceras)
        assert wsfe.status_code == 200, wsfe.text
        assert wsfe.json()["token"] == "TKN" and wsfe.json()["servicio"] == "wsfe"
        # `wscpe` sale del par de `arca_credenciales_servicio` de la empresa de este producto («agencia»): acá no hay
        # ninguno cargado, y el central lo dice (422) en vez de prestar el de facturación con otro nombre.
        wscpe = escenario.cliente.post("/sync/v1/ticket-arca", json={"node_id": NODO, "servicio": "wscpe"},
                                       headers=cabeceras)
        assert wscpe.status_code == 422, wscpe.text
        assert "wscpe" in wscpe.json()["detail"]["mensaje"]


def test_la_carga_inicial_se_sirve_al_nodo_autenticado(escenario, cabeceras):
    with escenario.en_el_central():
        r = escenario.cliente.get("/sync/v1/carga-inicial", params={"node_id": NODO}, headers=cabeceras)
        assert r.status_code == 200, r.text
        assert r.json()["formato"] == "zlib+base64" and "ordenes_carga" in r.json()["conteos"]
        otro = escenario.cliente.get("/sync/v1/carga-inicial", params={"node_id": "otro-nodo"}, headers=cabeceras)
        assert otro.status_code == 401, "con el secreto de un nodo no se pide la carga de otro"
