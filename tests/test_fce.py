"""La Factura de Crédito Electrónica MiPyME (FCE).

Los valores de ARCA que se esperan acá (los códigos 201, 206 y 211, el vencimiento
de pago obligatorio, el CBU en el opcional 2101 y la transmisión en el 27) salen del
manual del WSFE y de lo **medido en homologación el 2026-10-02**: no de este código.
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from libracore import arca_wsfe
from sqlalchemy.exc import IntegrityError

from app.models import Comprobante, RazonSocial, Tercero, TipoComprobante
from app.models.enums import CondicionIVA
from app.servicios import emision_arca
from tests.conftest import _crear
from tests.test_comprobantes import orden
from tests.test_emision_arca import CUIT, _arca_responde, _configurar_arca

CBU = "0123456789012345678901"          # 22 dígitos
CUIT_DEL_RECEPTOR = "30-70933285-2"
# Fechas **relativas a hoy**: ARCA compara el vencimiento de pago contra hoy, y el
# backend también, así que con fechas fijas estos tests se romperían con el tiempo.
HOY = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
FECHA = HOY.isoformat()
VENCIMIENTO = (HOY + timedelta(days=30)).isoformat()


def _facturar(cliente, datos, ordenes, razon, *, tipo="fce_a", vencimiento=VENCIMIENTO):
    cuerpo = {
        "fecha": FECHA, "razon_social_id": razon, "cliente_id": datos["cliente"],
        "tipo": tipo, "punto_venta": 5,
        "orden_ids": [o["id"] if isinstance(o, dict) else o for o in ordenes],
    }
    if vencimiento is not None:
        cuerpo["fecha_vencimiento_pago"] = vencimiento
    return cliente.post("/api/comprobantes", json=cuerpo)


def _receptor_con_cuit(cliente, datos):
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True,
        "condicion_iva": "responsable_inscripto", "cuit": CUIT_DEL_RECEPTOR,
    })
    assert r.status_code == 200, r.text


def _configurar_fce(cliente, *, cbu=CBU, transmision="SCA"):
    """El CBU y la modalidad viajan por la configuración de ARCA que ya existe."""
    r = cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT, "punto_venta": 5,
        "ambiente": "produccion", "alias": "",
        "fce_cbu": cbu, "fce_transmision": transmision,
    })
    assert r.status_code == 200, r.text


@pytest.fixture
def razon_con_fce(cliente, datos):
    """Una razón social que emite por ARCA, con el CBU y la modalidad cargados."""
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5,
    })
    _configurar_arca(cliente)
    _configurar_fce(cliente)
    _receptor_con_cuit(cliente, datos)
    return razon


# ── Emitir ──────────────────────────────────────────────────────────────────

def test_una_fce_viaja_a_arca_con_su_codigo_y_lo_que_exige(cliente, datos, razon_con_fce,
                                                          monkeypatch):
    """Código 201, vencimiento de pago, y el CBU y la transmisión de la configuración."""
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    r = _facturar(cliente, datos, [a], razon_con_fce)

    assert r.status_code == 201, r.text
    assert ("ultimo", 5, 201, CUIT) in pedidos, "el número se pide para el tipo 201"
    (factura,) = [p[1] for p in pedidos if p[0] == "cae"]
    assert factura["tipo"] == 201
    assert factura["fch_vto_pago"] == VENCIMIENTO
    assert factura["fce_cbu"] == CBU
    assert factura["fce_transmision"] == "SCA"
    assert arca_wsfe.cuit_del_receptor(factura) == "30709332852"


def test_la_fce_guarda_con_que_salio(cliente, datos, razon_con_fce, monkeypatch):
    """El CBU y la modalidad quedan **en el comprobante**, no sólo en la configuración."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    comp = _facturar(cliente, datos, [a], razon_con_fce).json()

    assert comp["tipo"] == "fce_a"
    assert comp["numero"] == 42 and comp["cae"]
    assert comp["fch_vto_pago"] == VENCIMIENTO
    assert comp["fce_cbu"] == CBU
    assert comp["fce_transmision"] == "SCA"
    # Cambiar la configuración después no reescribe lo que ya salió.
    _configurar_fce(cliente, cbu="9999999999999999999999", transmision="ADC")
    de_nuevo = cliente.get(f"/api/comprobantes/{comp['id']}").json()["comprobante"]
    assert de_nuevo["fce_cbu"] == CBU and de_nuevo["fce_transmision"] == "SCA"


