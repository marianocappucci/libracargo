"""La pre liquidación de transportistas.

Escenario chico y **con los números calculados a mano**: un transportista responsable inscripto, uno
monotributista y uno exento, con fletes en los bordes del rango, uno por fuera, una orden anulada, una
sin fletero y una con comisión cero. Cada aserción es un importe que se rehizo con lápiz: un reporte
que devuelve algo no prueba nada, lo que prueba es que devuelva **ese** número.

Los nombres y CUIT son ficticios.
"""

import re
import zlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.testing import crear_schema_de_auth
from sqlalchemy import text

from app.main import crear_app
from app.models.enums import CondicionIVA
from app.servicios import pre_liquidacion
from tests.conftest import (
    CUIT_EMISOR,
    arca_responde,
    cargar_empresa,
    config_de_prueba,
    configurar_arca,
    vaciar_auth,
)

USUARIO, CLAVE = "admin", "clave-de-prueba"
SLUG = "/api/reportes/pre-liquidacion-transportistas"
JULIO = "desde=2026-07-01&hasta=2026-07-31"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    vaciar_auth(engine)
    crear_schema_de_auth(engine)
    cfg = config_de_prueba()
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    vaciar_auth(engine)


def crear(c, ruta, datos):
    r = c.post(ruta, json=datos)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def escenario(cliente, monkeypatch):
    """Tres transportistas (RI, monotributo, exento) con sus fletes, y lo que NO tiene que entrar."""
    def tercero(nombre, cuit, condicion, **roles):
        return crear(cliente, "/api/terceros", {
            "razon_social": nombre, "cuit": cuit, "condicion_iva": condicion, **roles})["id"]

    d = {
        # Los dos clientes sin CUIT: la factura de prueba sale B.
        "cliente_a": tercero("Agro Norte", None, "consumidor_final", es_cliente=True),
        "cliente_b": tercero("Molino Sur", None, "consumidor_final", es_cliente=True),
        # Se crean en este orden a propósito, distinto del alfabético: el reporte ordena por nombre.
        "mono": tercero("Juan Pérez", "20-12345678-6", "monotributo", es_fletero=True),
        "ri": tercero("Transportes del Oeste", "30-12345678-1", "responsable_inscripto",
                      es_fletero=True),
        "exento": tercero("Cooperativa del Sur", "30-12345678-1", "exento", es_fletero=True),
        "suipacha": crear(cliente, "/api/localidades", {"nombre": "Suipacha"})["id"],
        "rosario": crear(cliente, "/api/localidades", {"nombre": "Rosario"})["id"],
    }

    def orden(fecha, comision, fletero, *, alicuota="21.00", cliente_id=None, remito=None):
        return crear(cliente, "/api/ordenes", {
            "fecha": fecha, "cliente_id": cliente_id or d["cliente_a"],
            "origen_id": d["suipacha"], "destino_id": d["rosario"], "tarifa": "5000.00",
            "comision": comision, "alicuota_iva": alicuota, "remito": remito,
            "fletero_id": d[fletero] if fletero else None, "cantidad": "10", "unidad": "tn"})

    # ── Transportes del Oeste (responsable inscripto) ──
    d["ri_borde_desde"] = orden("2026-07-01", "1000.00", "ri", remito="R-0001")
    # Tres fletes de 0,50: 0,105 de IVA cada uno, que redondea a 0,11 (mitad hacia arriba). Si el
    # redondeo fuera sobre la suma (1,50 × 21% = 0,315) daría 0,32 y no 0,33.
    d["ri_medio"] = [orden("2026-07-05", "0.50", "ri"), orden("2026-07-05", "0.50", "ri"),
                     orden("2026-07-06", "0.50", "ri")]
    d["ri_105"] = orden("2026-07-12", "100.10", "ri", alicuota="10.50")   # 10,5105 -> 10,51
    d["ri_borde_hasta"] = orden("2026-07-31", "333.33", "ri")              # 69,9993 -> 70,00
    # ── Juan Pérez (monotributo) y Cooperativa del Sur (exento): sin IVA ──
    d["mono_1"] = orden("2026-07-10", "500.00", "mono", cliente_id=d["cliente_b"])
    d["exento_1"] = orden("2026-07-20", "700.00", "exento")
    # ── Lo que NO entra ──
    orden("2026-06-30", "9999.00", "ri")                     # un día antes
    orden("2026-08-01", "8888.00", "ri")                     # un día después
    d["anulada"] = orden("2026-07-15", "7777.00", "ri")
    assert cliente.delete(f"/api/ordenes/{d['anulada']['id']}").status_code == 200
    orden("2026-07-15", "0.00", "ri")                        # comisión cero
    orden("2026-07-15", "600.00", None)                      # sin fletero

    # Una de las del transportista RI **está facturada** al cliente: igual entra.
    cargar_empresa(cliente)
    configurar_arca(cliente, cuit=CUIT_EMISOR, punto_venta=1)
    arca_responde(monkeypatch)
    pf = cliente.post("/api/pre-facturas", json={
        "fecha": "2026-07-31", "cliente_id": d["cliente_a"],
        "tipo": "factura_b", "orden_ids": [d["ri_borde_desde"]["id"]]})
    assert pf.status_code == 201, pf.text
    assert cliente.post(f"/api/pre-facturas/{pf.json()['id']}/facturar").status_code == 201
    return d


