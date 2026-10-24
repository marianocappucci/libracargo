"""Lo que escribe la oficina sube al central, y el central lo materializa con sus ids definitivos (ADR-056).

Un nodo y su central con **dos bases** (`escenario`, ver `tests/nodo_apoyo.py`): lo que el nodo hace por la API de
siempre queda en su outbox como operaciones `cargo.*` (más `caja.movimiento` y `caja.movimiento_anulado` del motor), y
el receptor de LibraEdge del central las aplica con el despachador real del producto. Cada test mira las dos puntas:
lo que quedó encolado en el nodo y lo que quedó escrito en el central.
"""
from __future__ import annotations

from decimal import Decimal

from libracore.db import core

from app.routers.sincronizacion_offline import despachador


def orden(e, **extra):
    d = e.datos
    cuerpo = {"fecha": "2026-10-20", "cliente_id": d["cliente"], "origen_id": d["origen"],
              "destino_id": d["destino"], "fletero_id": d["fletero"], "tarifa": "1000.00", "comision": "100.00"}
    cuerpo.update(extra)
    r = e.cliente.post("/api/ordenes", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def cobro(e, **extra):
    cuerpo = {"fecha": "2026-10-21", "tipo": "ingreso", "concepto": "Cobro", "importe": "5000.00",
              "tercero_id": e.datos["cliente"], "rol": "cliente", "descripcion": "Cheque 77", "recibo": "0001-0000077"}
    cuerpo.update(extra)
    r = e.cliente.post("/api/caja", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def saldo(e, rol, tercero_id, *, central=False):
    consulta = ("SELECT COALESCE(SUM(debe), 0) - COALESCE(SUM(haber), 0) FROM cc_asientos "
                "WHERE rol = ? AND tercero_id = ?")
    filas = e.sql_central(consulta, rol, tercero_id) if central else e.sql_nodo(consulta, rol, tercero_id)
    return Decimal(str(filas[0][0]))


# ── La orden ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_la_orden_cargada_en_el_nodo_nace_con_id_provisorio_y_queda_en_el_outbox(escenario):
    o = orden(escenario)
    assert o["id"] < 0, "un id del central es siempre positivo: el del nodo es negativo hasta que el central lo asigne"
    operaciones = escenario.pendientes()
    assert [op.operation_type for op in operaciones] == ["cargo.orden", "cargo.asiento"]
    foto = operaciones[0].payload
    assert foto["id"] == o["id"] and foto["version"] == 1
    assert foto["valores"]["tarifa"] == "1000.00" and foto["valores"]["estado"] == "pendiente"
    assert foto["comprobante"] is None
    # El asiento del fletero (la comisión) viaja con la orden a la que pertenece, y después de ella.
    asiento = operaciones[1].payload
    assert asiento["refs"]["orden_id"] == o["id"]
    assert asiento["valores"]["rol"] == "fletero" and asiento["valores"]["debe"] == "100.00"


def test_el_central_materializa_la_orden_con_su_id_definitivo(escenario):
    o = orden(escenario)
    escenario.subir_todo_y_exigir()

    filas = escenario.sql_central("SELECT id, tarifa, estado FROM ordenes_carga")
    assert len(filas) == 1
    id_central, tarifa, estado = filas[0]
    assert id_central > 0 and id_central != o["id"], "el central le asigna su propio id"
    assert (Decimal(str(tarifa)), estado) == (Decimal("1000.00"), "pendiente")
    # El mapeo `(nodo, tabla, id_nodo) -> id_central` queda anotado: es lo que traduce las referencias que vengan
    # después.
    assert escenario.sql_central(
        "SELECT id_central FROM libraedge_mapeo WHERE node_id = ? AND tabla = 'ordenes_carga' AND id_nodo = ?",
        "oficina-1", o["id"]) == [(id_central,)]
    # Y el asiento del fletero cuelga de la orden del central, no de la del nodo.
    assert escenario.sql_central(
        "SELECT c.orden_id, a.rol, c.origen_nodo FROM cc_asientos a "
        "JOIN movimientos_cuenta_cargo c ON c.asiento_id = a.id") == [(id_central, "fletero", "oficina-1")]
    assert saldo(escenario, "fletero", escenario.datos["fletero"], central=True) == Decimal("100.00")


def test_aplicar_dos_veces_lo_mismo_deja_una_sola_orden_y_un_solo_asiento(escenario):
    orden(escenario)
    operaciones = escenario.pendientes()
    escenario.subir_todo_y_exigir()
    # El outbox entrega al menos una vez: el receptor dice «duplicate»...
    assert {r.result for _, r in escenario.subir(operaciones)} == {"duplicate"}
    # ...y, si la misma operación llegara por otro camino (una revisión manual que se reintenta), cada aplicador tampoco
    # duplica: se llama al despachador directo, sin pasar por la deduplicación del receptor.
    with escenario.en_el_central():
        conn = core.conectar(escenario.url_central)
        try:
            for op in operaciones:
                despachador(conn, op)
            conn.commit()
        finally:
            conn.close()
    assert escenario.sql_central("SELECT COUNT(*) FROM ordenes_carga") == [(1,)]
    assert escenario.sql_central("SELECT COUNT(*) FROM cc_asientos") == [(1,)]


def test_editar_la_orden_en_el_nodo_sube_la_foto_nueva_y_corrige_el_asiento_del_central(escenario):
    o = orden(escenario)
    escenario.subir_todo_y_exigir()
    r = escenario.cliente.put(f"/api/ordenes/{o['id']}", json={
        "fecha": "2026-10-20", "cliente_id": escenario.datos["cliente"], "origen_id": escenario.datos["origen"],
        "destino_id": escenario.datos["destino"], "fletero_id": escenario.datos["fletero"], "tarifa": "2000.00",
        "comision": "250.00"})
    assert r.status_code == 200, r.text
    assert escenario.tipos_pendientes() == ["cargo.orden", "cargo.asiento"]
    escenario.subir_todo_y_exigir()

    assert escenario.sql_central("SELECT COUNT(*), MAX(tarifa) FROM ordenes_carga") == [(1, Decimal("2000.00"))]
    assert saldo(escenario, "fletero", escenario.datos["fletero"], central=True) == Decimal("250.00")
    assert saldo(escenario, "fletero", escenario.datos["fletero"]) == Decimal("250.00")


def test_anular_la_orden_deja_en_el_central_las_dos_lineas_igual_que_en_el_nodo(escenario):
    o = orden(escenario)
    escenario.subir_todo_y_exigir()
    assert escenario.cliente.delete(f"/api/ordenes/{o['id']}").status_code == 200
    escenario.subir_todo_y_exigir()

    assert escenario.sql_central("SELECT estado FROM ordenes_carga") == [("anulada",)]
    assert escenario.sql_central("SELECT COUNT(*) FROM cc_asientos") == [(2,)]
    assert saldo(escenario, "fletero", escenario.datos["fletero"], central=True) == Decimal("0")


def test_una_orden_que_cambia_dos_veces_en_la_misma_transaccion_sube_una_sola_foto(escenario):
    o = orden(escenario)
    escenario.subir_todo_y_exigir()
    # Cambiar la etapa no toca el asiento: sólo sube la orden.
    r = escenario.cliente.put(f"/api/ordenes/{o['id']}/etapa", json={"etapa": "en_viaje"})
    assert r.status_code == 200, r.text
    assert escenario.tipos_pendientes() == ["cargo.orden"]
    escenario.subir_todo_y_exigir()
    assert escenario.sql_central("SELECT etapa FROM ordenes_carga") == [("en_viaje",)]


# ── La caja ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_el_movimiento_de_caja_sube_con_lo_propio_en_extra_y_la_hija_se_crea_en_el_central(escenario):
    m = cobro(escenario)
    operaciones = escenario.pendientes()
    assert [op.operation_type for op in operaciones] == ["caja.movimiento", "cargo.asiento"]
    extra = operaciones[0].payload["extra"]
    assert extra == {"tercero_id": escenario.datos["cliente"], "descripcion": "Cheque 77", "recibo": "0001-0000077"}
    assert Decimal(str(operaciones[0].payload["monto"])) == Decimal("5000")

    escenario.subir_todo_y_exigir()
    filas = escenario.sql_central(
        "SELECT m.id, m.origen, m.origen_id, h.movimiento_id, h.tercero_id, h.descripcion, h.recibo "
        "FROM caja_movimientos m JOIN movimientos_caja_cargo h ON h.movimiento_id = m.id")
    assert filas == [(filas[0][0], "oficina-1", m["id"], filas[0][0], escenario.datos["cliente"], "Cheque 77",
                      "0001-0000077")], "la fila propia lleva el mismo id que la del motor, creada por `al_aplicar`"
    # La contrapartida llegó como asiento, vinculada al movimiento del central.
    assert escenario.sql_central(
        "SELECT c.movimiento_caja_id FROM movimientos_cuenta_cargo c") == [(filas[0][0],)]
    assert saldo(escenario, "cliente", escenario.datos["cliente"], central=True) == Decimal("-5000.00")


def test_anular_el_movimiento_sube_la_anulacion_y_la_reversion_de_la_cuenta(escenario):
    m = cobro(escenario)
    escenario.subir_todo_y_exigir()
    assert escenario.cliente.delete(f"/api/caja/{m['id']}").status_code == 200
    assert escenario.tipos_pendientes() == ["caja.movimiento_anulado", "cargo.asiento"]
    escenario.subir_todo_y_exigir()

    assert escenario.sql_central("SELECT anulado FROM caja_movimientos") == [(1,)]
    assert saldo(escenario, "cliente", escenario.datos["cliente"], central=True) == Decimal("0")
    assert saldo(escenario, "cliente", escenario.datos["cliente"]) == Decimal("0")


def test_corregir_un_movimiento_en_el_nodo_es_anular_y_cargar_de_nuevo(escenario):
    m = cobro(escenario)
    escenario.subir_todo_y_exigir()
    r = escenario.cliente.put(f"/api/caja/{m['id']}", json={
        "fecha": "2026-10-21", "tipo": "ingreso", "concepto": "Cobro", "importe": "1.00"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_central"
    assert escenario.pendientes() == []
    escenario.cliente.delete(f"/api/caja/{m['id']}")
    cobro(escenario, importe="4000.00")
    escenario.subir_todo_y_exigir()
    assert saldo(escenario, "cliente", escenario.datos["cliente"], central=True) == Decimal("-4000.00")


def test_un_movimiento_sin_tercero_sube_sin_asiento(escenario):
    m = escenario.cliente.post("/api/caja", json={
        "fecha": "2026-10-21", "tipo": "egreso", "concepto": "Gasto general", "importe": "300.00"})
    assert m.status_code == 201, m.text
    assert escenario.tipos_pendientes() == ["caja.movimiento"]
    escenario.subir_todo_y_exigir()
    assert escenario.sql_central("SELECT COUNT(*) FROM caja_movimientos") == [(1,)]
    assert escenario.sql_central("SELECT tercero_id FROM movimientos_caja_cargo") == [(None,)]


# ── Los asientos ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_el_asiento_sube_con_su_origen_y_el_central_lo_reconoce(escenario):
    orden(escenario)
    escenario.subir_todo_y_exigir()
    filas = escenario.sql_central("SELECT origen_nodo, origen_nodo_id FROM movimientos_cuenta_cargo")
    nodo = escenario.sql_nodo("SELECT asiento_id FROM movimientos_cuenta_cargo")
    assert filas == [("oficina-1", nodo[0][0])]


def test_sacarle_la_comision_a_la_orden_borra_el_asiento_tambien_en_el_central(escenario):
    o = orden(escenario)
    escenario.subir_todo_y_exigir()
    assert escenario.sql_central("SELECT COUNT(*) FROM cc_asientos") == [(1,)]
    r = escenario.cliente.put(f"/api/ordenes/{o['id']}", json={
        "fecha": "2026-10-20", "cliente_id": escenario.datos["cliente"], "origen_id": escenario.datos["origen"],
        "destino_id": escenario.datos["destino"], "fletero_id": escenario.datos["fletero"], "tarifa": "1000.00",
        "comision": "0"})
    assert r.status_code == 200, r.text
    assert "cargo.asiento" in escenario.tipos_pendientes()
    escenario.subir_todo_y_exigir()
    assert escenario.sql_central("SELECT COUNT(*) FROM cc_asientos") == [(0,)]


# ── Gastos y adjuntos ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_un_gasto_de_proveedor_sube_con_sus_dos_asientos(escenario):
    proveedor = escenario.cliente.post("/api/terceros", json={"razon_social": "Gomería Norte", "es_proveedor": True})
    assert proveedor.status_code == 201
    # El proveedor se creó en el nodo: id provisorio que el central tiene que mapear antes del gasto.
    assert proveedor.json()["id"] < 0
    r = escenario.cliente.post("/api/gastos", json={
        "fecha": "2026-10-22", "proveedor_id": proveedor.json()["id"], "fletero_id": escenario.datos["fletero"],
        "descripcion": "Cubiertas", "importe": "800.00"})
    assert r.status_code == 201, r.text
    assert escenario.tipos_pendientes() == ["cargo.tercero", "cargo.gasto", "cargo.asiento", "cargo.asiento"]
    escenario.subir_todo_y_exigir()
    assert escenario.sql_central("SELECT COUNT(*) FROM gastos_de_proveedor") == [(1,)]
    assert escenario.sql_central("SELECT COUNT(*) FROM cc_asientos WHERE concepto <> ''") == [(2,)]
    proveedor_central = escenario.sql_central("SELECT id FROM terceros WHERE razon_social = 'Gomería Norte'")[0][0]
    assert proveedor_central > 0
    assert saldo(escenario, "proveedor", proveedor_central, central=True) == Decimal("800.00")


def test_el_adjunto_de_una_orden_viaja_con_su_contenido(escenario):
    o = orden(escenario)
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    r = escenario.cliente.post(f"/api/ordenes/{o['id']}/adjuntos", files={"archivo": ("ticket.png", png, "image/png")})
    assert r.status_code == 201, r.text
    assert "cargo.adjunto" in escenario.tipos_pendientes()
    escenario.subir_todo_y_exigir()
    filas = escenario.sql_central("SELECT nombre, tamanio, octet_length(contenido) FROM ordenes_adjuntos")
    assert filas == [("ticket.png", len(png), len(png))]
    adjunto = r.json()["id"]
    assert escenario.cliente.delete(f"/api/ordenes/{o['id']}/adjuntos/{adjunto}").status_code == 204
    escenario.subir_todo_y_exigir()
    assert escenario.sql_central("SELECT COUNT(*) FROM ordenes_adjuntos") == [(0,)]


# ── Los terceros que se dan de alta en el nodo ────────────────────────────────────────────────────────────────────────


def test_un_cliente_nuevo_cargado_en_el_nodo_se_materializa_y_la_orden_apunta_al_definitivo(escenario):
    r = escenario.cliente.post("/api/terceros", json={"razon_social": "Cereales del Oeste", "es_cliente": True})
    assert r.status_code == 201, r.text
    nuevo = r.json()["id"]
    assert nuevo < 0
    o = orden(escenario, cliente_id=nuevo)
    assert escenario.tipos_pendientes()[:2] == ["cargo.tercero", "cargo.orden"], "el tercero llega antes que su orden"
    escenario.subir_todo_y_exigir()

    definitivo = escenario.sql_central("SELECT id FROM terceros WHERE razon_social = 'Cereales del Oeste'")[0][0]
    assert definitivo > 0
    assert escenario.sql_central("SELECT cliente_id FROM ordenes_carga") == [(definitivo,)]
    assert o["id"] < 0


def test_el_central_no_duplica_un_tercero_con_el_mismo_cuit_y_le_suma_el_rol(escenario):
    # El nodo da de alta un fletero con un CUIT que el central ya tiene como cliente (lo cargó otro mientras tanto: el
    # espejo del nodo todavía no lo trajo).
    r = escenario.cliente.post("/api/terceros", json={
        "razon_social": "Agro del Centro (fletes)", "es_fletero": True, "cuit": "30-99999999-9"})
    assert r.status_code == 201, r.text
    with escenario.en_el_central():
        conn = core.conectar(escenario.url_central)
        try:
            conn.execute(
                "INSERT INTO terceros (razon_social, cuit, condicion_iva, es_cliente, es_fletero, es_proveedor, "
                "activo) VALUES ('Agro del Centro', '30-99999999-9', 'consumidor_final', true, false, false, true)")
            conn.commit()
        finally:
            conn.close()
    escenario.subir_todo_y_exigir()
    filas = escenario.sql_central(
        "SELECT razon_social, es_cliente, es_fletero FROM terceros WHERE replace(cuit, '-', '') = '30999999999'")
    assert filas == [("Agro del Centro", True, True)], "una sola entidad con los dos roles (ADR-040)"
    nuevo = r.json()["id"]
    assert escenario.sql_central(
        "SELECT id_central FROM libraedge_mapeo WHERE tabla = 'terceros' AND id_nodo = ?", nuevo
    ) == [(escenario.sql_central("SELECT id FROM terceros WHERE cuit = '30-99999999-9'")[0][0],)]
