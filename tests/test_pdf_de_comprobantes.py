"""El PDF de los comprobantes de LibraCargo (ADR-034): el logo, la razón social que emitió, y el correo.

> 🔑 **Los datos son ficticios**: «Transportes Demo SRL» (30-50000001-1), «Juan Pérez» (20-12345678-6),
> «Agro Norte» (el cliente de la suite, 30-12345678-1). Ni un nombre ni un CUIT real entran en una suite.

Lo que se mide, en el orden del flujo:

1. Emitir deja el PDF guardado, con la razón social que emitió y **el logo de la base**; un fallo del PDF no deshace
   la emisión, y un comprobante sin PDF guardado se arma al pedirlo.
2. Cada razón social imprime el membrete **suyo** (dos razones sociales, cada PDF con la suya), y la nota de crédito
   tiene el suyo.
3. Qué comprobantes se ven (`puede_ver`): los de LibraCargo, con CAE y que no sean de homologación; el resto es 404.
4. El correo: sale el mismo PDF, firmado por la razón social, con un SMTP falso.
5. El resolvedor único: lo que decide, sin pasar por HTTP. Y que **la pre factura** lleva el logo.

Cómo se lee el PDF: `fpdf2` comprime los flujos, así que el texto se busca después de descomprimirlos, y el logo
se cuenta como los objetos `/Subtype /Image` (cada imagen del documento es uno).
"""

import io
import os
import re
import zlib
from datetime import date
from decimal import Decimal

import pytest
from libracore import email_sender, pdf_generator
from libracore import emisor_del_pdf as emisor_del_motor
from libracore import facturas_router as motor_facturas
from libracore.db import core as libracore_core
from libracore.db import facturas as db_facturas
from PIL import Image

from app.models import TipoComprobante
from app.servicios import emisor_del_pdf as emisor_de_cargo
from tests.conftest import CUIT_EMISOR, URL_CORE, arca_responde, configurar_arca
from tests.test_comprobantes import facturar, orden, pre_factura

#: Los datos de una segunda razón social. Ficticios.
CUIT_DEMO = "30-50000001-1"
CUIT_OTRA = "20-12345678-6"


# ── Leer un PDF ─────────────────────────────────────────────────────────────


def texto_del_pdf(contenido: bytes) -> str:
    """Todo el texto dibujado, sin comprimir. Los acentos vienen como escapes octales (`\\351`) y se vuelven letras."""
    partes = []
    for flujo in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", contenido, re.S):
        try:
            partes.append(zlib.decompress(flujo).decode("latin-1"))
        except zlib.error:
            continue
    texto = "\n".join(partes)
    return re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), texto)


def imagenes_del_pdf(contenido: bytes) -> int:
    return len(re.findall(rb"/Subtype\s*/Image", contenido))