def pedir(cliente, query=JULIO):
    r = cliente.get(f"{SLUG}?{query}")
    assert r.status_code == 200, r.text
    return r.json()


def por_nombre(datos):
    return {b["transportista"]: b for b in datos["transportistas"]}


def D(x):
    return Decimal(x)


# ── El cálculo ──────────────────────────────────────────────────────────────

def test_cada_transportista_trae_sus_fletes_con_la_comision_y_el_iva_de_su_condicion(
        cliente, escenario):
    datos = pedir(cliente)
    bloques = por_nombre(datos)
    assert set(bloques) == {"Transportes del Oeste", "Juan Pérez", "Cooperativa del Sur"}

    ri = bloques["Transportes del Oeste"]
    assert ri["cuit"] == "30-12345678-1"
    assert ri["condicion_iva"] == "responsable_inscripto" and ri["discrimina_iva"] is True
    assert ri["cantidad_fletes"] == 6
    # El valor de cada flete es la COMISIÓN de la orden, no la tarifa (5.000 en todas).
    assert [D(f["neto"]) for f in ri["fletes"]] == [
        D("1000.00"), D("0.50"), D("0.50"), D("0.50"), D("100.10"), D("333.33")]
    assert D("5000.00") not in {D(f["neto"]) for f in ri["fletes"]}
    assert [D(f["iva"]) for f in ri["fletes"]] == [
        D("210.00"), D("0.11"), D("0.11"), D("0.11"), D("10.51"), D("70.00")]
    assert [D(f["total"]) for f in ri["fletes"]] == [
        D("1210.00"), D("0.61"), D("0.61"), D("0.61"), D("110.61"), D("403.33")]

    # Responsable inscripto: suma IVA. Monotributo y exento: IVA cero, total = comisión.
    mono = bloques["Juan Pérez"]
    assert mono["condicion_iva"] == "monotributo" and mono["discrimina_iva"] is False
    assert [(D(f["neto"]), D(f["iva"]), D(f["total"])) for f in mono["fletes"]] == [
        (D("500.00"), D("0.00"), D("500.00"))]
    exento = bloques["Cooperativa del Sur"]
    assert exento["condicion_iva"] == "exento" and exento["discrimina_iva"] is False
    assert [(D(f["neto"]), D(f["iva"]), D(f["total"])) for f in exento["fletes"]] == [
        (D("700.00"), D("0.00"), D("700.00"))]


def test_el_flete_trae_los_datos_de_la_orden(cliente, escenario):
    flete = por_nombre(pedir(cliente))["Transportes del Oeste"]["fletes"][0]
    assert flete["orden_id"] == escenario["ri_borde_desde"]["id"]
    assert flete["fecha"] == "2026-07-01"
    assert flete["remito"] == "R-0001"
    assert flete["cliente"] == "Agro Norte"
    assert (flete["origen"], flete["destino"]) == ("Suipacha", "Rosario")
    assert D(flete["cantidad"]) == D("10") and flete["unidad"] == "tn"
    assert D(flete["alicuota_iva"]) == D("21.00")


def test_el_iva_se_redondea_por_flete_y_no_sobre_la_suma(cliente, escenario):
    """Tres fletes de 0,50 a 21%: 0,105 cada uno -> 0,11 (mitad hacia arriba). Sumados dan 0,33; si el
    redondeo fuera sobre el total (1,50 × 21% = 0,315) daría 0,32 — y la factura del transportista, que
    discrimina flete por flete, no coincidiría."""
    ri = por_nombre(pedir(cliente))["Transportes del Oeste"]
    chicos = [f for f in ri["fletes"] if D(f["neto"]) == D("0.50")]
    assert [D(f["iva"]) for f in chicos] == [D("0.11")] * 3
    assert sum(D(f["iva"]) for f in chicos) == D("0.33") != D("0.32")
    # Y la alícuota que cuenta es la de CADA orden: 10,5% sobre 100,10 son 10,5105 -> 10,51.
    assert D(next(f for f in ri["fletes"] if D(f["neto"]) == D("100.10"))["iva"]) == D("10.51")


