"""Las facturas y las CPE sin red quedan en cola y se emiten solas al volver la conexión (ADR-056).

Decisión del humano (2026-10-22): sin internet, la oficina **pide** la factura o la carta de porte y el pedido queda
en la cola de ARCA del motor (libracore ADR-079); al volver la conexión sale **una sola vez**, con el número de ARCA
pedido con el ticket que presta el central. Acá se prueba lo del producto —los emisores, el pedido desde la API, el
interruptor de la emisión real de CPE y lo que sube al central— sobre un nodo y su central (`escenario`); ARCA y el
ticket son dobles.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from libracore import arca_wscpe
from libracore.cola_arca import procesar_cola
from libracore.db import core
from libracore.fechas import hoy

from app import offline
from tests.conftest import arca_responde
from tests.nodo_apoyo import ticket_de_prueba
from tests.test_cartas_porte import cpe
from tests.test_emision_cpe import TITULAR, _datos, arca  # noqa: F401  (`arca` es un fixture)


def vuelve_la_conexion(escenario):
    escenario.en_linea(True)
    return asyncio.run(procesar_cola(offline.cola()))


def orden(e, *, fecha="2026-10-20", tarifa="1000.00", cliente=None):
    d = e.datos
    r = e.cliente.post("/api/ordenes", json={
        "fecha": fecha, "cliente_id": cliente or d["cliente"], "origen_id": d["origen"], "destino_id": d["destino"],
        "tarifa": tarifa})
    assert r.status_code == 201, r.text
    return r.json()


def facturar(e, ordenes, *, fecha="2026-10-20", tipo="factura_a"):
    return e.cliente.post("/api/comprobantes/desde-ordenes", json={
        "fecha": fecha, "cliente_id": e.datos["cliente"], "tipo": tipo, "orden_ids": [o["id"] for o in ordenes]})


def pedidos(e, tipo="documento"):
    return e.sql_nodo("SELECT estado, origen_tipo, ultimo_error FROM cola_arca WHERE origen_tipo = ? ORDER BY id", tipo)


@pytest.fixture
def con_arca(escenario, monkeypatch):
    """ARCA y el ticket prestado, simulados: lo que se le pidió a ARCA queda en `pedidos`."""
    escenario.arca = arca_responde(monkeypatch)
    escenario.tickets = ticket_de_prueba(monkeypatch)
    return escenario


# ── La factura ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_sin_conexion_la_factura_queda_en_cola_y_no_sale_a_arca(con_arca):
    e = con_arca
    o = orden(e)
    r = facturar(e, [o])
    assert r.status_code == 202, r.text
    cuerpo = r.json()
    assert cuerpo["codigo"] == "en_cola" and cuerpo["estado"] == "esperando"
    assert "al volver la conexión" in cuerpo["mensaje"]
    # La forma única del 202 (libracore ADR-084): la unión de la de antes y la que lee el kit (`esRespuestaEnCola`).
    assert set(cuerpo) == {"en_cola", "codigo", "estado", "pedido_id", "mensaje", "motivo"}
    assert cuerpo["en_cola"] is True and cuerpo["pedido_id"] == e.sql_nodo("SELECT id FROM cola_arca")[0][0]
    assert pedidos(e)[0][:2] == ("esperando", "documento")
    assert e.arca == [] and e.tickets == [], "sin conexión no se llama a ARCA ni se le pide el ticket al central"
    assert e.sql_nodo("SELECT estado, comprobante_id FROM ordenes_carga") == [("pendiente", None)]
    assert e.sql_nodo("SELECT COUNT(*) FROM facturas") == [(0,)]


def test_al_volver_la_conexion_se_emite_una_sola_vez_con_el_numero_de_arca(con_arca):
    e = con_arca
    o = orden(e, fecha="2026-10-20")
    facturar(e, [o])
    salida = vuelve_la_conexion(e)
    assert [x["origen_tipo"] for x in salida["emitidos"]] == ["documento"] and salida["quedan"] == 0

    # Factura A, punto de venta 1, el número que dio ARCA y la fecha del hecho: ARCA todavía la admite (hasta 5 días).
    assert e.sql_nodo("SELECT tipo, punto_venta, numero, cae, fecha FROM facturas") == [
        (1, 1, 1, "75123456789012", "2026-10-20")]
    assert e.sql_nodo("SELECT estado FROM ordenes_carga") == [("facturada",)]
    assert len([p for p in e.arca if p[0] == "cae"]) == 1
    assert {s for s, _ in e.tickets} == {"wsfe"}, "el ticket de facturación lo presta el central"

    # Una segunda vuelta no emite otra: el pedido ya está emitido.
    assert vuelve_la_conexion(e)["emitidos"] == []
    assert e.sql_nodo("SELECT COUNT(*) FROM facturas") == [(1,)]
    assert len([p for p in e.arca if p[0] == "cae"]) == 1
    assert pedidos(e)[0][0] == "emitido"


def test_la_factura_emitida_sube_al_central_con_su_numero_y_su_cae(con_arca):
    e = con_arca
    o = orden(e)
    facturar(e, [o])
    vuelve_la_conexion(e)
    tipos = e.tipos_pendientes()
    # La orden sube dos veces: cuando se cargó y cuando se facturó. La segunda va después de su comprobante.
    despues_del_comprobante = tipos[tipos.index("cargo.comprobante"):]
    assert despues_del_comprobante[:2] == ["cargo.comprobante", "cargo.orden"], "el comprobante va antes que su orden"
    assert "cola.pedido" in tipos and "cargo.asiento" in tipos
    e.subir_todo_y_exigir()

    assert e.sql_central("SELECT tipo, punto_venta, numero, cae, total FROM facturas") == [
        (1, 1, 1, "75123456789012", Decimal("1210.00"))]
    assert e.sql_central("SELECT o.estado, f.numero FROM ordenes_carga o "
                         "JOIN facturas f ON f.id = o.comprobante_id") == [("facturada", 1)]
    assert e.sql_central("SELECT cliente_id, anulado, sin_ordenes FROM comprobantes_cargo") == [
        (e.datos["cliente"], False, False)]
    # La cuenta del cliente: lo mismo que en el nodo.
    consulta = "SELECT COALESCE(SUM(debe), 0) - COALESCE(SUM(haber), 0) FROM cc_asientos WHERE rol = 'cliente'"
    assert Decimal(str(e.sql_central(consulta)[0][0])) == Decimal(str(e.sql_nodo(consulta)[0][0])) == Decimal("1210.00")
    # Y el estado del pedido, para que la web lo consulte («la web consulta»).
    assert e.sql_central("SELECT origen_tipo, estado FROM cola_arca") == [("documento", "emitido")]


def test_con_conexion_la_factura_sale_en_el_momento(con_arca):
    e = con_arca
    e.en_linea(True)
    o = orden(e)
    r = facturar(e, [o], fecha=hoy().isoformat())
    assert r.status_code == 201, r.text
    assert r.json()["cae"] == "75123456789012" and r.json()["numero"] == 1
    assert pedidos(e)[0][0] == "emitido"


def test_dos_pedidos_por_las_mismas_ordenes_no_se_encolan(con_arca):
    e = con_arca
    o = orden(e)
    assert facturar(e, [o]).status_code == 202
    segundo = facturar(e, [o])
    assert segundo.status_code == 409 and "ya están en un pedido de factura" in segundo.json()["detail"]
    assert len(pedidos(e)) == 1


def test_un_pedido_que_ya_se_sabe_invalido_no_se_encola(con_arca):
    e = con_arca
    ajena = orden(e, cliente=e.datos["otro_cliente"])
    assert facturar(e, [ajena]).status_code == 422          # de otro cliente
    assert facturar(e, [{"id": 999999}]).status_code == 404  # no existe
    assert pedidos(e) == []


def test_la_factura_directa_tambien_va_por_la_cola(con_arca):
    e = con_arca
    r = e.cliente.post("/api/comprobantes/directa", json={
        "fecha": "2026-10-20", "cliente_id": e.datos["cliente"], "tipo": "factura_b",
        "conceptos": [{"descripcion": "Estadía", "cantidad": "2", "precio_unitario": "500.00"}]})
    assert r.status_code == 202, r.text
    salida = vuelve_la_conexion(e)
    assert len(salida["emitidos"]) == 1
    assert e.sql_nodo("SELECT total, cae FROM facturas") == [(Decimal("1210.00"), "75123456789012")]
    e.subir_todo_y_exigir()
    assert e.sql_central("SELECT sin_ordenes FROM comprobantes_cargo") == [(True,)]


def test_la_fecha_es_la_del_hecho_si_arca_la_admite_y_la_de_hoy_si_no(con_arca):
    e = con_arca
    reciente, vieja = hoy() - timedelta(days=2), hoy() - timedelta(days=30)
    for fecha in (reciente, vieja):
        facturar(e, [orden(e, fecha=fecha.isoformat())], fecha=fecha.isoformat())
    vuelve_la_conexion(e)
    fechas = [f[0] for f in e.sql_nodo("SELECT fecha FROM facturas ORDER BY numero")]
    # Una factura de hace 2 días sale con esa fecha; una de hace 30 (fuera del plazo de ARCA) sale con la de hoy, y
    # nunca antes que la última de la serie.
    assert fechas == [reciente.isoformat(), hoy().isoformat()]


def test_el_pedido_de_un_cliente_nuevo_sigue_valiendo_cuando_baja_su_id_definitivo(con_arca):
    """El cliente se dio de alta en el nodo (id provisorio) y el pedido de factura lo guardó dentro de su JSON. Cuando
    el central le asigna el suyo, LibraEdge reapunta las filas pero no el JSON de la cola: el emisor lo resuelve con
    el mapeo."""
    from libraedge.sync.reconciliacion import reapuntar

    e = con_arca
    nuevo = e.cliente.post("/api/terceros", json={
        "razon_social": "Cereales del Oeste", "es_cliente": True, "cuit": "30-71234567-1",
        "condicion_iva": "responsable_inscripto"}).json()["id"]
    assert nuevo < 0
    r = e.cliente.post("/api/comprobantes/directa", json={
        "fecha": "2026-10-20", "cliente_id": nuevo, "tipo": "factura_a",
        "conceptos": [{"descripcion": "Estadía", "cantidad": "1", "precio_unitario": "1000.00"}]})
    assert r.status_code == 202, r.text

    # Lo que hace el espejo al bajar el definitivo (libraedge ADR-021): llega la fila del central, el mapeo, y reapunta.
    with core.get_connection() as conn:
        conn.execute(
            "INSERT INTO terceros (id, razon_social, cuit, condicion_iva, es_cliente, es_fletero, es_proveedor, "
            "activo) SELECT 9001, razon_social, cuit, condicion_iva, es_cliente, es_fletero, es_proveedor, activo "
            "FROM terceros WHERE id = ?", (nuevo,))
        conn.execute("INSERT INTO libraedge_mapeo (node_id, tabla, id_nodo, id_central, creado_at) "
                     "VALUES ('oficina-1', 'terceros', ?, 9001, '2026-10-24')", (nuevo,))
        assert reapuntar(conn, "terceros", nuevo, 9001) == "hecho"
        conn.commit()
    assert e.sql_nodo("SELECT COUNT(*) FROM terceros WHERE id = ?", nuevo) == [(0,)]

    salida = vuelve_la_conexion(e)
    assert len(salida["emitidos"]) == 1, salida
    assert e.sql_nodo("SELECT c.cliente_id FROM comprobantes_cargo c") == [(9001,)]


def test_si_arca_rechaza_el_pedido_queda_a_revisar_y_no_deja_nada(con_arca, monkeypatch):
    e = con_arca
    e.arca = arca_responde(monkeypatch, falla_cae="CAE rechazado")
    o = orden(e)
    facturar(e, [o])
    salida = vuelve_la_conexion(e)
    assert [x["error"] for x in salida["a_revisar"]] and "rechazo" in salida["a_revisar"][0]["error"].lower()
    assert e.sql_nodo("SELECT COUNT(*) FROM facturas") == [(0,)]
    assert e.sql_nodo("SELECT estado FROM ordenes_carga") == [("pendiente",)]
    # No se reintenta solo: sigue a revisar.
    assert vuelve_la_conexion(e)["emitidos"] == []
    assert pedidos(e)[0][0] == "a_revisar"


def test_el_central_que_no_presta_el_ticket_deja_el_pedido_esperando(escenario, monkeypatch):
    e = escenario
    e.arca = arca_responde(monkeypatch)
    ticket_de_prueba(monkeypatch, falla=offline.RechazoDelCentral("El central no tiene el certificado de ARCA."))
    o = orden(e)
    facturar(e, [o])
    salida = vuelve_la_conexion(e)
    assert salida["emitidos"] == [] and salida["errores"], "se informa y no se pierde"
    assert pedidos(e)[0][0] == "esperando" and "certificado" in pedidos(e)[0][2]
    assert e.arca == [], "nunca se numera local: ni siquiera se le pidió el número a ARCA"


def test_contra_homologacion_se_corre_todo_y_se_revierte_sin_pasar_por_la_cola(con_arca):
    e = con_arca
    with core.get_connection() as conn:   # la configuración de ARCA baja por el espejo: acá, la del ambiente de pruebas
        conn.execute("UPDATE arca_config SET ambiente = 'homologacion'")
        conn.commit()
    e.en_linea(True)
    o = orden(e)
    r = facturar(e, [o], fecha=hoy().isoformat())
    assert r.status_code == 200 and r.json()["ensayo"] is True, r.text
    assert pedidos(e) == [] and e.sql_nodo("SELECT COUNT(*) FROM facturas") == [(0,)]
    assert e.sql_nodo("SELECT estado FROM ordenes_carga") == [("pendiente",)], "el ensayo no cierra la orden"


def test_las_notas_necesitan_internet_y_no_se_encolan(con_arca):
    e = con_arca
    e.en_linea(True)
    o = orden(e)
    comprobante = facturar(e, [o], fecha=hoy().isoformat()).json()
    e.en_linea(False)
    r = e.cliente.post(f"/api/comprobantes/{comprobante['id']}/nota-de-credito", json={"motivo": "Devolución total"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "sin_conexion"
    assert e.sql_nodo("SELECT COUNT(*) FROM facturas") == [(1,)]
    e.en_linea(True)
    r = e.cliente.post(f"/api/comprobantes/{comprobante['id']}/nota-de-credito", json={"motivo": "Devolución total"})
    assert r.status_code == 201, r.text
    assert e.sql_nodo("SELECT COUNT(*) FROM facturas") == [(2,)]


# ── La carta de porte ─────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def referencia_extra(cliente):
    """Los maestros de una CPE, cargados antes de copiar la base al central (en el nodo bajan por el espejo): cliente y
    fletero con CUIT, chofer, vehículo y dos localidades de la provincia de Buenos Aires."""
    def alta(ruta, cuerpo):
        r = cliente.post(ruta, json=cuerpo)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    flet = alta("/api/terceros", {"razon_social": "Fletero Prueba", "cuit": "20-12345678-6", "es_fletero": True})
    return {
        "cliente_cpe": alta("/api/terceros", {"razon_social": "Agro Titular SA", "cuit": "30-87654321-0",
                                              "es_cliente": True}),
        "fletero_cpe": flet,
        "chofer": alta("/api/choferes", {"nombre": "Chofer Prueba", "cuit": "20-11111111-2", "fletero_id": flet}),
        "vehiculo": alta("/api/vehiculos", {"patente_chasis": "CTR587", "patente_acoplado": "OVY322",
                                            "fletero_id": flet}),
        "origen_cpe": alta("/api/localidades", {"nombre": "Suipacha", "provincia": "Buenos Aires"}),
        "destino_cpe": alta("/api/localidades", {"nombre": "Pilar", "provincia": "Buenos Aires"}),
    }


@pytest.fixture
def con_cpe(escenario, monkeypatch, arca):  # noqa: F811
    """El nodo listo para emitir CPE: la orden completa, el ticket prestado de `wscpe` con la delegación del titular y
    el interruptor de la emisión real prendido (en el nodo lo trae el espejo de la empresa)."""
    e = escenario
    d = e.datos
    e.tickets = ticket_de_prueba(monkeypatch, relaciones_wscpe=(TITULAR,))
    e.arca = arca
    r = e.cliente.post("/api/ordenes", json={
        "fecha": "2026-10-08", "cliente_id": d["cliente_cpe"], "origen_id": d["origen_cpe"],
        "destino_id": d["destino_cpe"], "fletero_id": d["fletero_cpe"], "chofer_id": d["chofer"],
        "vehiculo_id": d["vehiculo"], "tarifa": "1000.00", "kg_bruto_carga": 45000, "kg_tara_carga": 15220,
        "km": 80, "tarifa_tonelada": "19724.73"})
    assert r.status_code == 201, r.text
    e.orden_cpe = r.json()["id"]
    e.en_linea(True)
    p = e.cliente.get("/api/cartas-porte/emision/propuesta", params={"orden_id": e.orden_cpe, "cuit_titular": TITULAR})
    assert p.status_code == 200, p.text
    e.solicitud = _datos(p.json())
    e.en_linea(False)
    prender_interruptor(e)
    return e


def prender_interruptor(e, valor=True):
    """En el nodo la empresa baja por el espejo: el interruptor lo cambia el central y llega así."""
    with core.get_connection() as conn:
        conn.execute("UPDATE configuracion_empresa SET cpe_emision_habilitada = ?", (valor,))
        conn.commit()


def pedir_cpe(e):
    return e.cliente.post("/api/cartas-porte/emision/emitir", json={
        "orden_id": e.orden_cpe, "datos": e.solicitud, "confirmo": True})


def test_sin_conexion_la_cpe_queda_en_cola_y_no_hay_cpe_valida_para_viajar(con_cpe):
    e = con_cpe
    r = pedir_cpe(e)
    assert r.status_code == 202, r.text
    assert r.json()["codigo"] == "cpe_en_cola" and "NO hay una CPE válida" in r.json()["mensaje"]
    assert r.json()["en_cola"] is True and r.json()["estado"] == "esperando"
    assert e.arca["emitidas"] == []
    assert e.sql_nodo("SELECT COUNT(*) FROM cartas_porte") == [(0,)]
    assert pedidos(e, "cpe")[0][:2] == ("esperando", "cpe")


def test_al_volver_la_conexion_la_cpe_se_emite_una_sola_vez(con_cpe):
    e = con_cpe
    pedir_cpe(e)
    salida = vuelve_la_conexion(e)
    assert [x["origen_tipo"] for x in salida["emitidos"]] == ["cpe"]
    assert len(e.arca["emitidas"]) == 1 and e.arca["emitidas"][0][2] == "produccion"
    assert e.sql_nodo("SELECT nro_ctg, emitida, orden_carga_id FROM cartas_porte") == [
        (10135099999, True, e.orden_cpe)]
    assert e.sql_nodo("SELECT COUNT(*) FROM cartas_porte_pdf") == [(1,)]
    assert "wscpe" in {s for s, _ in e.tickets}, "el ticket de wscpe lo presta el central"

    assert vuelve_la_conexion(e)["emitidos"] == []
    assert len(e.arca["emitidas"]) == 1, "una segunda vuelta no emite otra"

    e.subir_todo_y_exigir()
    assert e.sql_central("SELECT nro_ctg, emitida FROM cartas_porte") == [(10135099999, True)]
    assert e.sql_central("SELECT COUNT(*) FROM cartas_porte_pdf") == [(1,)]
    # La carta apunta a la orden del central (la del nodo era provisoria).
    assert e.sql_central("SELECT o.id FROM cartas_porte c JOIN ordenes_carga o ON o.id = c.orden_carga_id") != []
    assert e.sql_central("SELECT origen_tipo, estado FROM cola_arca WHERE origen_tipo = 'cpe'") == [("cpe", "emitido")]


def test_una_cpe_incierta_no_se_reintenta(con_cpe):
    e = con_cpe
    e.arca["emitir"] = arca_wscpe.EmisionIncierta("ARCA no contestó", sucursal=1, nro_orden=311, tipo_cpe=74)
    pedir_cpe(e)
    salida = vuelve_la_conexion(e)
    assert [x["origen_tipo"] for x in salida["inciertos"]] == ["cpe"] and salida["emitidos"] == []
    assert pedidos(e, "cpe")[0][0] == "incierto"
    # Ni la tanda automática ni otra vuelta la vuelven a emitir: reintentar con el mismo número puede chocar con una
    # carta emitida, y con el siguiente deja dos para el mismo viaje.
    e.arca["emitir"] = replace(cpe(10135099999, nro_orden=311), nro_orden=311, sucursal=1)
    assert vuelve_la_conexion(e)["emitidos"] == []
    assert len(e.arca["emitidas"]) == 1
    assert e.sql_nodo("SELECT COUNT(*) FROM cartas_porte") == [(0,)]


def test_con_el_interruptor_apagado_con_conexion_es_409_y_no_se_encola(con_cpe):
    e = con_cpe
    prender_interruptor(e, False)
    e.en_linea(True)
    r = pedir_cpe(e)
    assert r.status_code == 409 and "apagada" in r.json()["detail"]
    assert pedidos(e, "cpe") == [] and e.arca["emitidas"] == []


def test_con_el_interruptor_apagado_el_pedido_espera_y_no_se_emite(con_cpe):
    e = con_cpe
    assert pedir_cpe(e).status_code == 202          # sin conexión no se sabe el ambiente: queda en cola
    prender_interruptor(e, False)                   # un administrador lo apagó en el central mientras esperaba
    salida = vuelve_la_conexion(e)
    assert salida["emitidos"] == [] and e.arca["emitidas"] == []
    assert pedidos(e, "cpe")[0][0] == "esperando" and "apagada" in pedidos(e, "cpe")[0][2]
    # Cuando lo prenden, sale sola y una sola vez.
    prender_interruptor(e, True)
    assert len(vuelve_la_conexion(e)["emitidos"]) == 1
    assert len(e.arca["emitidas"]) == 1


def test_si_el_central_no_presta_wscpe_la_cpe_espera_con_el_motivo(con_cpe, monkeypatch):
    e = con_cpe
    ticket_de_prueba(monkeypatch, falla=offline.RechazoDelCentral("El central no tiene el certificado de wscpe."))
    pedir_cpe(e)
    salida = vuelve_la_conexion(e)
    assert salida["emitidos"] == [] and salida["errores"]
    assert pedidos(e, "cpe")[0][0] == "esperando" and "certificado de wscpe" in pedidos(e, "cpe")[0][2]
    assert e.arca["emitidas"] == []


def test_consultar_a_arca_desde_el_nodo_usa_el_ticket_prestado_y_sin_conexion_lo_dice(con_cpe):
    e = con_cpe
    e.en_linea(True)
    assert e.cliente.get("/api/cartas-porte/emision/estado").json() == {
        "ambiente": "produccion", "habilitada": True, "puede_emitir": True}
    e.en_linea(False)
    estado = e.cliente.get("/api/cartas-porte/emision/estado").json()
    assert estado["ambiente"] is None, "sin conexión no se sabe el ambiente: lo dice el ticket del central"
    r = e.cliente.get("/api/cartas-porte/representados")
    assert r.status_code == 409 and "Sin conexión con el central" in r.json()["detail"]
