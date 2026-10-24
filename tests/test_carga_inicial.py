"""La carga inicial del nodo: al vincular baja lo que el central ya tenía, una sola vez (ADR-056).

La oficina con nodo **opera** y la web **consulta**: órdenes, caja, asientos, facturas y cartas de porte no se
espejan, así que un nodo recién vinculado las tiene vacías y tiene que poder consultarlo todo sin internet.
`LIBRAEDGE_CARGA_INICIAL` (libraedge ADR-023) lo trae en un solo paso, con los **ids del central**, y deja las
secuencias donde corresponde.

Acá el **central** es la base del worker (con datos de autoridad del nodo) y el **nodo** una copia hecha antes de
cargarlos (sólo la referencia): es lo que hay el día de la vinculación.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal

import pytest
from libracore.db import core
from libracore.respaldo_postgres import con_base

from app.servicios import carga_inicial
from tests.conftest import _PG, CUIT_EMISOR, arca_responde, cargar_empresa, configurar_arca


@pytest.fixture
def central_y_nodo(cliente, engine, datos, monkeypatch):
    """El central (la base del worker) con datos de autoridad del nodo, y el nodo: una copia sin ellos."""
    r = cliente.post("/api/terceros", json={"razon_social": "Fletes del Sur SRL", "es_fletero": True})
    fletero = r.json()["id"]
    proveedor = cliente.post("/api/terceros", json={"razon_social": "Gomería Norte", "es_proveedor": True}).json()["id"]
    cargar_empresa(cliente)
    configurar_arca(cliente, cuit=CUIT_EMISOR, punto_venta=1)
    from app import db

    db.engine().dispose()
    engine.dispose()
    nombre = f"{_PG.nombre}_nodo"
    _PG._soltar(nombre)
    _PG._sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
             f"WHERE datname = '{_PG.nombre}' AND pid <> pg_backend_pid()")
    _PG._crear(nombre, plantilla=_PG.nombre)
    url_nodo = con_base(_PG.url_original, nombre)
    arca_responde(monkeypatch)
    yield {"cliente": cliente, "datos": {**datos, "fletero": fletero, "proveedor": proveedor}, "url_nodo": url_nodo}
    _PG._soltar(nombre)


def datos_del_central(c):
    """Lo que la web carga hoy: dos órdenes (una facturada), un cobro anulado y otro vigente, un gasto y un adjunto."""
    cl, d = c["cliente"], c["datos"]
    ordenes = []
    for tarifa in ("1000.00", "2500.50"):
        r = cl.post("/api/ordenes", json={
            "fecha": "2026-10-10", "cliente_id": d["cliente"], "origen_id": d["origen"], "destino_id": d["destino"],
            "fletero_id": d["fletero"], "tarifa": tarifa, "comision": "100.00"})
        assert r.status_code == 201, r.text
        ordenes.append(r.json())
    assert cl.post("/api/comprobantes/desde-ordenes", json={
        "fecha": "2026-10-10", "cliente_id": d["cliente"], "tipo": "factura_a", "orden_ids": [ordenes[0]["id"]]
    }).status_code == 201
    for importe in ("300.00", "450.25"):
        r = cl.post("/api/caja", json={
            "fecha": "2026-10-11", "tipo": "ingreso", "concepto": "Cobro", "importe": importe,
            "tercero_id": d["cliente"], "rol": "cliente", "recibo": "0001-1"})
        assert r.status_code == 201, r.text
    assert cl.delete(f"/api/caja/{r.json()['id'] - 1}").status_code == 200
    assert cl.post("/api/gastos", json={
        "fecha": "2026-10-12", "proveedor_id": d["proveedor"], "fletero_id": d["fletero"], "descripcion": "Cubiertas",
        "importe": "800.00"}).status_code == 201
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    assert cl.post(f"/api/ordenes/{ordenes[1]['id']}/adjuntos", files={"archivo": ("t.png", png, "image/png")}
                   ).status_code == 201
    return ordenes


def cuerpo_de_la_carga():
    with core.get_connection() as conn:
        return carga_inicial.carga_inicial_del_central(conn, "oficina-1", "1")


def en_el_nodo(c, funcion):
    conn = core.conectar(c["url_nodo"])
    try:
        return funcion(conn)
    finally:
        conn.close()


def filas(conn, sentencia, *params):
    return [tuple(f) for f in conn.execute(sentencia, params).fetchall()]


def test_la_carga_trae_todo_con_los_ids_del_central_y_los_importes_exactos(central_y_nodo):
    c = central_y_nodo
    datos_del_central(c)
    cuerpo = cuerpo_de_la_carga()
    assert cuerpo["formato"] == "zlib+base64" and cuerpo["version"] == 1
    esperados = cuerpo["conteos"]
    assert esperados["ordenes_carga"] == 2 and esperados["facturas"] == 1 and esperados["gastos_de_proveedor"] == 1
    assert esperados["caja_movimientos"] == 2 and esperados["ordenes_adjuntos"] == 1
    assert esperados["cc_asientos"] > 0 and esperados["movimientos_cuenta_cargo"] == esperados["cc_asientos"]

    def aplicar(conn):
        resultado = carga_inicial.aplicar_carga_inicial(conn, lambda: cuerpo)
        conn.commit()
        return resultado

    resultado = en_el_nodo(c, aplicar)
    assert resultado["hecha"] is True and resultado["conteos"] == esperados

    with core.get_connection() as central:
        for tabla, pk in (("ordenes_carga", "id"), ("cc_asientos", "id"), ("caja_movimientos", "id"),
                          ("movimientos_caja_cargo", "movimiento_id"), ("facturas", "id"),
                          ("gastos_de_proveedor", "id"), ("ordenes_adjuntos", "id")):
            consulta = f"SELECT {pk} FROM {tabla} ORDER BY {pk}"
            assert en_el_nodo(c, lambda n, q=consulta: filas(n, q)) == filas(central, consulta), tabla
        # Los importes, tal cual: sin pasar por `float`.
        assert en_el_nodo(c, lambda n: filas(n, "SELECT tarifa::text, total::text FROM ordenes_carga ORDER BY id")) == \
            filas(central, "SELECT tarifa::text, total::text FROM ordenes_carga ORDER BY id")
        assert en_el_nodo(c, lambda n: filas(n, "SELECT debe::text, haber::text FROM cc_asientos ORDER BY id")) == \
            filas(central, "SELECT debe::text, haber::text FROM cc_asientos ORDER BY id")
    # El contenido binario del adjunto bajó entero.
    assert en_el_nodo(c, lambda n: filas(n, "SELECT octet_length(contenido) FROM ordenes_adjuntos")) == [(40,)]


def test_lo_que_dice_de_que_nodo_vino_una_fila_no_se_copia(central_y_nodo):
    c = central_y_nodo
    datos_del_central(c)
    with core.get_connection() as central:
        central.execute("UPDATE caja_movimientos SET origen = 'oficina-vieja', origen_id = 5 WHERE id = "
                        "(SELECT MIN(id) FROM caja_movimientos)")
        central.commit()
    cuerpo = cuerpo_de_la_carga()
    en_el_nodo(c, lambda n: (carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo), n.commit()))
    assert en_el_nodo(c, lambda n: filas(n, "SELECT COUNT(*) FROM caja_movimientos WHERE origen IS NOT NULL")) == [(0,)]
    assert en_el_nodo(c, lambda n: filas(
        n, "SELECT COUNT(*) FROM movimientos_cuenta_cargo WHERE origen_nodo IS NOT NULL")) == [(0,)]


def test_las_secuencias_siguen_al_id_mas_alto_y_al_origen_id_del_nodo_anterior(central_y_nodo):
    c = central_y_nodo
    datos_del_central(c)
    with core.get_connection() as central:
        # Un nodo anterior (una PC reemplazada) ya había subido movimientos con ids propios más altos que los del
        # central.
        central.execute("UPDATE caja_movimientos SET origen = 'oficina-1', origen_id = 9000 WHERE id = "
                        "(SELECT MAX(id) FROM caja_movimientos)")
        central.commit()
    cuerpo = cuerpo_de_la_carga()
    en_el_nodo(c, lambda n: (carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo), n.commit()))

    def siguientes(n):
        return {t: n.execute(f"SELECT nextval(pg_get_serial_sequence('{t}', 'id'))").fetchone()[0]
                for t in ("caja_movimientos", "cc_asientos", "facturas", "ordenes_carga", "gastos_de_proveedor")}

    nodo = en_el_nodo(c, siguientes)
    with core.get_connection() as central:
        maximos = {t: central.execute(f"SELECT MAX(id) FROM {t}").fetchone()[0]
                   for t in ("cc_asientos", "facturas", "ordenes_carga", "gastos_de_proveedor")}
    for tabla, maximo in maximos.items():
        assert nodo[tabla] > maximo, f"{tabla}: lo que el nodo numere no puede chocar con lo que bajó"
    assert nodo["caja_movimientos"] > 9000, "ni con el origen_id del nodo anterior que el central ya recibió"


def test_se_niega_a_cargar_sobre_un_nodo_que_ya_tiene_datos(central_y_nodo):
    c = central_y_nodo
    datos_del_central(c)
    cuerpo = cuerpo_de_la_carga()
    primera = en_el_nodo(c, lambda n: (carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo), n.commit())[0])
    assert primera["hecha"] is True
    segunda = en_el_nodo(c, lambda n: carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo))
    assert segunda["hecha"] is False and "ya tienen filas" in segunda["motivo"]
    # No pisó nada.
    assert en_el_nodo(c, lambda n: filas(n, "SELECT COUNT(*) FROM ordenes_carga")) == [(2,)]


def test_si_el_espejo_todavia_no_trajo_lo_que_se_referencia_espera(central_y_nodo):
    c = central_y_nodo
    datos_del_central(c)
    cuerpo = cuerpo_de_la_carga()

    def sin_terceros(n):
        n.execute("TRUNCATE TABLE terceros CASCADE")
        n.commit()
        return carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo)

    resultado = en_el_nodo(c, sin_terceros)
    assert resultado["hecha"] is False and "todavía no trajo" in resultado["motivo"]
    assert en_el_nodo(c, lambda n: filas(n, "SELECT COUNT(*) FROM ordenes_carga")) == [(0,)], "no quedó nada a medias"


def test_una_carga_de_otra_version_no_se_aplica(central_y_nodo):
    c = central_y_nodo
    cuerpo = {**cuerpo_de_la_carga(), "version": 99}
    with pytest.raises(carga_inicial.CargaInicialInvalida, match="actualizar el nodo"):
        en_el_nodo(c, lambda n: carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo))


def test_el_router_la_sirve_a_un_nodo_autenticado(central_y_nodo):
    # La ruta existe y no es pública: sin el secreto del nodo, 401 (la matriz de roles lo fija para todas las rutas).
    c = central_y_nodo["cliente"]
    assert c.get("/sync/v1/carga-inicial", params={"node_id": "oficina-1"}).status_code == 401


# ── El volumen de Suitrans ────────────────────────────────────────────────────────────────────────────────────────────

#: Lo que tiene hoy la instancia (wiki: 4.337 órdenes, 22.646 asientos, 8.387 movimientos de caja, 2.799 gastos).
ORDENES, ASIENTOS, MOVIMIENTOS, GASTOS = 4337, 22646, 8387, 2799


def sembrar_volumen(central, d):
    central.execute(
        "INSERT INTO ordenes_carga (fecha, cliente_id, origen_id, destino_id, fletero_id, remito, cantidad, unidad, "
        "tarifa, alicuota_iva, iva, total, comision, estado, etapa, observaciones) "
        "SELECT DATE '2025-01-01' + (g % 300), ?, ?, ?, ?, 'R-' || LPAD(g::text, 8, '0'), 28.5, 'tn', "
        "100000 + g, 21, 21000 + g, 121000 + g, 5000, 'pendiente', 'cerrada', "
        "'Flete de cereal desde el campo hasta el puerto, retira el chofer con la carta de porte' "
        "FROM generate_series(1, ?) g",
        (d["cliente"], d["origen"], d["destino"], d["fletero"], ORDENES))
    central.execute(
        "INSERT INTO cc_asientos (fecha, tercero_id, rol, concepto, descripcion, debe, haber) "
        "SELECT '2025-02-01', ?, 'fletero', 'Flete orden ' || g, "
        "'Suipacha → Rosario · 28,5 tn · Soja · remito R-' || LPAD(g::text, 8, '0'), 5000 + g, 0 "
        "FROM generate_series(1, ?) g", (d["fletero"], ASIENTOS))
    central.execute(
        "INSERT INTO movimientos_cuenta_cargo (asiento_id, orden_id) "
        "SELECT a.id, o.id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) n FROM cc_asientos) a "
        "JOIN (SELECT id, ROW_NUMBER() OVER (ORDER BY id) n FROM ordenes_carga) o ON o.n = ((a.n - 1) % ?) + 1",
        (ORDENES,))
    central.execute(
        "INSERT INTO caja_movimientos (fecha, tipo, concepto, monto, medio_pago, anulado) "
        "SELECT '2025-03-01', 'ingreso', 'Cobro de flete ' || g, 10000 + g, 'efectivo', 0 FROM generate_series(1, ?) g",
        (MOVIMIENTOS,))
    central.execute(
        "INSERT INTO movimientos_caja_cargo (movimiento_id, descripcion, tercero_id, recibo) "
        "SELECT id, 'Cheque del banco de la localidad, recibo manual', ?, '0001-' || LPAD(id::text, 8, '0') "
        "FROM caja_movimientos", (d["cliente"],))
    central.execute(
        "INSERT INTO gastos_de_proveedor (fecha, proveedor_id, fletero_id, descripcion, importe, anulado) "
        "SELECT '2025-04-01', ?, ?, 'Cubiertas y reparaciones del camión ' || g, 800 + g, false "
        "FROM generate_series(1, ?) g",
        (d["proveedor"], d["fletero"], GASTOS))
    central.commit()


def test_el_volumen_de_suitrans_entra_en_una_respuesta(central_y_nodo):
    """Se midió, como pidió el plan: ≈4.300 órdenes, 22.600 asientos, 8.400 movimientos de caja y 2.800 gastos entran en
    UNA respuesta comprimida de unos pocos MB, que se arma y se aplica en segundos. libraedge no pagina la carga (el
    `traer()` no recibe cursor y el plazo es de 30 s): no hace falta."""
    c = central_y_nodo
    with core.get_connection() as central:
        sembrar_volumen(central, c["datos"])
    t0 = time.perf_counter()
    cuerpo = cuerpo_de_la_carga()
    armar_s = time.perf_counter() - t0
    with core.get_connection() as conn:
        crudo = len(json.dumps(carga_inicial.armar(conn), separators=(",", ":")))
    en_cable = len(json.dumps(cuerpo))
    t1 = time.perf_counter()
    resultado = en_el_nodo(c, lambda n: (carga_inicial.aplicar_carga_inicial(n, lambda: cuerpo), n.commit())[0])
    aplicar_s = time.perf_counter() - t1
    print(f"\nCARGA INICIAL DE SUITRANS: filas={sum(cuerpo['conteos'].values())} json_crudo={crudo / 1e6:.1f} MB "
          f"en_el_cable={en_cable / 1e6:.2f} MB armar={armar_s:.2f}s aplicar={aplicar_s:.2f}s")
    assert resultado["hecha"] is True
    assert resultado["conteos"]["cc_asientos"] == ASIENTOS and resultado["conteos"]["ordenes_carga"] == ORDENES
    assert en_cable < 4_000_000, "comprimida, la respuesta entera es de unos pocos MB"
    assert armar_s < 15 and aplicar_s < 30, "muy por debajo del plazo de 30 s del transporte"
    assert Decimal(en_el_nodo(c, lambda n: filas(n, "SELECT SUM(debe) FROM cc_asientos"))[0][0]) > 0
