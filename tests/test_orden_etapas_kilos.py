"""La orden con etapa, kilos y adjuntos; el chofer con CUIT (ADR-037).

La etapa es operativa y va aparte del estado de facturación: por ahora sólo informa, también en una orden
facturada. Los kilos de carga y de descarga son enteros y el neto lo pone el servidor si están bruto y tara.
Los adjuntos (la foto del ticket) se guardan en la base y su tipo sale del contenido, no del navegador.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import RegistroAuditoria
from tests.test_comprobantes import facturar, orden

JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64


def _orden(cliente, datos, **extra):
    r = cliente.post("/api/ordenes", json={
        "fecha": "2026-10-07", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00", **extra})
    return r


# ── Etapa ──────────────────────────────────────────────────────────────────

def test_una_orden_nueva_nace_asignada_y_se_filtra_por_etapa(cliente, datos):
    a = _orden(cliente, datos).json()
    b = _orden(cliente, datos, etapa="cargada").json()
    assert (a["etapa"], b["etapa"]) == ("asignada", "cargada")
    assert [o["id"] for o in cliente.get("/api/ordenes", params={"etapa": "cargada"}).json()] == [b["id"]]


def test_una_etapa_que_no_existe_es_422(cliente, datos):
    assert _orden(cliente, datos, etapa="liquidada").status_code == 422
    a = _orden(cliente, datos).json()
    assert cliente.put(f"/api/ordenes/{a['id']}/etapa", json={"etapa": "volando"}).status_code == 422


def test_cambiar_de_etapa_queda_en_la_auditoria(cliente, datos, sesion):
    a = _orden(cliente, datos).json()
    for etapa in ("cargada", "en_viaje", "descargada", "cargada"):
        r = cliente.put(f"/api/ordenes/{a['id']}/etapa", json={"etapa": etapa})
        assert r.status_code == 200, r.text
        assert r.json()["etapa"] == etapa, "por ahora se puede ir para adelante y para atrás"
    asientos = sesion.scalars(select(RegistroAuditoria).where(
        RegistroAuditoria.entidad == "orden_carga", RegistroAuditoria.entidad_id == a["id"],
        RegistroAuditoria.accion == "modificacion")).all()
    assert [x.datos_despues["etapa"] for x in asientos] == ["cargada", "en_viaje", "descargada", "cargada"]


@pytest.mark.con_emisor
def test_una_facturada_cambia_de_etapa_y_recibe_adjuntos(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a]).status_code == 201
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "facturada"
    r = cliente.put(f"/api/ordenes/{a['id']}/etapa", json={"etapa": "cerrada"})
    assert r.status_code == 200 and r.json()["etapa"] == "cerrada"
    r = cliente.post(f"/api/ordenes/{a['id']}/adjuntos", files={"archivo": ("ticket.jpg", JPG, "image/jpeg")})
    assert r.status_code == 201, r.text
    # El PUT de la orden sigue cerrado para una facturada: la etapa va por su propio endpoint.
    assert cliente.put(f"/api/ordenes/{a['id']}", json={
        "fecha": "2026-08-10", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00", "etapa": "asignada"}).status_code == 409


def test_una_anulada_no_cambia_de_etapa_ni_recibe_adjuntos(cliente, datos):
    a = _orden(cliente, datos).json()
    assert cliente.delete(f"/api/ordenes/{a['id']}").status_code == 200
    assert cliente.put(f"/api/ordenes/{a['id']}/etapa", json={"etapa": "cargada"}).status_code == 409
    r = cliente.post(f"/api/ordenes/{a['id']}/adjuntos", files={"archivo": ("t.jpg", JPG, "image/jpeg")})
    assert r.status_code == 409


# ── Kilos ──────────────────────────────────────────────────────────────────

def test_el_neto_lo_pone_el_servidor(cliente, datos):
    r = _orden(cliente, datos, kg_bruto_carga=45200, kg_tara_carga=15900,
               kg_bruto_descarga=45100, kg_tara_descarga=15800)
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["kg_neto_carga"], o["kg_neto_descarga"]) == (29300, 29300)


def test_un_neto_que_no_es_la_resta_es_422(cliente, datos):
    r = _orden(cliente, datos, kg_bruto_carga=45200, kg_tara_carga=15900, kg_neto_carga=30000)
    assert r.status_code == 422
    assert "45200 - 15900 = 29300" in r.text


def test_la_tara_mayor_que_el_bruto_es_422(cliente, datos):
    r = _orden(cliente, datos, kg_bruto_descarga=10000, kg_tara_descarga=15000)
    assert r.status_code == 422
    assert "descarga" in r.text


def test_el_neto_solo_se_acepta(cliente, datos):
    """A veces es lo único que se sabe: lo que dice el ticket."""
    o = _orden(cliente, datos, kg_neto_descarga=29300).json()
    assert (o["kg_bruto_descarga"], o["kg_tara_descarga"], o["kg_neto_descarga"]) == (None, None, 29300)


def test_kilos_negativos_es_422(cliente, datos):
    assert _orden(cliente, datos, kg_bruto_carga=-1).status_code == 422


def test_editar_los_kilos_recalcula_el_neto(cliente, datos):
    a = _orden(cliente, datos, kg_bruto_carga=40000, kg_tara_carga=15000).json()
    r = cliente.put(f"/api/ordenes/{a['id']}", json={
        "fecha": "2026-10-07", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00", "kg_bruto_carga": 41000, "kg_tara_carga": 15000,
        "kg_neto_carga": 25000})
    assert r.status_code == 422, "el neto viejo no es la resta nueva"
    r = cliente.put(f"/api/ordenes/{a['id']}", json={
        "fecha": "2026-10-07", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00", "kg_bruto_carga": 41000, "kg_tara_carga": 15000})
    assert r.status_code == 200 and r.json()["kg_neto_carga"] == 26000


# ── CUIT del chofer ────────────────────────────────────────────────────────

def test_el_cuit_del_chofer_se_guarda_en_once_digitos(cliente):
    r = cliente.post("/api/choferes", json={"nombre": "Chofer de prueba", "cuit": "20-12345678-6"})
    assert r.status_code == 201, r.text
    assert r.json()["cuit"] == "20123456786"
    vacio = cliente.post("/api/choferes", json={"nombre": "Sin CUIT", "cuit": ""})
    assert vacio.status_code == 201 and vacio.json()["cuit"] is None


@pytest.mark.parametrize("cuit", ["20-12345678-0", "2012345678", "ab-12345678-6"])
def test_un_cuit_de_chofer_invalido_es_422(cliente, cuit):
    r = cliente.post("/api/choferes", json={"nombre": "Chofer", "cuit": cuit})
    assert r.status_code == 422
    assert "CUIT del chofer" in r.text


# ── Adjuntos ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("nombre", "contenido", "tipo"), [
    ("ticket.jpg", JPG, "image/jpeg"), ("ticket.png", PNG, "image/png"),
    ("ticket.pdf", PDF, "application/pdf"), ("IMG_0001.HEIC", HEIC, "image/heic"),
])
def test_subir_listar_y_bajar_un_adjunto(cliente, datos, nombre, contenido, tipo):
    a = _orden(cliente, datos).json()
    r = cliente.post(f"/api/ordenes/{a['id']}/adjuntos",
                     files={"archivo": (nombre, contenido, "application/octet-stream")})
    assert r.status_code == 201, r.text
    adj = r.json()
    assert (adj["nombre"], adj["tipo_contenido"], adj["tamanio"]) == (nombre, tipo, len(contenido))
    assert [x["id"] for x in cliente.get(f"/api/ordenes/{a['id']}/adjuntos").json()] == [adj["id"]]
    baja = cliente.get(f"/api/ordenes/{a['id']}/adjuntos/{adj['id']}")
    assert baja.status_code == 200
    assert (baja.content, baja.headers["content-type"].split(";")[0]) == (contenido, tipo)
    assert baja.headers["x-content-type-options"] == "nosniff"


def test_el_tipo_sale_del_contenido_y_no_del_navegador(cliente, datos):
    a = _orden(cliente, datos).json()
    r = cliente.post(f"/api/ordenes/{a['id']}/adjuntos",
                     files={"archivo": ("foto.jpg", b"<html><script>alert(1)</script>", "image/jpeg")})
    assert r.status_code == 422
    assert "JPG" in r.json()["detail"]


def test_un_adjunto_vacio_o_muy_grande_es_422(cliente, datos, monkeypatch):
    from app.servicios import adjuntos
    a = _orden(cliente, datos).json()
    assert cliente.post(f"/api/ordenes/{a['id']}/adjuntos",
                        files={"archivo": ("v.jpg", b"", "image/jpeg")}).status_code == 422
    monkeypatch.setattr(adjuntos, "TAMANIO_MAXIMO", 32)
    r = cliente.post(f"/api/ordenes/{a['id']}/adjuntos", files={"archivo": ("g.jpg", JPG, "image/jpeg")})
    assert r.status_code == 422 and "pesa más" in r.json()["detail"]


def test_el_nombre_con_acentos_y_rutas_se_limpia(cliente, datos):
    a = _orden(cliente, datos).json()
    adj = cliente.post(f"/api/ordenes/{a['id']}/adjuntos",
                       files={"archivo": ("C:\\fotos\\ticket ñandú.jpg", JPG, "image/jpeg")}).json()
    assert adj["nombre"] == "ticket ñandú.jpg"
    baja = cliente.get(f"/api/ordenes/{a['id']}/adjuntos/{adj['id']}")
    assert "filename*=UTF-8''ticket%20%C3%B1and%C3%BA.jpg" in baja.headers["content-disposition"]


def test_borrar_un_adjunto_y_no_alcanzar_el_de_otra_orden(cliente, datos, sesion):
    a, b = _orden(cliente, datos).json(), _orden(cliente, datos).json()
    adj = cliente.post(f"/api/ordenes/{a['id']}/adjuntos", files={"archivo": ("t.jpg", JPG, "image/jpeg")}).json()
    assert cliente.get(f"/api/ordenes/{b['id']}/adjuntos/{adj['id']}").status_code == 404
    assert cliente.delete(f"/api/ordenes/{b['id']}/adjuntos/{adj['id']}").status_code == 404
    assert cliente.delete(f"/api/ordenes/{a['id']}/adjuntos/{adj['id']}").status_code == 204
    assert cliente.get(f"/api/ordenes/{a['id']}/adjuntos").json() == []
    acciones = sesion.scalars(select(RegistroAuditoria.accion).where(
        RegistroAuditoria.entidad == "orden_adjunto").order_by(RegistroAuditoria.id)).all()
    assert [x.value for x in acciones] == ["alta", "baja"]
