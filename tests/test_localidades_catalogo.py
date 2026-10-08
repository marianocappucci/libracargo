"""Localidades vinculadas al catálogo de LibraCore y parajes como excepción (ADR-041).

Medido en Suitrans (2026-10-08): 120 localidades, 92 coinciden con una sola del catálogo; las 28 restantes
son partidos, abreviaturas, parajes y nombres del legado («Campo», «Shap»).
"""

from __future__ import annotations

SUIPACHA = "06784020"


def _orden(cliente, origen, destino, clientes_id):
    r = cliente.post("/api/ordenes", json={"fecha": "2026-10-08", "cliente_id": clientes_id,
                                           "origen_id": origen, "destino_id": destino, "tarifa": "100.00"})
    assert r.status_code == 201, r.text
    return r.json()


def test_buscar_trae_el_maestro_y_el_catalogo(cliente, datos):
    """`datos` ya tiene «Suipacha» en el maestro, sin vincular."""
    r = cliente.get("/api/localidades/buscar/combinado", params={"q": "suipa"}).json()
    assert [x["nombre"] for x in r["maestro"]] == ["Suipacha"]
    assert any(c["id"] == SUIPACHA and c["provincia"] == "Buenos Aires" for c in r["catalogo"])


def test_traer_del_catalogo_crea_vincula_o_devuelve_la_que_esta(cliente, datos):
    nueva = cliente.post("/api/localidades/desde-catalogo", json={"catalogo_id": "06588030"})  # 12 de Octubre
    assert nueva.status_code == 201, nueva.text
    assert (nueva.json()["nombre"], nueva.json()["provincia"], nueva.json()["catalogo_id"]) == (
        "12 de Octubre", "Buenos Aires", "06588030")
    otra_vez = cliente.post("/api/localidades/desde-catalogo", json={"catalogo_id": "06588030"})
    assert otra_vez.status_code == 200 and otra_vez.json()["id"] == nueva.json()["id"]
    # «Suipacha» del maestro (sin provincia) no es «la misma» hasta tener provincia: se crea otra vinculada.
    cliente.put(f"/api/localidades/{datos['origen']}", json={"nombre": "Suipacha", "provincia": "Buenos Aires"})
    vinculada = cliente.post("/api/localidades/desde-catalogo", json={"catalogo_id": SUIPACHA}).json()
    assert vinculada["id"] == datos["origen"] and vinculada["catalogo_id"] == SUIPACHA, "vinculó la que había"
    assert cliente.post("/api/localidades/desde-catalogo", json={"catalogo_id": "99999999"}).status_code == 404


def test_el_mismo_nombre_en_dos_provincias_son_dos_localidades(cliente):
    a = cliente.post("/api/localidades", json={"nombre": "San Pedro", "provincia": "Buenos Aires"})
    b = cliente.post("/api/localidades", json={"nombre": "San Pedro", "provincia": "Jujuy"})
    assert (a.status_code, b.status_code) == (201, 201)
    assert cliente.post("/api/localidades", json={"nombre": "San Pedro", "provincia": "Jujuy"}).status_code == 409


def test_un_paraje_se_carga_a_mano_con_provincia(cliente):
    r = cliente.post("/api/localidades", json={"nombre": "Tomás Jofré", "es_paraje": True})
    assert r.status_code == 422 and "provincia" in r.text
    r = cliente.post("/api/localidades", json={"nombre": "Tomás Jofré", "provincia": "Buenos Aires",
                                               "es_paraje": True})
    assert r.status_code == 201 and (r.json()["es_paraje"], r.json()["catalogo_id"]) == (True, None)


def test_vincular_una_existente_y_no_dos_veces_la_misma(cliente, datos):
    r = cliente.post(f"/api/localidades/{datos['origen']}/vincular", json={"catalogo_id": SUIPACHA})
    assert r.status_code == 200 and (r.json()["catalogo_id"], r.json()["provincia"]) == (SUIPACHA, "Buenos Aires")
    otra = cliente.post("/api/localidades", json={"nombre": "Suipacha (ruta 5)", "provincia": "Buenos Aires"}).json()
    r = cliente.post(f"/api/localidades/{otra['id']}/vincular", json={"catalogo_id": SUIPACHA})
    assert r.status_code == 409 and "unificalas" in r.json()["detail"]


def test_unificar_mueve_las_ordenes_y_da_de_baja(cliente, datos):
    dup = cliente.post("/api/localidades", json={"nombre": "Pto San Martin", "provincia": "Santa Fe"}).json()
    buena = cliente.post("/api/localidades", json={"nombre": "Pto. San Martín", "provincia": "Santa Fe"}).json()
    o1 = _orden(cliente, dup["id"], datos["destino"], datos["cliente"])
    o2 = _orden(cliente, datos["origen"], dup["id"], datos["cliente"])
    r = cliente.post(f"/api/localidades/{dup['id']}/unificar", json={"en_id": buena["id"]})
    assert r.status_code == 200, r.text
    assert cliente.get(f"/api/ordenes/{o1['id']}").json()["origen_id"] == buena["id"]
    assert cliente.get(f"/api/ordenes/{o2['id']}").json()["destino_id"] == buena["id"]
    assert cliente.get(f"/api/localidades/{dup['id']}").json()["activo"] is False
    assert cliente.post(f"/api/localidades/{buena['id']}/unificar", json={"en_id": buena["id"]}).status_code == 422
    asiento = cliente.get("/api/auditoria?entidad=localidades").json()["registros"][0]
    assert asiento["datos_despues"]["ordenes_movidas"] == 2


# ── El resto del Mercosur (ADR-042) ────────────────────────────────────────

def test_el_buscador_trae_el_mercosur_despues_de_argentina(cliente):
    r = cliente.get("/api/localidades/buscar/combinado", params={"q": "nueva palmira"}).json()
    assert [(c["nombre"], c["provincia"], c["pais"]) for c in r["catalogo"]] == [("Nueva Palmira", "Colonia", "UY")]
    nueva = cliente.post("/api/localidades/desde-catalogo", json={"catalogo_id": r["catalogo"][0]["id"]})
    assert nueva.status_code == 201, nueva.text
    assert (nueva.json()["nombre"], nueva.json()["provincia"], nueva.json()["pais"]) == (
        "Nueva Palmira", "Colonia", "UY")
    sa = cliente.get("/api/localidades/buscar/combinado", params={"q": "san"}).json()["catalogo"]
    paises = [c["pais"] for c in sa]
    assert paises[0] == "AR" and paises == sorted(paises, key=lambda p: p != "AR")


def test_un_paraje_de_afuera(cliente):
    r = cliente.post("/api/localidades", json={"nombre": "Terminal TGU", "provincia": "Colonia", "pais": "UY",
                                               "es_paraje": True})
    assert r.status_code == 201 and r.json()["pais"] == "UY"
    assert cliente.post("/api/localidades", json={"nombre": "X", "pais": "uruguay"}).status_code == 422
    # El mismo nombre y provincia en otro país es otro lugar.
    assert cliente.post("/api/localidades", json={"nombre": "Terminal TGU", "provincia": "Colonia",
                                                  "es_paraje": True}).status_code == 201