@pytest.mark.parametrize("tipo, codigo", [("fce_a", 201), ("fce_b", 206), ("fce_c", 211)])
def test_los_tres_tipos_tienen_su_codigo(cliente, datos, razon_con_fce, monkeypatch,
                                         tipo, codigo):
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    assert _facturar(cliente, datos, [a], razon_con_fce, tipo=tipo).status_code == 201
    assert ("ultimo", 5, codigo, CUIT) in pedidos


def test_una_fce_c_no_discrimina_el_iva(cliente, datos, razon_con_fce, monkeypatch):
    """Como cualquier clase C: todo el importe va como neto y no hay alícuota."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    _facturar(cliente, datos, [a], razon_con_fce, tipo="fce_c")

    (factura,) = [p[1] for p in pedidos if p[0] == "cae"]
    assert factura["iva_amount"] == 0.0
    assert factura["subtotal"] == float(Decimal("1210.00"))


def test_la_fce_entra_en_los_totales_y_en_la_cuenta_corriente(cliente, datos, razon_con_fce,
                                                              monkeypatch):
    """Lo que la FCE no puede hacer es desaparecer de un listado."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)
    assert _facturar(cliente, datos, [a], razon_con_fce).status_code == 201

    totales = cliente.get("/api/comprobantes/totales").json()
    suyo = next(t for t in totales if t["razon_social_id"] == razon_con_fce)
    assert Decimal(suyo["total_comprobantes"]) == Decimal("1210.00")
    assert suyo["coinciden"] is True

    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    concepto = cuenta["movimientos"][0]["movimiento"]["concepto"]
    assert concepto == "Factura de credito electronica A 0005-00000042", concepto


@pytest.mark.parametrize("cuit", ["30-70933285-2", "30.70933285.2", "30 70933285 2", "30709332852"])
def test_el_cuit_viaja_a_arca_en_digitos_sea_cual_sea_como_se_cargo(
        cliente, datos, razon_con_fce, monkeypatch, cuit):
    """El CUIT llega a ARCA en dígitos sea cual sea como se cargó (con guiones, puntos o espacios).

    Lo normaliza **el motor** (`arca_wsfe.cuit_del_receptor`, libracore v1.124.0): antes sólo quitaba
    guiones y espacios, y con puntos el CUIT llegaba como «no es un CUIT»; este producto lo reducía
    a dígitos por su cuenta. Ese parche se retiró (el arreglo de fondo vive en el motor): el producto
    manda el CUIT tal cual y el test mira lo que el motor haría con él."""
    cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True,
        "condicion_iva": "responsable_inscripto", "cuit": cuit,
    })
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    assert _facturar(cliente, datos, [a], razon_con_fce).status_code == 201
    (factura,) = [p[1] for p in pedidos if p[0] == "cae"]
    assert arca_wsfe.cuit_del_receptor(factura) == "30709332852"


# ── Lo que se rechaza, y dónde ──────────────────────────────────────────────

def test_una_fce_sin_vencimiento_de_pago_se_rechaza(cliente, datos, razon_con_fce):
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    r = _facturar(cliente, datos, [a], razon_con_fce, vencimiento=None)

    assert r.status_code == 422, r.text
    assert "vencimiento de pago" in r.text


def test_el_vencimiento_no_puede_ser_anterior_a_la_fecha(cliente, datos, razon_con_fce):
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    ayer = (HOY - timedelta(days=1)).isoformat()
    r = _facturar(cliente, datos, [a], razon_con_fce, vencimiento=ayer)

    assert r.status_code == 422, r.text
    assert "anterior a la fecha" in r.text


