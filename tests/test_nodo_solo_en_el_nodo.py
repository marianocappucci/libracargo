"""«La oficina con nodo opera y la web consulta»: el 409 `solo_en_el_nodo` (ADR-056).

Decisión del humano (2026-10-22): órdenes, caja, asientos, facturas y CPE se escriben **sólo en el nodo**; en el
central esas escrituras contestan 409 `solo_en_el_nodo`. Y el diseño que protege a Suitrans (que hoy opera en la web,
sin nodo): el 409 **sólo aplica si la instancia tiene un nodo vinculado** (`node_identity` con una fila activa). Sin
nodo, la web opera como hoy; al dar de baja el nodo, vuelve a operar.

Las dos puntas: el central con un nodo vinculado (acá, `cliente` más una fila en `node_identity`), y el nodo mismo
(`escenario`), donde lo que manda el central —los maestros, la configuración— es de sólo lectura.
"""
from __future__ import annotations

import pytest
from libracore.db import core
from libraedge import aprovisionamiento as aprov

from app import offline

#: Cada escritura que sólo el nodo hace: método, ruta y un cuerpo cualquiera. La guarda corre antes que el handler,
#: así que ni los ids ni el cuerpo hacen falta.
ESCRITURAS = [
    ("POST", "/api/ordenes"), ("PUT", "/api/ordenes/1"), ("DELETE", "/api/ordenes/1"), ("PUT", "/api/ordenes/1/etapa"),
    ("POST", "/api/ordenes/1/adjuntos"), ("DELETE", "/api/ordenes/1/adjuntos/1"),
    ("POST", "/api/caja"), ("PUT", "/api/caja/1"), ("DELETE", "/api/caja/1"),
    ("POST", "/api/gastos"), ("PUT", "/api/gastos/1"), ("DELETE", "/api/gastos/1"),
    ("POST", "/api/comprobantes/desde-ordenes"), ("POST", "/api/comprobantes/directa"),
    ("DELETE", "/api/comprobantes/1"),
    ("POST", "/api/comprobantes/1/nota-de-credito"), ("POST", "/api/comprobantes/1/nota-de-debito"),
    ("POST", "/api/cartas-porte"), ("POST", "/api/cartas-porte/actualizar-abiertas"),
    ("POST", "/api/cartas-porte/1/anular"), ("POST", "/api/cartas-porte/1/actualizar"),
    ("PUT", "/api/cartas-porte/1/orden"), ("POST", "/api/cartas-porte/emision/emitir"),
    ("POST", "/api/localidades/1/unificar"),
    ("PUT", "/api/cartas-porte/titulares/1/plantilla"), ("DELETE", "/api/cartas-porte/titulares/1/plantilla"),
]

#: Lo que el central sigue haciendo con un nodo vinculado: consultar todo.
LECTURAS = ["/api/ordenes", "/api/caja", "/api/gastos", "/api/comprobantes", "/api/cartas-porte",
            "/api/cuentas/cliente/1", "/api/comprobantes/totales", "/api/reportes/resumen", "/api/reportes/saldos"]


@pytest.fixture
def con_nodo_vinculado(cliente):
    with core.get_connection() as conn:
        aprov.registrar(conn, offline.aprovisionamiento, "oficina-1", sucursal="1")
    return cliente


@pytest.mark.parametrize("metodo,ruta", ESCRITURAS)
def test_en_el_central_con_nodo_vinculado_escribir_da_409(con_nodo_vinculado, metodo, ruta):
    r = con_nodo_vinculado.request(metodo, ruta, json={})
    assert r.status_code == 409, f"{metodo} {ruta}: {r.status_code} {r.text}"
    assert r.json()["detail"]["codigo"] == "solo_en_el_nodo"
    assert "se carga en el equipo de la oficina" in r.json()["detail"]["mensaje"]


def test_la_web_consulta_todo_con_un_nodo_vinculado(con_nodo_vinculado):
    for ruta in LECTURAS:
        r = con_nodo_vinculado.get(ruta)
        assert r.status_code == 200, f"GET {ruta}: {r.status_code} {r.text}"


