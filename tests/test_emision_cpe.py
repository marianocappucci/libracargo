"""Emitir la Carta de Porte desde la orden, por delegación de un titular (ADR-043).

ARCA simulada en el borde del motor (`libracore.arca_wscpe`): el ticket y sus relaciones, los catálogos, la emisión
y la anulación. Lo que se prueba es lo del producto: la traba de producción, la propuesta desde la orden y la
plantilla del titular, guardar lo emitido y el enlace al PDF para el chofer. CUIT y dominios ficticios.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from libracore import arca_wscpe

from app.models.cartas_porte import CartaPorte
from app.servicios import cartas_porte as cpe_servicio
from app.servicios import emision_cpe
from tests.test_cartas_porte import AR, _ticket, cpe  # noqa: F401

TITULAR = "30876543210"  # un titular ficticio, con dígito verificador válido
SUITRANS = "30222222223"


@pytest.fixture
def arca(monkeypatch):
    estado = {"ambientes": {"produccion"}, "relaciones": (TITULAR,), "emitidas": [], "anuladas": [],
              "emitir": None, "consulta": None}
    emision_cpe._CACHE.clear()

    def par(empresa, servicio_, ambiente):
        return ("/c.crt", "/c.key") if ambiente in estado["ambientes"] else ("", "")

    async def autenticar(empresa, ambiente):
        return _ticket(*estado["relaciones"])

    async def tipos_grano(cuit, token, sign, ambiente):
        return {19: "Maíz", 23: "Soja"}

    async def provincias(cuit, token, sign, ambiente):
        return {1: "BUENOS AIRES", 12: "SANTA FE", 0: "CAP.FEDERAL"}

    async def localidades(cuit, token, sign, *, cod_provincia, ambiente):
        return {1: {13575: "SUIPACHA", 11128: "PILAR"}, 12: {4211: "ROSARIO"}}.get(cod_provincia, {})

    async def plantas(cuit_representada, token, sign, *, cuit, ambiente):
        return [arca_wscpe.Planta(715070, 1, 11128)]

    async def emitir_cpe(cuit, token, sign, solicitud, *, ambiente):
        estado["emitidas"].append((cuit, solicitud, ambiente))
        if isinstance(estado["emitir"], Exception):
            raise estado["emitir"]
        return estado["emitir"] or replace(cpe(10135099999, nro_orden=311), nro_orden=311, sucursal=1)

    async def anular_cpe(cuit, token, sign, *, sucursal, nro_orden, tipo_cpe, observaciones, ambiente):
        estado["anuladas"].append((cuit, sucursal, nro_orden, observaciones))
        return "AN"

    async def consultar_cpe(cuit, token, sign, *, ctg, ambiente):
        return estado["consulta"] or cpe(ctg, estado="AN")

    monkeypatch.setattr(cpe_servicio.arca_credenciales, "paths_en_disco_de_servicio", par)
    for nombre, f in (("autenticar", autenticar), ("tipos_grano", tipos_grano), ("provincias", provincias),
                      ("localidades", localidades), ("plantas", plantas), ("emitir_cpe", emitir_cpe),
                      ("anular_cpe", anular_cpe), ("consultar_cpe", consultar_cpe)):
        monkeypatch.setattr(arca_wscpe, nombre, f)
    return estado


@pytest.fixture
def orden(cliente):
    """Una orden completa: cliente y fletero con CUIT, chofer con CUIT, vehículo, kilos, km y tarifa por tonelada."""
    def alta(ruta, cuerpo):
        r = cliente.post(ruta, json=cuerpo)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    cli = alta("/api/terceros", {"razon_social": "Agro Titular SA", "cuit": "30-87654321-0", "es_cliente": True})
    flet = alta("/api/terceros", {"razon_social": "Fletero Prueba", "cuit": "20-12345678-6", "es_fletero": True})
    chofer = alta("/api/choferes", {"nombre": "Chofer Prueba", "cuit": "20-11111111-2", "fletero_id": flet})
    veh = alta("/api/vehiculos", {"patente_chasis": "CTR587", "patente_acoplado": "OVY322", "fletero_id": flet})
    origen = alta("/api/localidades", {"nombre": "Suipacha", "provincia": "Buenos Aires"})
    destino = alta("/api/localidades", {"nombre": "Pilar", "provincia": "Buenos Aires"})
    return alta("/api/ordenes", {
        "fecha": "2026-10-08", "cliente_id": cli, "origen_id": origen, "destino_id": destino, "fletero_id": flet,
        "chofer_id": chofer, "vehiculo_id": veh, "tarifa": "1000.00", "kg_bruto_carga": 45000,
        "kg_tara_carga": 15220, "km": 80, "tarifa_tonelada": "19724.73"})


def _datos(propuesta, **cambios):
    d = {**propuesta, "cod_grano": 19, "cosecha": 2526,
         "destino": {**propuesta["destino"], "cuit": "30650849805", "planta": 715070},
         "cuit_destinatario": "30650849805",
         "transporte": {**propuesta["transporte"], "fecha_hora_partida": "2026-10-08T13:35:00-03:00"}}
    d.update(cambios)
    return d


def _propuesta(cliente, orden):
    r = cliente.get("/api/cartas-porte/emision/propuesta", params={"orden_id": orden, "cuit_titular": TITULAR})
    assert r.status_code == 200, r.text
    return r.json()


def _habilitar(cliente, valor=True):
    r = cliente.put("/api/cartas-porte/emision/habilitada", json={"habilitada": valor})
    assert r.status_code == 200, r.text
    return r.json()


def _cargar_empresa(cliente):
    from tests.conftest import cargar_empresa
    cargar_empresa(cliente)


# ── La traba ───────────────────────────────────────────────────────────────

def test_en_produccion_arranca_apagada_y_la_prende_un_admin(cliente, arca):
    _cargar_empresa(cliente)
    assert cliente.get("/api/cartas-porte/emision/estado").json() == {
        "ambiente": "produccion", "habilitada": False, "puede_emitir": False}
    assert _habilitar(cliente)["puede_emitir"] is True
    asiento = cliente.get("/api/auditoria?entidad=configuracion").json()["registros"][0]
    assert asiento["datos_despues"]["cpe_emision_habilitada"] is True


def test_en_homologacion_se_puede_sin_habilitar(cliente, arca):
    arca["ambientes"] = {"homologacion"}
    assert cliente.get("/api/cartas-porte/emision/estado").json()["puede_emitir"] is True


def test_un_operador_no_la_prende(cliente, arca):
    _cargar_empresa(cliente)
    cliente.post("/api/usuarios", json={"username": "marta", "name": "Marta", "password": "una-clave",
                                        "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    staff.post("/auth/login", json={"username": "marta", "password": "una-clave"})
    assert staff.put("/api/cartas-porte/emision/habilitada", json={"habilitada": True}).status_code == 403


# ── La propuesta ───────────────────────────────────────────────────────────

def test_la_propuesta_sale_de_la_orden(cliente, arca, orden):
    p = _propuesta(cliente, orden)
    assert p["origen"] == {"tipo": "campo", "cod_provincia": 1, "cod_localidad": 13575}
    assert (p["destino"]["cod_provincia"], p["destino"]["cod_localidad"]) == (1, 11128)
    assert (p["peso_bruto"], p["peso_tara"]) == (45000, 15220)
    t = p["transporte"]
    assert (t["cuit_transportista"], t["cuit_chofer"], t["cuit_pagador_flete"]) == (
        "20123456786", "20111111112", TITULAR)
    assert (t["dominios"], t["km"], t["tarifa"]) == (["CTR587", "OVY322"], 80, "19724.73")
    assert p["faltantes"] == ["Elegí el grano."]


def test_lo_que_falta_se_dice(cliente, arca, datos):
    o = cliente.post("/api/ordenes", json={"fecha": "2026-10-08", "cliente_id": datos["otro_cliente"],
                                           "origen_id": datos["origen"], "destino_id": datos["destino"]}).json()
    p = _propuesta(cliente, o["id"])
    textos = " | ".join(p["faltantes"])
    for esperado in ("origen «Suipacha»", "destino «Rosario»", "vehículo", "pagador del flete", "kilos de carga",
                     "grano"):
        assert esperado in textos, esperado


# ── Emitir ─────────────────────────────────────────────────────────────────

def test_emitir_apagada_es_409_y_sin_confirmar_es_422(cliente, arca, orden):
    _cargar_empresa(cliente)
    datos = _datos(_propuesta(cliente, orden))
    r = cliente.post("/api/cartas-porte/emision/emitir", json={"orden_id": orden, "datos": datos, "confirmo": True})
    assert r.status_code == 409 and "apagada" in r.json()["detail"]
    _habilitar(cliente)
    r = cliente.post("/api/cartas-porte/emision/emitir", json={"orden_id": orden, "datos": datos})
    assert r.status_code == 422 and "Confirmá" in r.json()["detail"]
    assert arca["emitidas"] == []


def test_emitir_guarda_la_cpe_vinculada_y_recuerda_la_plantilla(cliente, arca, orden, sesion):
    _cargar_empresa(cliente)
    _habilitar(cliente)
    p = _propuesta(cliente, orden)
    r = cliente.post("/api/cartas-porte/emision/emitir",
                     json={"orden_id": orden, "datos": _datos(p), "confirmo": True})
    assert r.status_code == 201, r.text
    c = r.json()
    assert (c["nro_ctg"], c["orden_carga_id"], c["tiene_pdf"], c["cuit_representada"]) == (
        10135099999, orden, True, TITULAR)
    assert sesion.get(CartaPorte, c["id"]).emitida is True and c["emitida"] is True
    cuit, solicitud, amb = arca["emitidas"][0]
    assert (cuit, amb, solicitud.cuit_solicitante, solicitud.cod_grano, solicitud.peso_bruto) == (
        TITULAR, "produccion", TITULAR, 19, 45000)
    assert isinstance(solicitud.origen, arca_wscpe.OrigenCampo)
    assert (solicitud.destino.planta, solicitud.transporte.dominios, str(solicitud.transporte.tarifa)) == (
        715070, ("CTR587", "OVY322"), "19724.73")
    # La próxima propuesta de ese titular ya trae el grano, la cosecha, el destino y la planta.
    p2 = _propuesta(cliente, orden)
    assert (p2["cod_grano"], p2["cosecha"], p2["destino"]["planta"], p2["de_plantilla"]) == (19, 2526, 715070, True)
    assert p2["faltantes"] == []


def test_en_homologacion_no_hace_falta_confirmar(cliente, arca, orden):
    arca["ambientes"] = {"homologacion"}
    r = cliente.post("/api/cartas-porte/emision/emitir",
                     json={"orden_id": orden, "datos": _datos(_propuesta(cliente, orden))})
    assert r.status_code == 201, r.text
    assert arca["emitidas"][0][2] == "homologacion"


def test_un_titular_que_no_delego_no_emite(cliente, arca, orden):
    arca["ambientes"] = {"homologacion"}
    arca["relaciones"] = ("30444444445",)
    r = cliente.post("/api/cartas-porte/emision/emitir",
                     json={"orden_id": orden, "datos": _datos(_propuesta(cliente, orden))})
    assert r.status_code == 409 and "no le delegó" in r.json()["detail"]
    assert arca["emitidas"] == []


@pytest.mark.parametrize(("error", "status", "texto"), [
    (arca_wscpe.ErrorWscpe("WSCPE: [2008] sin SISA", [(2008, "sin SISA")]), 422, "rechazó"),
    (arca_wscpe.EmisionIncierta("no se sabe", sucursal=1, nro_orden=311, tipo_cpe=74), 502, "número 311"),
    (arca_wscpe.SolicitudInvalida(["la tara tiene que ser menor que el peso bruto"]), 422, "tara"),
])
def test_los_errores_de_arca(cliente, arca, orden, error, status, texto):
    arca["ambientes"] = {"homologacion"}
    arca["emitir"] = error
    r = cliente.post("/api/cartas-porte/emision/emitir",
                     json={"orden_id": orden, "datos": _datos(_propuesta(cliente, orden))})
    assert r.status_code == status and texto in r.json()["detail"]


def test_si_se_emitio_pero_no_se_guardo_lo_dice_con_el_ctg(cliente, arca, orden, monkeypatch, sesion):
    arca["ambientes"] = {"homologacion"}

    def falla(*a, **k):
        raise RuntimeError("la base se cayó")

    monkeypatch.setattr(cpe_servicio, "guardar", falla)
    r = cliente.post("/api/cartas-porte/emision/emitir",
                     json={"orden_id": orden, "datos": _datos(_propuesta(cliente, orden))})
    assert r.status_code == 500
    assert "SE EMITIÓ" in r.json()["detail"] and "10135099999" in r.json()["detail"]


# ── Anular y el enlace ─────────────────────────────────────────────────────

def _emitida(cliente, arca, orden):
    arca["ambientes"] = {"homologacion"}
    r = cliente.post("/api/cartas-porte/emision/emitir",
                     json={"orden_id": orden, "datos": _datos(_propuesta(cliente, orden))})
    assert r.status_code == 201, r.text
    return r.json()


def test_anular_una_emitida(cliente, arca, orden):
    c = _emitida(cliente, arca, orden)
    r = cliente.post(f"/api/cartas-porte/{c['id']}/anular", json={"observaciones": "Viaje suspendido"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "AN"
    assert arca["anuladas"] == [(TITULAR, 1, 311, "Viaje suspendido")]
    assert cliente.post(f"/api/cartas-porte/{c['id']}/anular", json={}).status_code == 409, "ya anulada"


def test_no_se_anula_una_traida(cliente, arca, orden, sesion):
    c = _emitida(cliente, arca, orden)
    fila = sesion.get(CartaPorte, c["id"])
    fila.emitida = False
    sesion.commit()
    r = cliente.post(f"/api/cartas-porte/{c['id']}/anular", json={})
    assert r.status_code == 409 and "emitió este sistema" in r.json()["detail"]


def test_el_enlace_al_pdf_para_el_chofer(cliente, arca, orden, monkeypatch):
    c = _emitida(cliente, arca, orden)
    r = cliente.get(f"/api/cartas-porte/{c['id']}/enlace")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://testserver/api/publico/cpe/")
    anonimo = TestClient(cliente.app, base_url="https://testserver")
    pdf = anonimo.get(url.replace("https://testserver", ""))
    assert pdf.status_code == 200 and pdf.content == b"%PDF-1.4 prueba"
    trucho = url[:-8] + "00000000.pdf"
    assert anonimo.get(trucho.replace("https://testserver", "")).status_code == 404
    vencido, _ = emision_cpe.enlace(c["id"], ahora=time.time() - 8 * 24 * 3600)
    assert anonimo.get("/api/publico" + vencido).status_code == 404