def test_los_subtotales_y_el_total_general_son_la_suma_de_lo_que_se_ve(cliente, escenario):
    datos = pedir(cliente)
    bloques = por_nombre(datos)
    ri = bloques["Transportes del Oeste"]
    # 1000 + 3 × 0,50 + 100,10 + 333,33 = 1.434,93 ; IVA 210 + 0,33 + 10,51 + 70 = 290,84
    assert (D(ri["neto"]), D(ri["iva"]), D(ri["total"])) == (
        D("1434.93"), D("290.84"), D("1725.77"))
    assert (D(bloques["Juan Pérez"]["neto"]), D(bloques["Juan Pérez"]["iva"]),
            D(bloques["Juan Pérez"]["total"])) == (D("500.00"), D("0.00"), D("500.00"))
    assert (D(bloques["Cooperativa del Sur"]["total"])) == D("700.00")

    assert datos["fletes"] == 8
    assert (D(datos["neto"]), D(datos["iva"]), D(datos["total"])) == (
        D("2634.93"), D("290.84"), D("2925.77"))
    # Y es consistente: cada subtotal es la suma de sus filas, y el general la de los subtotales.
    for b in datos["transportistas"]:
        assert sum(D(f["neto"]) for f in b["fletes"]) == D(b["neto"])
        assert sum(D(f["iva"]) for f in b["fletes"]) == D(b["iva"])
        assert sum(D(f["total"]) for f in b["fletes"]) == D(b["total"])
        assert D(b["neto"]) + D(b["iva"]) == D(b["total"])
    assert sum(D(b["total"]) for b in datos["transportistas"]) == D(datos["total"])


def test_el_rango_es_inclusivo_en_los_dos_extremos(cliente, escenario):
    ri = por_nombre(pedir(cliente))["Transportes del Oeste"]
    fechas = [f["fecha"] for f in ri["fletes"]]
    # El 1 y el 31 de julio entran; el 30 de junio y el 1 de agosto (con 9.999 y 8.888) no.
    assert fechas[0] == "2026-07-01" and fechas[-1] == "2026-07-31"
    assert D("9999.00") not in {D(f["neto"]) for f in ri["fletes"]}
    assert D("8888.00") not in {D(f["neto"]) for f in ri["fletes"]}
    # Un rango de un solo día: desde == hasta.
    un_dia = pedir(cliente, "desde=2026-07-01&hasta=2026-07-01")
    assert [(b["transportista"], b["cantidad_fletes"]) for b in un_dia["transportistas"]] == [
        ("Transportes del Oeste", 1)]


def test_entran_las_pendientes_y_las_facturadas_y_no_las_anuladas_ni_sin_fletero_ni_comision_cero(
        cliente, escenario):
    datos = pedir(cliente)
    ids = {f["orden_id"] for b in datos["transportistas"] for f in b["fletes"]}
    # La orden facturada al cliente entra (la liquidación no depende de eso)...
    facturada = cliente.get(f"/api/ordenes/{escenario['ri_borde_desde']['id']}").json()
    assert facturada["estado"] == "facturada"
    assert facturada["id"] in ids
    # ...y también las pendientes.
    assert escenario["ri_105"]["id"] in ids
    # No entran: la anulada, la sin fletero, la de comisión cero.
    todas = cliente.get(f"/api/reportes/listado-ordenes?{JULIO}").json()
    assert len(todas) == 11   # las 8 que entran + anulada + comisión cero + sin fletero
    assert escenario["anulada"]["id"] not in ids
    afuera = [o for o in todas if o["id"] not in ids]
    assert {(o["estado"], o["fletero_id"] is None, D(o["comision"]) == 0) for o in afuera} == {
        ("anulada", False, False), ("pendiente", False, True), ("pendiente", True, False)}
    assert datos["fletes"] == 8