def test_lo_que_manda_el_central_se_sigue_cargando_en_el_central(con_nodo_vinculado, datos):
    """Los maestros y la configuración no son del nodo: la web los sigue escribiendo (y bajan por el espejo)."""
    from tests.conftest import cargar_empresa

    c = con_nodo_vinculado
    cargar_empresa(c)
    assert c.post("/api/terceros", json={"razon_social": "Cliente Nuevo", "es_cliente": True}).status_code == 201
    assert c.post("/api/localidades", json={"nombre": "Pergamino"}).status_code == 201
    assert c.post("/api/choferes", json={"nombre": "Chofer Nuevo"}).status_code == 201
    assert c.put("/api/cartas-porte/emision/habilitada", json={"habilitada": True}).status_code == 200


def test_sin_nodo_vinculado_la_web_opera_como_hoy_y_al_dar_de_baja_el_nodo_vuelve_a_operar(cliente, datos):
    cuerpo = {"fecha": "2026-10-20", "cliente_id": datos["cliente"], "origen_id": datos["origen"],
              "destino_id": datos["destino"], "tarifa": "1000.00"}
    assert offline.hay_nodo_vinculado() is False
    assert cliente.post("/api/ordenes", json=cuerpo).status_code == 201
    with core.get_connection() as conn:
        aprov.registrar(conn, offline.aprovisionamiento, "oficina-1", sucursal="1")
    assert cliente.post("/api/ordenes", json=cuerpo).status_code == 409
    with core.get_connection() as conn:
        aprov.dar_de_baja(conn, "oficina-1", salida=lambda *_: None)
    assert offline.hay_nodo_vinculado() is False, "un nodo dado de baja no cuenta"
    assert cliente.post("/api/ordenes", json=cuerpo).status_code == 201
    assert cliente.get("/api/ordenes").status_code == 200


def test_el_409_no_depende_de_que_el_nodo_este_en_linea(con_nodo_vinculado):
    # `solo_en_el_nodo` no se arregla esperando: la web no tiene esa función mientras haya un nodo, esté en línea o no.
    assert con_nodo_vinculado.post("/api/caja", json={}).status_code == 409


# ── El nodo: lo que manda el central es de sólo lectura ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("metodo,ruta", [
    ("POST", "/api/localidades"), ("PUT", "/api/localidades/1"), ("POST", "/api/choferes"), ("POST", "/api/vehiculos"),
    ("POST", "/api/tipos-carga"), ("PUT", "/api/terceros/1"), ("DELETE", "/api/terceros/1"),
    ("POST", "/api/terceros/1/roles/cliente"), ("PUT", "/api/configuracion"), ("POST", "/api/tarifario"),
    ("POST", "/api/usuarios"), ("PUT", "/api/arca"), ("POST", "/api/arca/certificado"),
    ("PUT", "/api/cartas-porte/emision/habilitada"), ("POST", "/api/cartas-porte/titulares"),
    ("PUT", "/api/cartas-porte/refresco/habilitado"),
])
def test_en_el_nodo_los_maestros_y_la_configuracion_son_del_central(escenario, metodo, ruta):
    r = escenario.cliente.request(metodo, ruta, json={})
    assert r.status_code == 409, f"{metodo} {ruta}: {r.status_code} {r.text}"
    assert r.json()["detail"]["codigo"] == "solo_en_el_central"


def test_en_el_nodo_se_da_de_alta_un_tercero_y_se_corrige_mientras_es_provisorio(escenario):
    c = escenario.cliente
    r = c.post("/api/terceros", json={"razon_social": "Cliente Nuevo", "es_cliente": True})
    assert r.status_code == 201 and r.json()["id"] < 0
    nuevo = r.json()["id"]
    assert c.put(f"/api/terceros/{nuevo}", json={"razon_social": "Cliente Nuevo SA", "es_cliente": True}
                 ).status_code == 200
    assert c.post(f"/api/terceros/{nuevo}/roles/fletero").status_code == 200
    # Uno del central (con su id definitivo) no se toca desde el nodo.
    existente = escenario.datos["cliente"]
    assert c.put(f"/api/terceros/{existente}", json={"razon_social": "X", "es_cliente": True}).status_code == 409
    # Y todo lo demás que se lee sigue andando.
    assert c.get("/api/terceros").status_code == 200 and c.get("/api/localidades").status_code == 200


def test_el_refresco_de_cartas_de_porte_no_corre_en_el_central_con_un_nodo_vinculado(con_nodo_vinculado, sesion):
    from app.servicios import refresco_cpe

    resultado = refresco_cpe.correr(sesion)
    assert resultado["estado"] == "omitido" and "nodo vinculado" in resultado["motivo"]
