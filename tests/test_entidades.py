"""Entidades: una persona o empresa es una sola, con uno o más roles (ADR-040).

Lo medido en Suitrans (2026-10-08): 276 terceros, ninguno con más de un rol, un CUIT cargado dos veces (como
cliente y como fletero) y 68 con un CUIT de relleno («1») del legado.
"""

from __future__ import annotations

CUIT = "30-12345678-1"


def _alta(cliente, **datos):
    return cliente.post("/api/terceros", json={"razon_social": "Agro Prueba SA", **datos})


def test_un_cuit_que_ya_existe_no_se_vuelve_a_dar_de_alta(cliente):
    fletero = _alta(cliente, cuit=CUIT, es_fletero=True).json()
    r = _alta(cliente, razon_social="Agro Prueba", cuit="30123456781", es_cliente=True)
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["existente"] == {"id": fletero["id"], "razon_social": "Agro Prueba SA", "roles": ["fletero"],
                                    "activo": True}
    assert "Sumale el rol" in detalle["mensaje"]
    assert len(cliente.get("/api/terceros", params={"q": "Agro Prueba"}).json()) == 1


def test_sumarle_el_rol_a_la_que_existe(cliente):
    fletero = _alta(cliente, cuit=CUIT, es_fletero=True).json()
    r = cliente.post(f"/api/terceros/{fletero['id']}/roles/cliente")
    assert r.status_code == 200, r.text
    t = r.json()
    assert (t["es_fletero"], t["es_cliente"], t["es_proveedor"]) == (True, True, False)
    assert [x["id"] for x in cliente.get("/api/terceros/rol/cliente").json()] == [fletero["id"]]
    assert [x["id"] for x in cliente.get("/api/terceros/rol/fletero").json()] == [fletero["id"]]
    asiento = cliente.get("/api/auditoria?entidad=terceros").json()["registros"][0]
    assert asiento["datos_despues"]["es_cliente"] is True


def test_sumar_un_rol_reactiva_y_rechaza_un_rol_inventado(cliente):
    t = _alta(cliente, cuit=CUIT, es_proveedor=True).json()
    cliente.delete(f"/api/terceros/{t['id']}")
    assert cliente.post(f"/api/terceros/{t['id']}/roles/fletero").json()["activo"] is True
    assert cliente.post(f"/api/terceros/{t['id']}/roles/socio").status_code == 404
    assert cliente.post("/api/terceros/99999/roles/cliente").status_code == 404


def test_editar_hacia_un_cuit_ajeno_tambien_choca(cliente):
    _alta(cliente, cuit=CUIT, es_fletero=True)
    otra = _alta(cliente, razon_social="Otra SRL", cuit="20-12345678-6", es_cliente=True).json()
    r = cliente.put(f"/api/terceros/{otra['id']}", json={"razon_social": "Otra SRL", "cuit": CUIT, "es_cliente": True})
    assert r.status_code == 409
    mismo = cliente.put(f"/api/terceros/{otra['id']}", json={
        "razon_social": "Otra SRL", "cuit": "20-12345678-6", "es_cliente": True, "es_proveedor": True})
    assert mismo.status_code == 200, "su propio CUIT no choca consigo misma"


def test_los_cuit_de_relleno_no_cuentan(cliente, sesion):
    """El legado dejó «1» como CUIT en 68 terceros de Suitrans: no identifican a nadie y no chocan entre sí."""
    from app.models import CondicionIVA, Tercero
    for nombre in ("Legado A", "Legado B"):
        sesion.add(Tercero(razon_social=nombre, cuit="1", condicion_iva=CondicionIVA.CONSUMIDOR_FINAL,
                           es_cliente=True))
    sesion.commit()
    assert _alta(cliente, razon_social="Sin CUIT A", es_cliente=True).status_code == 201
    assert _alta(cliente, razon_social="Sin CUIT B", es_cliente=True).status_code == 201
    assert _alta(cliente, razon_social="Relleno", cuit="1", es_cliente=True).status_code == 201
    assert _alta(cliente, razon_social="Con CUIT", cuit=CUIT, es_cliente=True).status_code == 201


def test_choferes_y_vehiculos_de_un_fletero(cliente):
    a = _alta(cliente, razon_social="Fletero A", cuit=CUIT, es_fletero=True).json()["id"]
    b = _alta(cliente, razon_social="Fletero B", cuit="20-12345678-6", es_fletero=True).json()["id"]
    for nombre, fletero in (("Chofer 1", a), ("Chofer 2", b), ("Chofer 3", a)):
        assert cliente.post("/api/choferes", json={"nombre": nombre, "fletero_id": fletero}).status_code == 201
    for patente, fletero in (("AA123BB", a), ("AC456DD", b)):
        r = cliente.post("/api/vehiculos", json={"patente_chasis": patente, "fletero_id": fletero})
        assert r.status_code == 201
    assert [c["nombre"] for c in cliente.get("/api/choferes", params={"fletero_id": a}).json()] == ["Chofer 1",
                                                                                                    "Chofer 3"]
    assert [v["patente_chasis"] for v in cliente.get("/api/vehiculos", params={"fletero_id": b}).json()] == [
        "AC456DD"]
    assert cliente.get("/api/choferes", params={"fletero_id": "x"}).status_code == 422
    assert len(cliente.get("/api/choferes").json()) == 3, "sin filtro, todos"


def test_el_chofer_se_busca_por_cuit(cliente):
    cliente.post("/api/choferes", json={"nombre": "Alegre", "cuit": "20-12345678-6"})
    assert [c["nombre"] for c in cliente.get("/api/choferes", params={"q": "20123456786"}).json()] == ["Alegre"]
