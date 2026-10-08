"""Cartas de Porte Electrónicas traídas de ARCA por su CTG (ADR-036).

ARCA está simulada en el borde del motor (`libracore.arca_wscpe`): el ticket, sus relaciones y la consulta. Lo que
se prueba es lo de este producto: por quién se deja consultar, qué se guarda, que un CTG que falla no se lleve a
los demás, el refresco hasta la descarga y la orden vinculada. CUIT y dominios ficticios.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from libracore import arca_wscpe
from sqlalchemy import select

from app.models import RegistroAuditoria
from app.models.cartas_porte import CartaPorte
from app.servicios import cartas_porte as servicio

AR = timezone(timedelta(hours=-3))
#: La transportista y el titular que delegó: los dos CUIT que el ticket deja operar.
TRANSPORTISTA = "30222222223"
TITULAR = "30444444445"
#: El cliente del fixture `datos` («Agro Norte», 30-12345678-1): es el pagador del flete de las CPE de prueba.
PAGADOR = "30123456781"


def _ticket(*cuits: str) -> dict:
    relaciones = "".join(f'<relation key="{c}" reltype="4"/>' for c in cuits)
    xml = f'<sso><operation><login service="wscpe"><relations>{relaciones}</relations></login></operation></sso>'
    return {"token": base64.b64encode(xml.encode()).decode(), "sign": "SGN"}


def cpe(ctg: int = 10100000001, *, estado: str = "AC", descarga: tuple[int, int] | None = None,
        nro_orden: int | None = None) -> arca_wscpe.CartaDePorte:
    """Una CPE como la devolvería `arca_wscpe.consultar_cpe`."""
    return arca_wscpe.CartaDePorte(
        nro_ctg=ctg, tipo_cpe=74, sucursal=1, nro_orden=nro_orden or ctg % 100000000, estado=estado,
        fecha_emision=datetime(2026, 9, 15, 8, 30, tzinfo=AR), fecha_inicio_estado=None,
        fecha_vencimiento=datetime(2026, 9, 17, 23, 59, tzinfo=AR), observaciones="",
        origen=arca_wscpe.Origen(cuit="20111111112", cod_provincia=12, cod_localidad=5321, planta=None, renspa=""),
        destino=arca_wscpe.Destino(cuit="30666666667", cod_provincia=12, cod_localidad=4211, planta=1234,
                                   cuit_destinatario="30666666667"),
        carga=arca_wscpe.Carga(cod_grano=23, cosecha=2526, peso_bruto=45200, peso_tara=15900,
                               peso_bruto_descarga=descarga[0] if descarga else None,
                               peso_tara_descarga=descarga[1] if descarga else None),
        transporte=arca_wscpe.Transporte(
            cuit_transportista=TRANSPORTISTA, dominios=("AA123BB", "AC456DD"),
            fecha_hora_partida=datetime(2026, 9, 15, 9, 0, tzinfo=AR), km=310, cuit_chofer="20777777778",
            tarifa_referencia=None, tarifa=Decimal("65207.39"), cuit_pagador_flete=PAGADOR,
            cuit_intermediario_flete=None, mercaderia_fumigada=False),
        intervinientes={}, pdf=b"%PDF-1.4 prueba", respuesta_xml=f"<respuesta><nroCTG>{ctg}</nroCTG></respuesta>",
    )


@pytest.fixture
def arca(monkeypatch):
    """ARCA de mentira. `estado["cpes"]` es lo que contesta por CTG (una CPE, o una excepción que levanta)."""
    estado = {
        "ambientes": {"produccion"},
        "relaciones": (TRANSPORTISTA, TITULAR),
        "cpes": {},
        "pedidos": [],
        "logins": 0,
    }

    def par(empresa, servicio_, ambiente):
        assert servicio_ == "wscpe"
        return ("/c.crt", "/c.key") if ambiente in estado["ambientes"] else ("", "")

    async def autenticar(empresa, ambiente):
        estado["logins"] += 1
        return _ticket(*estado["relaciones"])

    async def consultar_cpe(cuit, token, sign, *, ctg, ambiente):
        estado["pedidos"].append((ctg, cuit, ambiente))
        if cuit not in estado["relaciones"]:
            raise arca_wscpe.CuitNoRelacionado("WSCPE: el CUIT representado no está relacionado", [])
        resultado = estado["cpes"].get(ctg)
        if resultado is None:
            raise arca_wscpe.CpeNoEncontrada("WSCPE: [800] No existen solicitudes", [(800, "No existen")])
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(servicio.arca_credenciales, "paths_en_disco_de_servicio", par)
    monkeypatch.setattr(servicio.arca_wscpe, "autenticar", autenticar)
    monkeypatch.setattr(servicio.arca_wscpe, "consultar_cpe", consultar_cpe)
    return estado


def _traer(cliente, *ctgs, cuit=TRANSPORTISTA, **extra):
    return cliente.post("/api/cartas-porte", json={"ctgs": list(ctgs), "cuit_representada": cuit, **extra})


# ── Por quién se consulta ──────────────────────────────────────────────────

def test_representados_son_los_del_ticket_con_su_nombre(cliente, datos, arca):
    arca["relaciones"] = (PAGADOR, TITULAR)
    r = cliente.get("/api/cartas-porte/representados")
    assert r.status_code == 200, r.text
    assert r.json() == {"ambiente": "produccion", "cuits": [
        {"cuit": PAGADOR, "nombre": "Agro Norte"}, {"cuit": TITULAR, "nombre": None}]}


def test_sin_certificado_de_wscpe_dice_donde_cargarlo(cliente, arca):
    arca["ambientes"] = set()
    r = cliente.get("/api/cartas-porte/representados")
    assert r.status_code == 409
    assert "Configuración / ARCA" in r.json()["detail"]


def test_produccion_primero_y_homologacion_si_es_lo_unico(cliente, arca):
    arca["ambientes"] = {"homologacion", "produccion"}
    assert cliente.get("/api/cartas-porte/representados").json()["ambiente"] == "produccion"
    arca["ambientes"] = {"homologacion"}
    assert cliente.get("/api/cartas-porte/representados").json()["ambiente"] == "homologacion"


def test_el_cuit_representado_es_obligatorio(cliente, arca):
    arca["cpes"][10100000001] = cpe()
    r = cliente.post("/api/cartas-porte", json={"ctgs": [10100000001]})
    assert r.status_code == 422
    r = _traer(cliente, 10100000001, cuit="30-2222222")
    assert r.status_code == 422
    assert arca["pedidos"] == [], "sin CUIT válido no se sale a ARCA"


# ── Vista previa ───────────────────────────────────────────────────────────

def test_la_vista_previa_no_guarda_y_cruza_con_los_terceros(cliente, datos, arca, sesion):
    arca["cpes"][10100000001] = cpe()
    r = cliente.post("/api/cartas-porte/consultar", json={"ctg": 10100000001, "cuit_representada": "30-22222222-3"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["id"], v["guardada_id"], v["numero"], v["estado_descripcion"]) == (None, None, "00001-00000001", "Activa")
    assert v["pagador_flete"] == {"cuit": PAGADOR, "nombre": "Agro Norte"}
    assert v["chofer"] == {"cuit": "20777777778", "nombre": None}
    assert (v["peso_neto"], v["tiene_descarga"], v["dominios"]) == (29300, False, ["AA123BB", "AC456DD"])
    assert arca["pedidos"] == [(10100000001, TRANSPORTISTA, "produccion")]
    assert sesion.scalar(select(CartaPorte.id)) is None


def test_la_cpe_que_arca_no_tiene_es_404(cliente, arca):
    r = cliente.post("/api/cartas-porte/consultar", json={"ctg": 999, "cuit_representada": TRANSPORTISTA})
    assert r.status_code == 404
    assert "CTG 999" in r.json()["detail"]


def test_sin_delegacion_es_409(cliente, arca):
    arca["cpes"][10100000001] = cpe()
    r = cliente.post("/api/cartas-porte/consultar", json={"ctg": 10100000001, "cuit_representada": "30555555556"})
    assert r.status_code == 409
    assert "relacionado" in r.json()["detail"]


# ── Traer y guardar ────────────────────────────────────────────────────────

def test_traer_guarda_la_cpe_su_pdf_y_la_auditoria(cliente, datos, arca, sesion):
    arca["cpes"][10100000001] = cpe()
    r = _traer(cliente, 10100000001)
    assert r.status_code == 200, r.text
    [res] = r.json()
    assert res["error"] is None and res["id"]

    v = cliente.get(f"/api/cartas-porte/{res['id']}").json()
    assert (v["nro_ctg"], v["cuit_representada"], v["ambiente"], v["tiene_pdf"]) == (
        10100000001, TRANSPORTISTA, "produccion", True)
    assert v["pagador_flete"]["nombre"] == "Agro Norte"
    assert v["tarifa"] == "65207.39" and v["km"] == 310

    pdf = cliente.get(f"/api/cartas-porte/{res['id']}/pdf")
    assert pdf.status_code == 200
    assert (pdf.content, pdf.headers["content-type"]) == (b"%PDF-1.4 prueba", "application/pdf")

    fila = sesion.get(CartaPorte, res["id"])
    assert fila.respuesta_arca == "<respuesta><nroCTG>10100000001</nroCTG></respuesta>"
    assert sesion.scalars(select(RegistroAuditoria.entidad).where(
        RegistroAuditoria.entidad == "carta_porte")).all() == ["carta_porte"]


def test_traer_dos_veces_el_mismo_ctg_no_duplica(cliente, arca, sesion):
    arca["cpes"][10100000001] = cpe()
    primero = _traer(cliente, 10100000001).json()[0]["id"]
    arca["cpes"][10100000001] = cpe(descarga=(45100, 15800))
    segundo = _traer(cliente, 10100000001, 10100000001).json()
    assert [s["id"] for s in segundo] == [primero], "un CTG repetido en el lote se pide una vez"
    assert len(sesion.scalars(select(CartaPorte)).all()) == 1
    assert cliente.get(f"/api/cartas-porte/{primero}").json()["peso_neto_descarga"] == 29300


def test_un_ctg_que_falla_no_se_lleva_a_los_demas(cliente, arca, sesion):
    arca["cpes"][1] = cpe(1)
    arca["cpes"][3] = cpe(3)
    r = _traer(cliente, 1, 2, 3)
    assert r.status_code == 200, r.text
    assert [(x["ctg"], bool(x["id"]), x["error"] is None) for x in r.json()] == [
        (1, True, True), (2, False, False), (3, True, True)]
    assert "CTG 2" in r.json()[1]["error"]
    assert {c.nro_ctg for c in sesion.scalars(select(CartaPorte))} == {1, 3}


def test_sin_delegacion_corta_el_lote_entero(cliente, arca, sesion):
    arca["cpes"][1] = cpe(1)
    r = _traer(cliente, 1, 2, cuit="30555555556")
    assert r.status_code == 409
    assert len(arca["pedidos"]) == 1, "falla igual para todos: no se piden los demás"
    assert sesion.scalar(select(CartaPorte.id)) is None


def test_el_lote_tiene_tope(cliente, arca):
    r = _traer(cliente, *range(1, servicio.MAX_POR_LOTE + 2))
    assert r.status_code == 422
    assert arca["pedidos"] == []


# ── La orden ───────────────────────────────────────────────────────────────

def _orden(cliente, datos):
    r = cliente.post("/api/ordenes", json={
        "fecha": "2026-09-15", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
        "destino_id": datos["destino"], "tarifa": "1000.00"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_traer_vinculada_a_una_orden(cliente, datos, arca):
    orden = _orden(cliente, datos)
    arca["cpes"][1] = cpe(1)
    [res] = _traer(cliente, 1, orden_carga_id=orden).json()
    assert cliente.get(f"/api/cartas-porte/{res['id']}").json()["orden_carga_id"] == orden
    assert [c["nro_ctg"] for c in cliente.get("/api/cartas-porte", params={"orden_carga_id": orden}).json()] == [1]


def test_una_orden_no_se_vincula_a_un_lote(cliente, datos, arca):
    orden = _orden(cliente, datos)
    assert _traer(cliente, 1, 2, orden_carga_id=orden).status_code == 422
    assert arca["pedidos"] == []


def test_vincular_y_desvincular(cliente, datos, arca):
    orden = _orden(cliente, datos)
    arca["cpes"][1] = cpe(1)
    id_ = _traer(cliente, 1).json()[0]["id"]
    assert cliente.put(f"/api/cartas-porte/{id_}/orden", json={"orden_carga_id": 99999}).status_code == 404
    r = cliente.put(f"/api/cartas-porte/{id_}/orden", json={"orden_carga_id": orden})
    assert r.status_code == 200 and r.json()["orden_carga_id"] == orden
    # Actualizarla desde ARCA no le saca la orden.
    assert cliente.post(f"/api/cartas-porte/{id_}/actualizar").json()["orden_carga_id"] == orden
    r = cliente.put(f"/api/cartas-porte/{id_}/orden", json={"orden_carga_id": None})
    assert r.status_code == 200 and r.json()["orden_carga_id"] is None


# ── Actualizar hasta la descarga ───────────────────────────────────────────

def test_actualizar_usa_el_mismo_cuit_y_ambiente(cliente, arca):
    arca["cpes"][1] = cpe(1)
    id_ = _traer(cliente, 1, cuit=TITULAR).json()[0]["id"]
    arca["ambientes"] = {"homologacion", "produccion"}
    arca["cpes"][1] = cpe(1, estado="CN", descarga=(45100, 15800))
    r = cliente.post(f"/api/cartas-porte/{id_}/actualizar")
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["tiene_descarga"]) == ("CN", True)
    assert arca["pedidos"][-1] == (1, TITULAR, "produccion")


def test_actualizar_abiertas_saltea_las_cerradas_y_las_descargadas(cliente, arca):
    arca["cpes"].update({1: cpe(1), 2: cpe(2, estado="AN"), 3: cpe(3, descarga=(1, 1))})
    _traer(cliente, 1, 2, 3)
    assert [c["nro_ctg"] for c in cliente.get("/api/cartas-porte", params={"abiertas": True}).json()] == [1]

    arca["pedidos"].clear()
    arca["cpes"][1] = cpe(1, estado="CN", descarga=(45100, 15800))
    r = cliente.post("/api/cartas-porte/actualizar-abiertas")
    assert r.status_code == 200, r.text
    assert r.json() == {"actualizadas": 1, "errores": []}
    assert [p[0] for p in arca["pedidos"]] == [1]
    assert cliente.get("/api/cartas-porte", params={"abiertas": True}).json() == []


def test_actualizar_abiertas_informa_las_que_fallan(cliente, arca):
    arca["cpes"].update({1: cpe(1), 2: cpe(2)})
    _traer(cliente, 1, 2)
    del arca["cpes"][1]
    r = cliente.post("/api/cartas-porte/actualizar-abiertas").json()
    assert r["actualizadas"] == 1
    assert [e["ctg"] for e in r["errores"]] == [1]


def test_el_listado_va_de_la_mas_nueva_a_la_mas_vieja(cliente, arca):
    vieja, nueva = cpe(1), cpe(2)
    nueva = replace(nueva, fecha_emision=vieja.fecha_emision + timedelta(days=1))
    arca["cpes"].update({1: vieja, 2: nueva})
    _traer(cliente, 1, 2)
    assert [c["nro_ctg"] for c in cliente.get("/api/cartas-porte").json()] == [2, 1]


def test_sin_pdf_el_pdf_es_404(cliente, arca):
    arca["cpes"][1] = replace(cpe(1), pdf=None)
    id_ = _traer(cliente, 1).json()[0]["id"]
    assert cliente.get(f"/api/cartas-porte/{id_}").json()["tiene_pdf"] is False
    assert cliente.get(f"/api/cartas-porte/{id_}/pdf").status_code == 404


def test_sin_sesion_no_hay_cartas_de_porte(cliente, arca):
    cliente.post("/auth/logout")
    cliente.cookies.clear()
    assert cliente.get("/api/cartas-porte").status_code in (401, 403)


# ── No frena el loop ───────────────────────────────────────────────────────

def test_consultar_no_frena_el_loop(cliente, arca, monkeypatch):
    """La firma del pedido de acceso (`openssl`) y la base son sincrónicas: la ruta va en `def`."""
    entro, desperto = threading.Event(), {}

    async def autenticar_lento(empresa, ambiente):
        entro.set()
        time.sleep(0.5)
        desperto["en"] = time.monotonic()
        return _ticket(TRANSPORTISTA)

    monkeypatch.setattr(servicio.arca_wscpe, "autenticar", autenticar_lento)
    arca["cpes"][1] = cpe(1)

    async def correr():
        transporte = httpx.ASGITransport(app=cliente.app)
        async with (
            httpx.AsyncClient(transport=transporte, base_url="https://testserver", cookies=cliente.cookies) as c,
            httpx.AsyncClient(transport=transporte, base_url="https://testserver") as anonimo,
        ):
            tarea = asyncio.create_task(c.post("/api/cartas-porte/consultar",
                                               json={"ctg": 1, "cuit_representada": TRANSPORTISTA}))
            assert await asyncio.to_thread(entro.wait, 10)
            health = await anonimo.get("/health")
            fin = time.monotonic()
            return await asyncio.wait_for(tarea, 30), health, fin

    respuesta, health, fin = asyncio.run(correr())
    assert respuesta.status_code == 200, respuesta.text
    assert health.status_code == 200
    assert fin < desperto["en"], "/health esperó a que terminara la consulta: la ruta bloqueó el loop"


def test_se_guarda_desde_cuando_esta_en_su_estado(cliente, arca):
    """Pedido del humano: una CPE «Anulada» cuyo PDF decía otra cosa. El PDF es del día de la emisión."""
    anulada = replace(cpe(1, estado="AN"), fecha_inicio_estado=datetime(2026, 9, 22, 9, 13, tzinfo=AR))
    arca["cpes"][1] = anulada
    previa = cliente.post("/api/cartas-porte/consultar", json={"ctg": 1, "cuit_representada": TRANSPORTISTA}).json()
    assert previa["fecha_inicio_estado"].startswith("2026-09-22T09:13")
    id_ = _traer(cliente, 1).json()[0]["id"]
    v = cliente.get(f"/api/cartas-porte/{id_}").json()
    assert v["estado_descripcion"] == "Anulada"
    assert datetime.fromisoformat(v["fecha_inicio_estado"]) == datetime(2026, 9, 22, 9, 13, tzinfo=AR)