def test_un_transportista_sin_condicion_o_consumidor_final_va_sin_iva_y_con_aviso(
        cliente, escenario):
    for nombre, condicion in (("Sin Categoría SA", "no_categorizado"),
                              ("Pedro Gómez", "consumidor_final")):
        t = crear(cliente, "/api/terceros", {
            "razon_social": nombre, "condicion_iva": condicion, "es_fletero": True})["id"]
        crear(cliente, "/api/ordenes", {
            "fecha": "2026-07-02", "cliente_id": escenario["cliente_a"],
            "origen_id": escenario["suipacha"], "destino_id": escenario["rosario"],
            "tarifa": "1000.00", "comision": "100.00", "fletero_id": t})
    bloques = por_nombre(pedir(cliente))
    for nombre in ("Sin Categoría SA", "Pedro Gómez"):
        b = bloques[nombre]
        assert D(b["iva"]) == D("0.00") and D(b["total"]) == D("100.00")
        assert b["discrimina_iva"] is False
        assert b["aviso"], nombre
    # Los que tienen una condición real, sin aviso.
    assert bloques["Transportes del Oeste"]["aviso"] is None
    assert bloques["Juan Pérez"]["aviso"] is None


def test_cada_condicion_tiene_su_criterio():
    """El criterio de IVA cubre TODOS los valores del enum: uno nuevo sin criterio rompe acá, y no se
    liquida en silencio con IVA cero."""
    assert set(pre_liquidacion.DISCRIMINA_IVA) == set(CondicionIVA)
    assert set(pre_liquidacion.NOMBRE_DE_CONDICION) == set(CondicionIVA)
    comision, alicuota = D("1000.00"), D("21.00")
    esperado = {
        CondicionIVA.RESPONSABLE_INSCRIPTO: D("210.00"),
        CondicionIVA.MONOTRIBUTO: D("0.00"),
        CondicionIVA.EXENTO: D("0.00"),
        CondicionIVA.CONSUMIDOR_FINAL: D("0.00"),
        CondicionIVA.NO_CATEGORIZADO: D("0.00"),
    }
    assert set(esperado) == set(CondicionIVA)
    for condicion, iva in esperado.items():
        assert pre_liquidacion.iva_del_flete(condicion, comision, alicuota) == iva, condicion
    # Un RI con una orden a alícuota cero: IVA cero, no un error.
    assert pre_liquidacion.iva_del_flete(
        CondicionIVA.RESPONSABLE_INSCRIPTO, comision, D("0.00")) == D("0.00")


# ── Filtros, orden y parámetros ─────────────────────────────────────────────

def test_se_puede_acotar_a_un_transportista(cliente, escenario):
    solo_mono = pedir(cliente, f"{JULIO}&fletero_id={escenario['mono']}")
    assert solo_mono["fletero_id"] == escenario["mono"]
    assert [b["transportista"] for b in solo_mono["transportistas"]] == ["Juan Pérez"]
    assert solo_mono["fletes"] == 1
    assert D(solo_mono["total"]) == D("500.00")
    # El control de que el filtro filtra: sin él son tres.
    assert len(pedir(cliente)["transportistas"]) == 3
    # Un transportista sin fletes en el rango (o un id que no es de un fletero): vacío, no error.
    vacio = pedir(cliente, f"{JULIO}&fletero_id={escenario['cliente_a']}")
    assert vacio["transportistas"] == [] and vacio["fletes"] == 0
    assert D(vacio["total"]) == D("0.00")


def test_los_transportistas_salen_por_nombre_y_los_fletes_por_fecha_y_numero(cliente, escenario):
    datos = pedir(cliente)
    # No es el orden de alta (Pérez, Oeste, Sur) sino el alfabético.
    assert [b["transportista"] for b in datos["transportistas"]] == [
        "Cooperativa del Sur", "Juan Pérez", "Transportes del Oeste"]
    ri = por_nombre(datos)["Transportes del Oeste"]
    claves = [(f["fecha"], f["orden_id"]) for f in ri["fletes"]]
    assert claves == sorted(claves)
    # Las dos del 5 de julio, por número de orden.
    del_cinco = [f["orden_id"] for f in ri["fletes"] if f["fecha"] == "2026-07-05"]
    assert del_cinco == sorted(del_cinco) and len(del_cinco) == 2


def test_el_rango_es_obligatorio_y_tiene_que_estar_en_orden(cliente, escenario):
    """🔴 El 422 va con su control positivo (ver `test_reportes`): el mismo pedido con las fechas da 200."""
    for ruta in (SLUG, SLUG + "/pdf"):
        assert cliente.get(ruta).status_code == 422
        assert cliente.get(f"{ruta}?desde=2026-07-01").status_code == 422
        assert cliente.get(f"{ruta}?hasta=2026-07-31").status_code == 422
        assert cliente.get(f"{ruta}?desde=2026-07-31&hasta=2026-07-01").status_code == 422
        assert cliente.get(f"{ruta}?{JULIO}").status_code == 200