def test_el_vencimiento_no_puede_estar_ya_vencido_aunque_la_fecha_sea_atrasada(
        cliente, datos, razon_con_fce, monkeypatch):
    """ARCA compara el vencimiento contra hoy (10164): una FCE con fecha de hace 3 días y un
    vencimiento de ayer es posterior a la fecha y aun así se rechaza. Se dice antes de pedir
    el número, no como un 502."""
    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)
    cuerpo = {
        "fecha": (HOY - timedelta(days=3)).isoformat(), "razon_social_id": razon_con_fce,
        "cliente_id": datos["cliente"], "tipo": "fce_a", "punto_venta": 5,
        "orden_ids": [a["id"]],
        "fecha_vencimiento_pago": (HOY - timedelta(days=1)).isoformat(),
    }

    r = cliente.post("/api/comprobantes", json=cuerpo)

    assert r.status_code == 422, r.text
    assert "anterior a hoy" in r.text
    assert pedidos == [], "no tenía que ir a ARCA"


def test_el_vencimiento_igual_a_hoy_es_valido(cliente, datos, razon_con_fce, monkeypatch):
    """Medido en homologación el 2026-10-02: el mismo día se autoriza; sólo uno anterior se rechaza."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    assert _facturar(cliente, datos, [a], razon_con_fce, vencimiento=FECHA).status_code == 201


def test_una_factura_comun_no_lleva_vencimiento_de_pago(cliente, datos, razon_con_fce):
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    r = _facturar(cliente, datos, [a], razon_con_fce, tipo="factura_a", vencimiento=VENCIMIENTO)

    assert r.status_code == 422, r.text


@pytest.mark.parametrize("cuit", ["", "1", "30-7093328", "30.7093328.2"])
def test_una_fce_a_un_cliente_sin_un_cuit_valido_se_rechaza_antes_de_ir_a_arca(
        cliente, datos, razon_con_fce, monkeypatch, cuit):
    """ARCA contestaría 10015, o un 502 por un CUIT a medio cargar: acá se dice qué cargar
    y no se le pregunta nada. «Algún dígito» no alcanza: tienen que ser los 11."""
    cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True, "cuit": cuit,
    })
    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    r = _facturar(cliente, datos, [a], razon_con_fce)

    assert r.status_code == 422, r.text
    assert "CUIT de 11 digitos" in r.text and "ficha del cliente" in r.text
    assert pedidos == [], "no tenía que ir a ARCA"


def test_una_fce_sin_arca_habilitado_no_se_puede_registrar_a_mano(cliente, datos):
    """Una FCE sin CAE no existe: no hay camino de «registrar con el número que tengo»."""
    _receptor_con_cuit(cliente, datos)
    a = orden(cliente, datos, "1000.00")

    r = cliente.post("/api/comprobantes", json={
        "fecha": FECHA, "razon_social_id": datos["razon"], "cliente_id": datos["cliente"],
        "tipo": "fce_a", "punto_venta": 1, "numero": 7, "orden_ids": [a["id"]],
        "fecha_vencimiento_pago": VENCIMIENTO,
    })

    assert r.status_code == 422, r.text
    assert "solo se emite por ARCA" in r.text
    assert cliente.get("/api/comprobantes").json() == []


def test_si_arca_rechaza_la_fce_no_queda_comprobante(cliente, datos, razon_con_fce, monkeypatch):
    _arca_responde(monkeypatch, falla_cae="FchVtoPago debe ser posterior a la fecha")
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    r = _facturar(cliente, datos, [a], razon_con_fce)

    assert r.status_code == 502, r.text
    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


# ── Lo que sale hacia ARCA, sin mockear `solicitar_cae` ─────────────────────

def _soap_de_arca(monkeypatch):
    """Deja pasar `solicitar_cae` del motor y captura el SOAP que enviaría."""
    enviados = []

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        return {"token": "TKN", "sign": "SGN"}

    async def soap(url, accion, cuerpo):
        enviados.append((accion, cuerpo))
        if accion == "FECompUltimoAutorizado":
            return ET.fromstring("<r><CbteNro>41</CbteNro></r>")
        return ET.fromstring(
            "<r><FECAEDetResponse><Resultado>A</Resultado><CAE>75123456789012</CAE>"
            "<CAEFchVto>20261231</CAEFchVto></FECAEDetResponse></r>")

    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "_soap", soap)
    return enviados


def test_el_sobre_de_una_fce_lleva_vencimiento_cbu_y_transmision(
        cliente, datos, razon_con_fce, monkeypatch):
    """El test que no mockea el motor: mira el SOAP real, que es lo que ARCA valida."""
    enviados = _soap_de_arca(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)

    r = _facturar(cliente, datos, [a], razon_con_fce)

    assert r.status_code == 201, r.text
    (pedido,) = [c for acc, c in enviados if acc == "FECAESolicitar"]
    assert "<CbteTipo>201</CbteTipo>" in pedido
    assert f"<FchVtoPago>{VENCIMIENTO.replace('-', '')}</FchVtoPago>" in pedido
    assert f"<Opcional><Id>2101</Id><Valor>{CBU}</Valor></Opcional>" in pedido
    assert "<Opcional><Id>27</Id><Valor>SCA</Valor></Opcional>" in pedido
    assert "<DocTipo>80</DocTipo>" in pedido, "una FCE se emite a un receptor con CUIT"


def test_una_fce_sin_cbu_cargado_dice_que_cargar(cliente, datos, monkeypatch):
    """Sin el CBU en la configuración el motor falla y el mensaje llega a la pantalla."""
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5})
    _configurar_arca(cliente)           # ARCA sí, pero sin CBU ni transmisión
    _receptor_con_cuit(cliente, datos)
    _soap_de_arca(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)

    r = _facturar(cliente, datos, [a], razon)

    assert r.status_code == 502, r.text
    assert "CBU" in r.text and "configuración de ARCA" in r.text
    assert cliente.get("/api/comprobantes").json() == []


# ── La base ─────────────────────────────────────────────────────────────────

def _comprobante(sesion, **campos):
    razon = RazonSocial(nombre="Suitrans", punto_venta=1, codigo_legado=1)
    cli = Tercero(razon_social="ACOPIO SUR SA", es_cliente=True,
                  condicion_iva=CondicionIVA.RESPONSABLE_INSCRIPTO)
    sesion.add_all([razon, cli])
    sesion.commit()
    base = dict(razon_social_id=razon.id, tipo=TipoComprobante.FCE_A, punto_venta=1,
                numero=1, fecha=date(2026, 8, 15), cliente_id=cli.id,
                neto=Decimal("100"), iva=Decimal("21"), total=Decimal("121"))
    return Comprobante(**{**base, **campos})


def test_la_base_no_admite_una_fce_sin_vencimiento_de_pago(sesion):
    sesion.add(_comprobante(sesion))
    with pytest.raises(IntegrityError, match="ck_comprobantes_fce_vencimiento"):
        sesion.commit()


def test_la_base_admite_una_fce_con_vencimiento_y_una_factura_comun_sin_el(sesion):
    fce = _comprobante(sesion, fch_vto_pago=date(2026, 9, 14), fce_cbu=CBU, fce_transmision="SCA")
    sesion.add(fce)
    sesion.commit()
    sesion.add(Comprobante(
        razon_social_id=fce.razon_social_id, tipo=TipoComprobante.FACTURA_A, punto_venta=1,
        numero=2, fecha=date(2026, 8, 15), cliente_id=fce.cliente_id,
        neto=Decimal("1"), iva=Decimal("0.21"), total=Decimal("1.21")))
    sesion.commit()


# ── Anular ──────────────────────────────────────────────────────────────────

def test_una_fce_emitida_no_se_anula_desde_aca(cliente, datos, razon_con_fce, monkeypatch):
    """🔴 Anular localmente no llega a ARCA: la FCE seguiría vigente allá mientras las
    órdenes vuelven a pendientes y se pueden facturar otra vez."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_fce)
    comp = _facturar(cliente, datos, [a], razon_con_fce).json()

    r = cliente.delete(f"/api/comprobantes/{comp['id']}")

    assert r.status_code == 409, r.text
    assert "nota de credito" in r.text
    quedo = cliente.get(f"/api/comprobantes/{comp['id']}").json()
    assert quedo["comprobante"]["anulado"] is False
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "facturada", \
        "las órdenes no tienen que reabrirse"