def un_logo() -> bytes:
    """Un PNG de verdad, con color: el que sube la persona desde Configuración."""
    buffer = io.BytesIO()
    Image.new("RGB", (60, 30), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


# ── Armar el escenario ──────────────────────────────────────────────────────


def cargar_logo(cliente, *, cuit=None):
    """Datos de la empresa de la instancia y su logo, como los carga la pantalla «Datos de la empresa»."""
    cuerpo = {"razon_social": "Suitrans SA", "domicilio": "Calle Falsa 123", "localidad": "Suipacha",
              "provincia": "Buenos Aires", "ingresos_brutos": "123-456", "inicio_actividades": "01/01/2020"}
    if cuit:
        cuerpo["cuit"] = cuit
    assert cliente.put("/api/configuracion", json=cuerpo).status_code == 200
    r = cliente.post("/api/configuracion/logo", files={"archivo": ("logo.png", un_logo(), "image/png")})
    assert r.status_code == 200, r.text


def emitida(cliente, datos, tarifa="1000.00", **kw):
    """Una factura emitida por ARCA (simulada) para la razón social que emite (`con_emisor`)."""
    r = facturar(cliente, datos, [orden(cliente, datos, tarifa)], **kw)
    assert r.status_code == 201, r.text
    return r.json()


def pdf_de(cliente, comprobante_id):
    r = cliente.get(f"/api/comprobantes/{comprobante_id}/pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    return r.content


def factura_del_motor(factura_id):
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        return db_facturas.get_factura(factura_id, conn=conn)


def segunda_razon(cliente, datos, *, nombre="Transportes Demo SRL", cuit=CUIT_DEMO):
    r = cliente.put(f"/api/razones-sociales/{datos['otra_razon']}", json={
        "nombre": nombre, "cuit": cuit, "punto_venta": 2})
    assert r.status_code == 200, r.text
    return datos["otra_razon"]


def a_mano(sesion, datos, razon_id, *, numero, cae="75123456789012", tipo=TipoComprobante.FACTURA_A,
           ambiente=None, **kw):
    """Un comprobante de una razón social que no emite por ARCA, creado por la misma puerta que usa la emisión."""
    from app.servicios import comprobantes

    comp = comprobantes.crear(
        sesion, razon_social_id=razon_id, tipo=tipo, punto_venta=2, numero=numero, fecha=date(2026, 8, 15),
        cliente_id=datos["cliente"], neto=Decimal("100.00"), iva=Decimal("21.00"), total=Decimal("121.00"),
        items=[{"description": "Flete", "qty": 1, "unit_price": 100.0, "subtotal": 100.0, "iva_pct": 21}],
        ambiente=ambiente, **kw)
    if cae:
        comprobantes.guardar_cae(sesion, comp, cae, "20261231")
    sesion.commit()
    return comp


# ── 1. Emitir deja el PDF ───────────────────────────────────────────────────


@pytest.mark.con_emisor
def test_emitir_guarda_el_pdf_con_la_razon_social_que_emitio(cliente, datos):
    comp = emitida(cliente, datos)

    guardado = factura_del_motor(comp["id"])["pdf_path"]
    assert guardado and os.path.exists(guardado), "el PDF se guarda al emitir"
    contenido = pdf_de(cliente, comp["id"])
    assert contenido == open(guardado, "rb").read(), "se sirve el que se guardó, no uno nuevo"
    texto = texto_del_pdf(contenido)
    assert "Suitrans" in texto and CUIT_EMISOR in texto
    assert "Responsable Inscripto" in texto
    # El `empresa` de `arca_config` es un slug interno ("agencia"): nunca es el nombre de quien emite.
    assert "agencia" not in texto
    assert imagenes_del_pdf(contenido) == 0, "sin logo cargado, el membrete lleva las iniciales"


@pytest.mark.con_emisor
def test_el_pdf_lleva_el_logo_de_la_base_y_el_domicilio_de_la_empresa(cliente, datos):
    cargar_logo(cliente, cuit=CUIT_EMISOR)
    comp = emitida(cliente, datos)

    contenido = pdf_de(cliente, comp["id"])
    assert imagenes_del_pdf(contenido) == 1
    texto = texto_del_pdf(contenido)
    assert "Calle Falsa 123, Suipacha" in texto
    assert "123-456" in texto
    assert "01-01-2020" in texto, "el inicio de actividades, como se lee en un papel"


@pytest.mark.con_emisor
def test_el_pdf_guardado_es_lo_que_salio_y_no_cambia_si_cambia_el_logo(cliente, datos):
    """Es lo que se le mandó al cliente: cambiar el logo después no reescribe un comprobante ya emitido."""
    comp = emitida(cliente, datos)
    assert imagenes_del_pdf(pdf_de(cliente, comp["id"])) == 0

    cargar_logo(cliente, cuit=CUIT_EMISOR)

    assert imagenes_del_pdf(pdf_de(cliente, comp["id"])) == 0
    # Uno nuevo sí sale con el logo.
    nuevo = emitida(cliente, datos, "50.00")
    assert imagenes_del_pdf(pdf_de(cliente, nuevo["id"])) == 1


@pytest.mark.con_emisor
def test_si_el_pdf_no_sale_la_emision_no_se_deshace_y_el_pdf_se_arma_al_pedirlo(cliente, datos, monkeypatch):
    """ARCA ya autorizó y la transacción ya guardó: un PDF que falla no revierte un comprobante fiscal."""
    real = pdf_generator.generate_pdf_factura

    def falla(*a, **kw):
        raise RuntimeError("fpdf se cayó")

    monkeypatch.setattr(pdf_generator, "generate_pdf_factura", falla)
    pf = pre_factura(cliente, datos, [orden(cliente, datos, "1000.00")]).json()
    r = cliente.post(f"/api/pre-facturas/{pf['id']}/facturar")
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["cae"], "el comprobante quedó con su CAE"
    assert cliente.get(f"/api/pre-facturas/{pf['id']}").json()["estado"] == "facturado"
    assert not factura_del_motor(comp["id"])["pdf_path"]

    # Cuando el generador vuelve, el endpoint lo arma al vuelo y **no** lo guarda: es lo que dice el motor.
    monkeypatch.setattr(pdf_generator, "generate_pdf_factura", real)
    assert "Suitrans" in texto_del_pdf(pdf_de(cliente, comp["id"]))
    assert not factura_del_motor(comp["id"])["pdf_path"]


@pytest.mark.con_emisor
def test_un_pdf_perdido_se_arma_de_nuevo(cliente, datos):
    """Un redeploy que borra el disco del contenedor: el archivo no está, el comprobante sí."""
    comp = emitida(cliente, datos)
    os.remove(factura_del_motor(comp["id"])["pdf_path"])
    assert "Suitrans" in texto_del_pdf(pdf_de(cliente, comp["id"]))


def test_contra_homologacion_no_se_guarda_ningun_pdf(cliente, datos, monkeypatch):
    """El ensayo se revierte entero: no hay comprobante, y por lo tanto no hay PDF."""
    r = cliente.put(f"/api/razones-sociales/{datos['razon']}", json={
        "nombre": "Suitrans", "cuit": CUIT_EMISOR, "punto_venta": 1})
    assert r.status_code == 200
    configurar_arca(cliente, cuit=CUIT_EMISOR, punto_venta=1, ambiente="homologacion")
    arca_responde(monkeypatch)

    r = facturar(cliente, datos, [orden(cliente, datos, "1000.00")])
    assert r.status_code == 200 and r.json()["ensayo"] is True
    assert not os.path.exists(pdf_generator.FACTURAS_PDF_DIR) or not os.listdir(pdf_generator.FACTURAS_PDF_DIR)


# ── 2. Cada razón social, la suya ───────────────────────────────────────────


@pytest.mark.con_emisor
def test_dos_razones_sociales_cada_pdf_con_la_suya(cliente, datos, sesion):
    """Suitrans emite por ARCA (tiene `emisor_id`); la otra no (`emisor_id` vacío): ninguna imprime la de la otra."""
    cargar_logo(cliente)  # la empresa sin CUIT: el logo vale para las dos
    otra = segunda_razon(cliente, datos)
    propia = emitida(cliente, datos)
    ajena = a_mano(sesion, datos, otra, numero=7)

    primero = pdf_de(cliente, propia["id"])
    segundo = pdf_de(cliente, ajena.id)
    t1, t2 = texto_del_pdf(primero), texto_del_pdf(segundo)
    assert "Suitrans" in t1 and CUIT_EMISOR in t1
    assert "Transportes Demo SRL" not in t1 and CUIT_DEMO not in t1
    assert "Transportes Demo SRL" in t2 and CUIT_DEMO in t2
    assert "Suitrans" not in t2 and CUIT_EMISOR not in t2
    assert imagenes_del_pdf(primero) == imagenes_del_pdf(segundo) == 1


@pytest.mark.con_emisor
def test_la_condicion_de_iva_es_la_de_cada_razon_social(cliente, datos, sesion):
    otra = segunda_razon(cliente, datos, nombre="Juan Pérez", cuit=CUIT_OTRA)
    assert cliente.put(f"/api/razones-sociales/{otra}", json={
        "nombre": "Juan Pérez", "cuit": CUIT_OTRA, "punto_venta": 2,
        "condicion_iva": "monotributo"}).status_code == 200
    ajena = a_mano(sesion, datos, otra, numero=3, tipo=TipoComprobante.FACTURA_C)
    texto = texto_del_pdf(pdf_de(cliente, ajena.id))
    assert "Monotributo" in texto and "Juan P" in texto


@pytest.mark.parametrize("cargado, para_el_pdf", [
    ("01/01/2020", "2020-01-01"), ("1-2-2020", "2020-02-01"), ("2020-03-15", "2020-03-15"),
    ("enero de 2020", ""), ("", ""), (None, ""),
])
def test_el_inicio_de_actividades_llega_al_motor_en_iso(cargado, para_el_pdf):
    assert emisor_de_cargo._inicio_para_el_pdf(cargado) == para_el_pdf


@pytest.mark.con_emisor
def test_la_empresa_de_otro_cuit_no_presta_su_domicilio_ni_su_logo(cliente, datos, sesion):
    """Una razón social que no es la empresa de la instancia no sale con el domicilio ni el logo de la otra."""
    cargar_logo(cliente, cuit=CUIT_EMISOR)
    otra = segunda_razon(cliente, datos)
    ajena = a_mano(sesion, datos, otra, numero=9)

    contenido = pdf_de(cliente, ajena.id)
    assert imagenes_del_pdf(contenido) == 0
    assert "Calle Falsa 123" not in texto_del_pdf(contenido)


@pytest.mark.con_emisor
def test_la_nota_de_credito_tiene_su_pdf_con_el_membrete_de_quien_emitio(cliente, datos):
    cargar_logo(cliente, cuit=CUIT_EMISOR)
    factura = emitida(cliente, datos)

    r = cliente.post(f"/api/comprobantes/{factura['id']}/nota-de-credito", json={"motivo": "Error de tarifa"})
    assert r.status_code == 201, r.text
    nota = r.json()

    guardado = factura_del_motor(nota["id"])["pdf_path"]
    assert guardado and os.path.exists(guardado), "la nota también guarda su PDF"
    assert guardado != factura_del_motor(factura["id"])["pdf_path"], "una nota no pisa a su factura"
    contenido = pdf_de(cliente, nota["id"])
    texto = texto_del_pdf(contenido)
    assert "Nota De Cr" in texto and "Código 003" in texto, "el título y el código de ARCA de una nota de crédito A"
    assert "Suitrans" in texto and CUIT_EMISOR in texto
    assert imagenes_del_pdf(contenido) == 1
    # Y la factura sigue siendo su PDF.
    assert "Código 001" in texto_del_pdf(pdf_de(cliente, factura["id"]))


# ── 3. Qué comprobantes se ven ──────────────────────────────────────────────


def un_comprobante_ajeno(*, cae="75123456789012", ambiente="produccion"):
    """Una fila de `facturas` sin su `comprobantes_cargo`: de otro producto, o cargada por fuera."""
    libracore_core.configure(URL_CORE)
    with libracore_core.get_connection() as conn:
        factura_id = db_facturas.create_factura(
            1, 1, 77, "2026-08-15", "30-12345678-1", "Agro Norte", 1,
            [{"description": "Flete", "qty": 1, "unit_price": 100.0, "subtotal": 100.0}],
            100.0, 21.0, 121.0, ambiente=ambiente, conn=conn)
        if cae:
            db_facturas.update_factura_cae(factura_id, cae, "20261231", conn=conn)
        conn.commit()
    return factura_id


def test_un_comprobante_que_no_es_de_libracargo_no_existe_para_este_router(cliente):
    ajeno = un_comprobante_ajeno()
    assert cliente.get(f"/api/comprobantes/{ajeno}/pdf").status_code == 404
    r = cliente.post(f"/api/comprobantes/{ajeno}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 404
    # Es el mismo 404 de un id que no existe: no delata que está.
    assert cliente.get("/api/comprobantes/99999/pdf").json() == cliente.get(f"/api/comprobantes/{ajeno}/pdf").json()


def test_sin_cae_no_hay_pdf(cliente, datos, sesion):
    """Lo registrado a mano y lo migrado del legado: ARCA no lo conoce, y un PDF suyo parecería una factura."""
    a_mano_sin_cae = a_mano(sesion, datos, datos["razon"], numero=5, cae=None)
    assert cliente.get(f"/api/comprobantes/{a_mano_sin_cae.id}").status_code == 200
    assert cliente.get(f"/api/comprobantes/{a_mano_sin_cae.id}/pdf").status_code == 404
    r = cliente.post(f"/api/comprobantes/{a_mano_sin_cae.id}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 404


def test_uno_de_homologacion_no_se_imprime(cliente, datos, sesion):
    """No queda ninguno por el camino normal (el ensayo se revierte); si apareciera uno, su CAE no vale."""
    de_prueba = a_mano(sesion, datos, datos["razon"], numero=6, ambiente="homologacion")
    assert cliente.get(f"/api/comprobantes/{de_prueba.id}").status_code == 200
    assert cliente.get(f"/api/comprobantes/{de_prueba.id}/pdf").status_code == 404


def test_sin_sesion_no_hay_pdf(cliente, datos, sesion):
    from fastapi.testclient import TestClient

    comp = a_mano(sesion, datos, datos["razon"], numero=8)
    anonimo = TestClient(cliente.app, base_url="https://testserver")
    assert anonimo.get(f"/api/comprobantes/{comp.id}/pdf").status_code == 401
    assert anonimo.post(f"/api/comprobantes/{comp.id}/enviar-email", json={"email": "a@b.test"}).status_code == 401


def test_las_rutas_de_antes_siguen_en_su_lugar(cliente):
    """El router del PDF comparte prefijo con el de comprobantes: no le tapa `/totales` ni `/fce/corresponde`."""
    assert cliente.get("/api/comprobantes/totales").status_code == 200
    assert cliente.get("/api/comprobantes").status_code == 200
    rutas = cliente.app.openapi()["paths"]
    assert "get" in rutas["/api/comprobantes/{factura_id}/pdf"]
    assert "post" in rutas["/api/comprobantes/{factura_id}/enviar-email"]
    assert "post" in rutas["/api/comprobantes/{id_}/nota-de-credito"]


# ── 4. El correo ────────────────────────────────────────────────────────────


@pytest.fixture
def smtp_falso(monkeypatch):
    """Un SMTP configurado y un `enviar_comprobante` que anota lo que recibe en vez de abrir una conexión."""
    enviados = []
    monkeypatch.setattr(motor_facturas, "smtp_efectivo", lambda resolver: {
        "host": "smtp.ejemplo.test", "port": 587, "user": "u", "password": "p",
        "from_email": "facturacion@ejemplo.test", "from_name": "Demo"})
    monkeypatch.setattr(email_sender, "enviar_comprobante", lambda **kw: enviados.append(kw))
    return enviados


@pytest.mark.con_emisor
def test_enviar_por_correo_manda_el_mismo_pdf_firmado_por_la_razon_social(cliente, datos, smtp_falso):
    comp = emitida(cliente, datos)

    r = cliente.post(f"/api/comprobantes/{comp['id']}/enviar-email", json={"email": " compras@agronorte.test "})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    [enviado] = smtp_falso
    assert enviado["to_email"] == "compras@agronorte.test"
    assert enviado["to_name"] == "Agro Norte"
    assert enviado["empresa_nombre"] == "Suitrans", "firma la razón social que emitió, no el slug de ARCA"
    assert enviado["factura_label"] == "FACTURA A 0001-00000001"
    assert open(enviado["pdf_path"], "rb").read() == pdf_de(cliente, comp["id"]), "el que se ve es el que se manda"


@pytest.mark.con_emisor
def test_enviar_por_correo_dice_donde_configurar_el_smtp_y_pide_el_correo(cliente, datos, monkeypatch):
    comp = emitida(cliente, datos)
    monkeypatch.setattr(motor_facturas, "smtp_efectivo", lambda resolver: {
        "host": "", "port": 587, "user": "", "password": "", "from_email": "", "from_name": ""})
    r = cliente.post(f"/api/comprobantes/{comp['id']}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 400
    assert "Configuración → Email" in r.text


@pytest.mark.con_emisor
def test_enviar_sin_correo_o_si_el_servidor_falla(cliente, datos, smtp_falso, monkeypatch):
    comp = emitida(cliente, datos)
    assert cliente.post(f"/api/comprobantes/{comp['id']}/enviar-email", json={"email": "  "}).status_code == 422

    def falla(**kw):
        raise OSError("sin red")

    monkeypatch.setattr(email_sender, "enviar_comprobante", falla)
    r = cliente.post(f"/api/comprobantes/{comp['id']}/enviar-email", json={"email": "compras@agronorte.test"})
    assert r.status_code == 502 and "sin red" in r.text


# ── 5. El resolvedor único, y la pre factura ────────────────────────────────


def test_crear_app_registra_el_resolvedor_en_el_motor(cliente):
    assert emisor_del_motor.resolvedor_registrado() is emisor_de_cargo.resolvedor


@pytest.mark.con_emisor
def test_la_pre_factura_lleva_el_logo_y_la_razon_social(cliente, datos):
    """El mismo resolvedor que los comprobantes: antes la pre factura armaba su emisor aparte y sin logo."""
    pf = pre_factura(cliente, datos, [orden(cliente, datos, "1000.00")]).json()
    sin_logo = cliente.get(f"/api/pre-facturas/{pf['id']}/pdf").content
    assert imagenes_del_pdf(sin_logo) == 0

    cargar_logo(cliente, cuit=CUIT_EMISOR)
    con_logo = cliente.get(f"/api/pre-facturas/{pf['id']}/pdf")
    assert con_logo.status_code == 200
    assert imagenes_del_pdf(con_logo.content) == 1
    texto = texto_del_pdf(con_logo.content)
    assert "Suitrans" in texto and CUIT_EMISOR in texto
    assert "Calle Falsa 123, Suipacha" in texto


@pytest.mark.con_emisor
def test_la_pre_factura_de_otra_razon_social_sale_con_la_suya(cliente, datos):
    otra = segunda_razon(cliente, datos)
    pf = pre_factura(cliente, datos, [orden(cliente, datos, "100.00", razon_social_id=otra)], razon=otra).json()
    texto = texto_del_pdf(cliente.get(f"/api/pre-facturas/{pf['id']}/pdf").content)
    assert "Transportes Demo SRL" in texto and CUIT_DEMO in texto
    assert CUIT_EMISOR not in texto


def test_el_resolvedor_sin_razon_social_conocida_no_agrega_nada(cliente, sesion):
    assert emisor_de_cargo.emisor_de(sesion, {}) is None
    assert emisor_de_cargo.emisor_de(sesion, {"id": 123456}) is None
    # Una pre factura de otro producto no es de acá: su `id` es de otra tabla.
    assert emisor_de_cargo.emisor_de(
        sesion, {"id": 1, "numero_interno": "PF-0001", "origen_producto": "otro-producto"}) is None


@pytest.mark.con_emisor
def test_sin_fila_propia_la_razon_social_sale_del_cuit_del_emisor(cliente, datos, sesion):
    """Un documento con `emisor_id` y nada más: la razón social cuyo CUIT es el del `arca_config`."""
    emisor_id = _id_de_arca()
    elegido = emisor_de_cargo.emisor_de(sesion, {"id": 123456, "emisor_id": emisor_id})
    assert elegido["nombre"] == "Suitrans" and elegido["cuit"] == CUIT_EMISOR

    # Con dos razones sociales del mismo CUIT no se adivina cuál es.
    segunda_razon(cliente, datos, nombre="Suitrans Dos", cuit=CUIT_EMISOR)
    assert emisor_de_cargo.emisor_de(sesion, {"id": 123456, "emisor_id": emisor_id}) is None


def _id_de_arca() -> int:
    from libracore.db import arca_config as db_arca_config

    libracore_core.configure(URL_CORE)
    [cfg] = db_arca_config.obtener_todas_arca_configs()
    return cfg["id"]


def test_el_resolvedor_registrado_abre_su_propia_sesion(cliente, datos, sesion):
    """Lo llama el motor sin la sesión del pedido: lee la base por su cuenta."""
    comp = a_mano(sesion, datos, datos["razon"], numero=11)
    assert emisor_de_cargo.resolvedor({"id": comp.id})["nombre"] == "Suitrans"