def test_el_catalogo_lo_ofrece_como_un_reporte_de_detalle_con_rango_y_fletero(cliente):
    catalogo = {r["slug"]: r for r in cliente.get("/api/reportes").json()}
    r = catalogo["pre-liquidacion-transportistas"]
    assert r["titulo"] == "Pre liquidación de transportistas"
    assert r["detalle"] is True and r["solo_admin"] is False
    assert r["parametros"] == ["rango", "fletero"]
    assert r["descripcion"].strip()


# ── Permisos ────────────────────────────────────────────────────────────────

def test_sin_sesion_no_se_ve_y_un_operador_si(cliente, escenario):
    anonimo = TestClient(cliente.app, base_url="https://testserver")
    assert anonimo.get(f"{SLUG}?{JULIO}").status_code == 401
    assert anonimo.get(f"{SLUG}/pdf?{JULIO}").status_code == 401

    # Como los otros reportes: lo ve un operador (staff), no hace falta ser admin.
    cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    assert staff.post("/auth/login",
                      json={"username": "marta", "password": "una-clave"}).status_code == 200
    assert staff.get(f"{SLUG}?{JULIO}").status_code == 200
    assert staff.get(f"{SLUG}/pdf?{JULIO}").status_code == 200
    assert "pre-liquidacion-transportistas" in {
        r["slug"] for r in staff.get("/api/reportes").json()}


# ── El PDF ──────────────────────────────────────────────────────────────────

def texto_del_pdf(contenido: bytes) -> str:
    """El texto de un PDF de fpdf2 con fuentes core: los strings entre paréntesis de los streams
    comprimidos. Sin dependencias: lo que el PDF dice es lo que dicen sus `Tj`."""
    partes = []
    for flujo in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", contenido, re.S):
        try:
            crudo = zlib.decompress(flujo)
        except zlib.error:
            continue
        for literal in re.findall(rb"\(((?:[^()\\]|\\.)*)\)", crudo):
            partes.append(literal.replace(rb"\(", b"(").replace(rb"\)", b")")
                          .replace(rb"\\", b"\\").decode("cp1252", "replace"))
    return " ".join(partes)


def test_el_pdf_sale_con_el_titulo_la_leyenda_los_transportistas_y_los_totales(
        cliente, escenario):
    cliente.put("/api/configuracion", json={
        "razon_social": "Agencia Ficticia SRL", "cuit": "30-12345678-1",
        "domicilio": "Calle Falsa 123", "localidad": "Suipacha", "telefono": "02341-000000"})
    r = cliente.get(f"{SLUG}/pdf?{JULIO}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "pre-liquidacion-transportistas-2026-07-01-2026-07-31.pdf" in (
        r.headers["content-disposition"])

    texto = texto_del_pdf(r.content)
    assert "Pre liquidación de transportistas" in texto
    assert "Pre liquidación — no es un comprobante" in texto
    # El encabezado de la empresa.
    assert "Agencia Ficticia SRL" in texto and "Calle Falsa 123" in texto
    # Los bloques, con su condición.
    for nombre in ("Transportes del Oeste", "Juan Pérez", "Cooperativa del Sur"):
        assert nombre in texto
    assert "CUIT 30-12345678-1" in texto and "Responsable inscripto (suma IVA)" in texto
    assert "Monotributista (sin IVA)" in texto
    # Los subtotales y el total general, formateados como en el resto del producto.
    for importe in ("1.434,93", "290,84", "1.725,77", "500,00", "700,00", "2.634,93", "2.925,77"):
        assert importe in texto, importe
    assert "TOTAL GENERAL (8 fletes)" in texto
    # Y los datos de un flete.
    assert "R-0001" in texto and "Agro Norte" in texto and "01-07-2026" in texto


def test_el_pdf_de_un_rango_sin_fletes_sale_igual_y_lo_dice(cliente, escenario):
    r = cliente.get(f"{SLUG}/pdf?desde=2025-01-01&hasta=2025-01-31")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    texto = texto_del_pdf(r.content)
    assert "No hay fletes con comisión en ese período." in texto
    assert "Pre liquidación — no es un comprobante" in texto
    assert "TOTAL GENERAL" not in texto


