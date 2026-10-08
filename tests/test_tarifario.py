"""El tarifario de referencia y los km y la tarifa por tonelada de la orden (ADR-038).

El de verdad (10 de abril de 2026) tiene una tarifa por km; en la CPE de Pereiro, 80 km a 19.724,73 $/t es el
85 % de la referencia de 80 km (23.205,57). Acá se usan tablas cortas con esos mismos valores.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

CSV = b"km;tarifa\n1;9.636,69\n10;9.636,69\n11;9.864,21\n80;23.205,57\n100;27.192,78\n"


def _cargar(cliente, contenido=CSV, vigencia="2026-04-10", nombre="Tarifa de referencia abril 2026",
            estadia="214.146,67"):
    datos = {"vigencia": vigencia, "nombre": nombre}
    if estadia is not None:
        datos["valor_estadia"] = estadia
    return cliente.post("/api/tarifario", data=datos, files={"archivo": ("t.csv", contenido, "text/csv")})


def _orden(cliente, datos, **extra):
    r = cliente.post("/api/ordenes", json={
        "fecha": "2026-09-10", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_cargar_el_tarifario(cliente):
    r = _cargar(cliente)
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["vigencia"], t["filas"], t["km_desde"], t["km_hasta"], t["valor_estadia"]) == (
        "2026-04-10", 5, 1, 100, "214146.67")
    assert cliente.get(f"/api/tarifario/{t['id']}/filas").json()[3] == {"km": 80, "tarifa": "23205.57"}
    asiento = cliente.get("/api/auditoria?entidad=tarifario").json()["registros"][0]
    assert (asiento["accion"], asiento["datos_despues"]["filas"]) == ("alta", 5)


def test_cargar_la_misma_vigencia_la_reemplaza_entera(cliente):
    _cargar(cliente)
    r = _cargar(cliente, contenido=b"1,100.50\n2,200.75\n", estadia=None)
    assert r.status_code == 201, r.text
    assert (r.json()["filas"], r.json()["valor_estadia"]) == (2, None)
    assert len(cliente.get("/api/tarifario").json()) == 1
    assert cliente.get(f"/api/tarifario/{r.json()['id']}/filas").json() == [
        {"km": 1, "tarifa": "100.50"}, {"km": 2, "tarifa": "200.75"}]


def test_la_referencia_es_la_del_tarifario_que_regia_en_la_fecha(cliente):
    _cargar(cliente)
    _cargar(cliente, contenido=b"80;30000,00\n", vigencia="2026-10-01", nombre="Octubre")
    vieja = cliente.get("/api/tarifario/referencia", params={"km": 80, "fecha": "2026-09-10"}).json()
    nueva = cliente.get("/api/tarifario/referencia", params={"km": 80, "fecha": "2026-10-05"}).json()
    assert (vieja["tarifa"], vieja["vigencia"]) == ("23205.57", "2026-04-10")
    assert (nueva["tarifa"], nueva["vigencia"]) == ("30000.00", "2026-10-01")
    antes = cliente.get("/api/tarifario/referencia", params={"km": 80, "fecha": "2026-01-01"})
    assert antes.status_code == 404, "antes de cualquier vigencia no hay tarifario"


def test_un_km_que_no_esta_no_se_extrapola(cliente):
    _cargar(cliente)
    r = cliente.get("/api/tarifario/referencia", params={"km": 81, "fecha": "2026-09-10"})
    assert r.status_code == 200 and r.json()["tarifa"] is None


def test_el_porcentaje_sugerido_es_el_del_ultimo_viaje_del_cliente(cliente, datos):
    _cargar(cliente)
    assert cliente.get("/api/tarifario/sugerencia", params={"cliente_id": datos["cliente"]}).status_code == 404
    _orden(cliente, datos, km=80, tarifa_tonelada="19724.73")
    s = cliente.get("/api/tarifario/sugerencia", params={"cliente_id": datos["cliente"]}).json()
    assert (s["porcentaje"], s["km"], s["tarifa_referencia"]) == ("85.00", 80, "23205.57")
    _orden(cliente, datos, km=100, tarifa_tonelada="27192.78", fecha="2026-09-20")
    s = cliente.get("/api/tarifario/sugerencia", params={"cliente_id": datos["cliente"]}).json()
    assert s["porcentaje"] == "100.00", "varía por viaje: manda el último"
    otro = cliente.get("/api/tarifario/sugerencia", params={"cliente_id": datos["otro_cliente"]})
    assert otro.status_code == 404


def test_la_orden_guarda_km_y_tarifa_por_tonelada(cliente, datos):
    o = _orden(cliente, datos, km=80, tarifa_tonelada="19724.73")
    assert (o["km"], o["tarifa_tonelada"], o["tarifa"]) == (80, "19724.73", "1000.00"), "no toca el importe"
    r = cliente.post("/api/ordenes", json={
        "fecha": "2026-09-10", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "km": 0})
    assert r.status_code == 422


def test_csv_invalido_es_422_con_la_linea(cliente):
    r = _cargar(cliente, contenido=b"km;tarifa\n1;100\n1;200\n")
    assert r.status_code == 422 and "línea 3" in r.json()["detail"] and "repetido" in r.json()["detail"]
    r = _cargar(cliente, contenido=b"km;tarifa\nuno;100\n")
    assert r.status_code == 422 and "línea 2" in r.json()["detail"]
    assert _cargar(cliente, contenido=b"km;tarifa\n").status_code == 422
    assert _cargar(cliente, estadia="mucho").status_code == 422


def test_un_operador_consulta_pero_no_carga(cliente):
    _cargar(cliente)
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    staff.post("/auth/login", json={"username": "marta", "password": "una-clave"})
    assert staff.get("/api/tarifario/referencia", params={"km": 80, "fecha": "2026-09-10"}).status_code == 200
    assert _cargar(staff).status_code == 403