def test_el_pdf_sin_datos_de_la_empresa_sale_igual(cliente, escenario, sesion):
    """Lo que no puede pasar es que no se pueda generar por falta de configuración."""
    sesion.execute(text("DELETE FROM configuracion_empresa"))
    sesion.commit()
    assert cliente.get("/api/configuracion").json()["razon_social"] == ""
    assert cliente.get(f"{SLUG}/pdf?{JULIO}").status_code == 200


def test_el_pdf_con_muchos_fletes_pasa_de_hoja_y_repite_el_encabezado_del_bloque(
        cliente, escenario):
    """El bloque que no entra en una hoja sigue en la otra con su banda («continúa») y su total."""
    for i in range(70):
        crear(cliente, "/api/ordenes", {
            "fecha": "2026-07-15", "cliente_id": escenario["cliente_a"],
            "origen_id": escenario["suipacha"], "destino_id": escenario["rosario"],
            "tarifa": "1000.00", "comision": "1234567.89", "fletero_id": escenario["ri"],
            "remito": f"R-{i:04d}"})
    r = cliente.get(f"{SLUG}/pdf?{JULIO}")
    assert r.status_code == 200
    texto = texto_del_pdf(r.content)
    assert "Transportes del Oeste (continúa)" in texto
    assert len(re.findall(rb"/Type /Page\b", r.content)) >= 2
    assert "1.234.567,89" in texto
    # 70 fletes de 1.234.567,89 + los 6 de antes: 86.419.752,30 + 1.434,93.
    assert "86.421.187,23" in texto


def test_el_pdf_lleva_el_logo_de_la_empresa_y_el_aviso_del_transportista_sin_categorizar(
        cliente, escenario):
    import io

    from PIL import Image

    cliente.put("/api/configuracion", json={"razon_social": "Agencia Ficticia SRL"})
    png = io.BytesIO()
    Image.new("RGB", (60, 30), (1, 105, 111)).save(png, format="PNG")
    r = cliente.post("/api/configuracion/logo",
                     files={"archivo": ("logo.png", png.getvalue(), "image/png")})
    assert r.status_code == 200, r.text

    t = crear(cliente, "/api/terceros", {
        "razon_social": "Sin Categoría SA", "condicion_iva": "no_categorizado", "es_fletero": True})
    crear(cliente, "/api/ordenes", {
        "fecha": "2026-07-02", "cliente_id": escenario["cliente_a"],
        "origen_id": escenario["suipacha"], "destino_id": escenario["rosario"],
        "tarifa": "1000.00", "comision": "100.00", "fletero_id": t["id"]})

    r = cliente.get(f"{SLUG}/pdf?{JULIO}")
    assert r.status_code == 200
    # Con logo, el encabezado dibuja la imagen y no el nombre como texto.
    assert b"/Subtype /Image" in r.content
    texto = texto_del_pdf(r.content)
    assert "Sin Categoría SA" in texto and "Sin categorizar (sin IVA)" in texto
    assert "No tiene condición de IVA cargada: se liquida sin IVA." in texto
    assert "Sin CUIT" in texto


def test_un_bloque_que_no_entra_en_lo_que_queda_de_la_hoja_arranca_en_la_siguiente(
        cliente, escenario):
    """Un transportista nunca queda con su banda y su encabezado al pie de la hoja y los fletes en la
    otra: si no entra con unos renglones, se pasa entero."""
    for nombre in ("Transporte Uno", "Transporte Dos", "Transporte Tres"):
        t = crear(cliente, "/api/terceros", {
            "razon_social": nombre, "condicion_iva": "monotributo", "es_fletero": True})
        for i in range(22):
            crear(cliente, "/api/ordenes", {
                "fecha": "2026-07-03", "cliente_id": escenario["cliente_a"],
                "origen_id": escenario["suipacha"], "destino_id": escenario["rosario"],
                "tarifa": "1000.00", "comision": "10.00", "fletero_id": t["id"],
                "remito": f"{nombre[-3:]}-{i}"})
    r = cliente.get(f"{SLUG}/pdf?{JULIO}")
    assert r.status_code == 200
    assert len(re.findall(rb"/Type /Page\b", r.content)) >= 3
    texto = texto_del_pdf(r.content)
    # Los tres bloques salen completos, cada uno con su subtotal de 22 fletes y 220,00.
    assert texto.count("Subtotal · 22 fletes") == 3
    assert texto.count("220,00") >= 6
