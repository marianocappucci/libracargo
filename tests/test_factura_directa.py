"""«Nueva factura»: conceptos libres, sin órdenes ni remitos, directo por ARCA (ADR-048).

> 🔑 **Los datos son ficticios**: «Agro Norte», el CUIT 30-12345678-1 del receptor y el 20-12345678-6 de la empresa.

Una factura directa **no tiene órdenes contra las que comprobarse**, y esa es la mitad de lo que se mide acá:

1. La aritmética de los conceptos la hace el servidor (el IVA sobre el neto, una sola alícuota por comprobante, la
   clase C sin IVA) y es lo que viaja a ARCA.
2. La clase que corresponde: el emisor manda (monotributo C, inscripto A o B), después el receptor.
3. Las mismas garantías de toda emisión: sin certificado 409 y nada se toca, ARCA que rechaza no deja nada, el ensayo
   contra homologación se revierte, un doble clic emite una sola.
4. Lo que **no** se rompe: el gate de F5 no la pone en rojo (`sin_ordenes`), suma a la cuenta corriente y a lo
   facturado, y se acredita con una nota de crédito como cualquier factura.
"""

import asyncio
import threading
import time
from decimal import Decimal

import pytest
from libracore import arca_wsfe

from app.models.enums import CODIGO_ARCA, CondicionIVA
from app.schemas.comprobantes import ALICUOTAS_DE_IVA
from app.servicios import facturacion
from tests.conftest import CUIT_EMISOR, arca_responde, cargar_empresa
from tests.test_comprobantes import facturar, orden
from tests.test_pdf_de_comprobantes import pdf_de, texto_del_pdf

pytestmark = pytest.mark.con_emisor

CUIT_RECEPTOR = "30-12345678-1"


def concepto(descripcion="Flete Suipacha - Rosario", cantidad="1", precio="1000.00", alicuota="21"):
    return {"descripcion": descripcion, "cantidad": cantidad, "precio_unitario": precio, "alicuota_iva": alicuota}


def directa(cliente, datos, conceptos=None, *, tipo="factura_b", cliente_id=None, fecha="2026-08-15", **extra):
    """«Nueva factura». Por omisión B: el cliente de la suite es consumidor final, y a ése le corresponde B."""
    cuerpo = {"fecha": fecha, "cliente_id": cliente_id or datos["cliente"], "tipo": tipo,
              "conceptos": conceptos if conceptos is not None else [concepto()], **extra}
    return cliente.post("/api/comprobantes/directa", json=cuerpo)


def receptor(cliente, datos, condicion, *, cuit=CUIT_RECEPTOR):
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True, "condicion_iva": condicion, "cuit": cuit})
    assert r.status_code == 200, r.text


def pedido_a_arca(pedidos):
    return next(p[1] for p in reversed(pedidos) if p[0] == "cae")


def cuenta(cliente, datos):
    return cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()


# ── 1. El camino feliz y la aritmética ──────────────────────────────────────


def test_la_factura_directa_sale_con_cae_y_suma_a_la_cuenta_del_cliente(cliente, datos, emisor):
    r = directa(cliente, datos)
    assert r.status_code == 201, r.text
    comp = r.json()

    assert comp["tipo"] == "factura_b" and comp["cae"] == "75123456789012"
    assert (comp["punto_venta"], comp["numero"]) == (1, 1), "el número lo da ARCA; el punto de venta, su configuración"
    assert comp["sin_ordenes"] is True
    assert (comp["neto"], comp["iva"], comp["total"]) == ("1000.00", "210.00", "1210.00")
    # A ARCA va lo mismo que quedó guardado.
    pedido = pedido_a_arca(emisor)
    assert (pedido["tipo"], pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (6, 1000.0, 210.0, 1210.0)
    assert pedido["cliente_iva_cond"] == 5, "consumidor final"

    # La deuda del cliente entra en el libro del motor con el número real.
    c = cuenta(cliente, datos)
    (mov,) = [m["movimiento"] for m in c["movimientos"]]
    assert mov["concepto"] == "Factura B 0001-00000001"
    assert mov["descripcion"] == "Factura directa: Flete Suipacha - Rosario"
    assert (Decimal(mov["debe"]), Decimal(mov["haber"])) == (Decimal("1210.00"), Decimal(0))
    assert mov["comprobante_id"] == comp["id"]
    assert Decimal(c["saldo"]) == Decimal("1210.00") and c["coinciden"] is True


def test_el_detalle_de_una_factura_directa_no_marca_alarma_por_no_tener_ordenes(cliente, datos):
    comp = directa(cliente, datos).json()
    detalle = cliente.get(f"/api/comprobantes/{comp['id']}").json()
    assert detalle["ordenes"] == [] and detalle["coinciden"] is True
    assert detalle["saldo_acreditable"] == "1210.00", "se puede acreditar como cualquier factura con CAE"


def test_varios_conceptos_el_iva_se_calcula_una_vez_sobre_el_neto(cliente, datos, emisor):
    """`3 × 33.33 = 99.99` y `2 × 10.01 = 20.02`: neto 120.01 y IVA `25.2021 → 25.20`, no la suma de IVA redondeados."""
    r = directa(cliente, datos, [concepto("Flete", "3", "33.33"), concepto("Peaje", "2", "10.01")])
    assert r.status_code == 201, r.text
    assert (r.json()["neto"], r.json()["iva"], r.json()["total"]) == ("120.01", "25.20", "145.21")
    pedido = pedido_a_arca(emisor)
    assert (pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (120.01, 25.2, 145.21)
    # Los ítems quedan como se cargaron: lo que lee el PDF.
    from tests.test_facturar_ordenes import _factura_del_motor

    items = _factura_del_motor(r.json()["id"])["items"]
    assert [(i["description"], i["qty"], i["unit_price"], i["subtotal"]) for i in items] == [
        ("Flete", 3.0, 33.33, 99.99), ("Peaje", 2.0, 10.01, 20.02)]


def test_cantidades_con_decimales_y_el_redondeo_va_al_centavo_hacia_arriba(cliente, datos):
    """`1.5 × 0.01 = 0.015` va a `0.02` (mitad hacia arriba), no a `0.01` del redondeo bancario de Python."""
    r = directa(cliente, datos, [concepto("Hora de espera", "1.5", "0.01"), concepto("Otra", "1", "100.00")])
    assert r.status_code == 201, r.text
    assert r.json()["neto"] == "100.02"


@pytest.mark.parametrize("alicuota, iva_esperado", [
    ("0", "0.00"), ("10.5", "105.00"), ("21", "210.00"), ("27", "270.00")])
def test_las_alicuotas_que_arca_conoce(cliente, datos, emisor, alicuota, iva_esperado):
    r = directa(cliente, datos, [concepto(alicuota=alicuota)])
    assert r.status_code == 201, r.text
    assert r.json()["iva"] == iva_esperado
    assert pedido_a_arca(emisor)["iva_amount"] == float(iva_esperado)


def test_las_alicuotas_ofrecidas_son_las_que_conoce_el_wsfe_del_motor():
    """Si el motor suma o saca una alícuota (`arca_wsfe._IVA_ID`), esto avisa antes de que ARCA reciba otra."""
    assert {float(a) for a in ALICUOTAS_DE_IVA} == set(float(k) for k in arca_wsfe._IVA_ID if k != 10)


@pytest.mark.parametrize("alicuota", ["19", "2.5", "-1", "100", "abc"])
def test_una_alicuota_que_arca_no_recibe_se_rechaza(cliente, datos, alicuota):
    r = directa(cliente, datos, [concepto(alicuota=alicuota)])
    assert r.status_code == 422, r.text
    assert cliente.get("/api/comprobantes").json() == []


def test_mezclar_alicuotas_se_rechaza_porque_arca_recibe_un_solo_bloque_de_iva(cliente, datos, emisor):
    r = directa(cliente, datos, [concepto(alicuota="21"), concepto("Seguro", alicuota="10.5")])
    assert r.status_code == 422, r.text
    assert "misma alicuota" in r.text and "10.5%" in r.text and "21%" in r.text
    assert emisor == [], "no se le pidió nada a ARCA"
    assert cliente.get("/api/comprobantes").json() == []


@pytest.mark.parametrize("mal", [
    {"cantidad": "0"}, {"cantidad": "-1"}, {"cantidad": "1.2345"}, {"cantidad": True},
    {"precio_unitario": "0"}, {"precio_unitario": "-5.00"}, {"precio_unitario": "1.005"}, {"precio_unitario": True},
    {"descripcion": ""}, {"descripcion": "   "}, {"descripcion": "x" * 201},
])
def test_un_concepto_mal_formado_se_rechaza(cliente, datos, mal):
    r = directa(cliente, datos, [concepto() | mal])
    assert r.status_code == 422, mal
    assert cliente.get("/api/comprobantes").json() == []


def test_sin_conceptos_o_con_demasiados_se_rechaza(cliente, datos):
    assert directa(cliente, datos, []).status_code == 422
    assert directa(cliente, datos, [concepto(f"c{i}", precio="1.00") for i in range(51)]).status_code == 422


def test_el_cuerpo_no_acepta_importes_ni_punto_de_venta_ni_numero_ni_ordenes(cliente, datos):
    """Los importes los calcula el servidor: aceptarlos del cliente permitiría una factura que diga otro total."""
    for extra in ({"punto_venta": 1}, {"numero": 7}, {"total": "1.00"}, {"neto": "1.00"}, {"iva": "0.21"},
                  {"orden_ids": [1]}, {"items": []}):
        assert directa(cliente, datos, **extra).status_code == 422, extra
    assert cliente.get("/api/comprobantes").json() == []


def test_un_cliente_que_no_existe_da_404(cliente, datos):
    assert directa(cliente, datos, cliente_id=9999).status_code == 404


def test_una_nota_no_se_factura_desde_aca(cliente, datos):
    for tipo in ("nota_credito_b", "nota_debito_b"):
        r = directa(cliente, datos, tipo=tipo)
        assert r.status_code == 422 and "una nota no se factura desde aca" in r.text, tipo


def test_las_observaciones_van_al_comprobante(cliente, datos):
    from tests.test_facturar_ordenes import _factura_del_motor

    comp = directa(cliente, datos, observaciones="Servicio de flete extraordinario").json()
    assert _factura_del_motor(comp["id"])["observaciones"] == "Servicio de flete extraordinario"


def test_el_alta_deja_un_asiento_de_auditoria(cliente, datos):
    comp = directa(cliente, datos).json()
    registros = cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"]
    assert [(r["entidad_id"], r["accion"]) for r in registros] == [(comp["id"], "alta")]


def test_el_pdf_de_una_factura_directa_lleva_la_empresa_y_los_conceptos(cliente, datos):
    comp = directa(cliente, datos, [concepto("Servicio de flete extraordinario")]).json()
    texto = texto_del_pdf(pdf_de(cliente, comp["id"]))
    assert "Transportes de Prueba" in texto and CUIT_EMISOR in texto
    assert "Servicio de flete extraordinario" in texto


# ── 2. La clase que corresponde ─────────────────────────────────────────────


def test_el_emisor_manda_y_despues_el_receptor():
    inscripto, mono, exento = (CondicionIVA.RESPONSABLE_INSCRIPTO, CondicionIVA.MONOTRIBUTO, CondicionIVA.EXENTO)

    def codigos(emisor, rec):
        return [CODIGO_ARCA[t] for t in facturacion.tipos_permitidos(emisor, rec)]

    # Inscripto: A a inscriptos y monotributistas, B a todos los demás, las dos si no se sabe.
    assert codigos(inscripto, inscripto) == [1, 201]
    assert codigos(inscripto, mono) == [1, 201]
    assert codigos(inscripto, CondicionIVA.CONSUMIDOR_FINAL) == [6, 206]
    assert codigos(inscripto, exento) == [6, 206]
    assert codigos(inscripto, CondicionIVA.NO_CATEGORIZADO) == [1, 6, 201, 206]
    assert codigos(inscripto, None) == [1, 6, 201, 206]
    # Monotributo: sólo C, a cualquiera.
    assert codigos(mono, inscripto) == codigos(mono, CondicionIVA.CONSUMIDOR_FINAL) == [11, 211]
    # Exento: B (y la FCE no se le ofrece: el motor no la habilita para exentos).
    assert codigos(exento, inscripto) == []
    assert codigos(exento, CondicionIVA.CONSUMIDOR_FINAL) == [6]
    # Una condición que no emite, o ninguna: no tiene tipos.
    assert codigos(CondicionIVA.CONSUMIDOR_FINAL, inscripto) == []
    assert codigos(None, inscripto) == []


@pytest.mark.parametrize("condicion, tipo, status", [
    ("responsable_inscripto", "factura_a", 201),
    ("monotributo", "factura_a", 201),
    ("responsable_inscripto", "factura_b", 422),     # a un inscripto le corresponde A (ARCA: 10243)
    ("monotributo", "factura_b", 422),
    ("consumidor_final", "factura_b", 201),
    ("consumidor_final", "factura_a", 422),
    ("exento", "factura_b", 201),
    ("responsable_inscripto", "factura_c", 422),     # la empresa es inscripta: no emite C
])
def test_la_clase_tiene_que_ser_la_que_corresponde_al_cliente(cliente, datos, condicion, tipo, status):
    receptor(cliente, datos, condicion)
    r = directa(cliente, datos, tipo=tipo)
    assert r.status_code == status, r.text
    if status == 422:
        assert "le corresponde" in r.text
        assert cliente.get("/api/comprobantes").json() == []


def test_un_monotributista_solo_emite_c_y_sin_iva(cliente, datos, emisor):
    cargar_empresa(cliente, condicion_iva="monotributo")
    receptor(cliente, datos, "responsable_inscripto")

    a = directa(cliente, datos, tipo="factura_a")
    assert a.status_code == 422 and "Monotributista" in a.text and "Factura C" in a.text

    # En una C el precio es el total y la alícuota que se mande se ignora: no se inventa un impuesto.
    r = directa(cliente, datos, [concepto(precio="1000.00", alicuota="21")], tipo="factura_c")
    assert r.status_code == 201, r.text
    assert (r.json()["neto"], r.json()["iva"], r.json()["total"]) == ("1000.00", "0.00", "1000.00")
    pedido = pedido_a_arca(emisor)
    assert (pedido["tipo"], pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (11, 1000.0, 0.0, 1000.0)
    # Y las alícuotas mezcladas no importan en una C: no hay IVA que mezclar.
    r = directa(cliente, datos, [concepto(alicuota="21"), concepto("Otro", alicuota="10.5")], tipo="factura_c")
    assert r.status_code == 201, r.text


def test_una_empresa_sin_condicion_de_iva_no_emite_y_dice_que_la_cargue(cliente, datos):
    cargar_empresa(cliente, condicion_iva=None)
    r = directa(cliente, datos)
    assert r.status_code == 422 and "condicion de IVA" in r.text and "Datos de la empresa" in r.text
    assert cliente.get("/api/comprobantes").json() == []


def test_las_opciones_de_tipo_para_la_pantalla(cliente, datos):
    receptor(cliente, datos, "responsable_inscripto")
    r = cliente.get("/api/comprobantes/tipos", params={"cliente_id": datos["cliente"]}).json()
    assert r["tipos"] == ["factura_a"] and r["sugerido"] == "factura_a" and r["problema"] is None
    assert r["fce_habilitada"] is False, "sin CBU ni modalidad en la configuración de ARCA"

    receptor(cliente, datos, "consumidor_final")
    r = cliente.get("/api/comprobantes/tipos", params={"cliente_id": datos["cliente"]}).json()
    assert r["tipos"] == ["factura_b"] and r["sugerido"] == "factura_b"

    # Sin cliente elegido: las dos del inscripto, sin sugerir una.
    r = cliente.get("/api/comprobantes/tipos").json()
    assert r["tipos"] == ["factura_a", "factura_b"] and r["sugerido"] is None

    assert cliente.get("/api/comprobantes/tipos", params={"cliente_id": 9999}).status_code == 404
    cargar_empresa(cliente, condicion_iva=None)
    r = cliente.get("/api/comprobantes/tipos").json()
    assert r["tipos"] == [] and "condición de IVA" in r["problema"]


def test_la_fce_se_ofrece_cuando_la_empresa_puede_emitirla_y_el_cliente_es_una_empresa(cliente, datos):
    receptor(cliente, datos, "responsable_inscripto")
    cliente.put("/api/arca", json={
        "empresa": "agencia", "cuit": CUIT_EMISOR, "punto_venta": 1, "ambiente": "produccion", "alias": "",
        "fce_cbu": "0000003100012345678901", "fce_transmision": "SCA"})
    r = cliente.get("/api/comprobantes/tipos", params={"cliente_id": datos["cliente"]}).json()
    assert r["tipos"] == ["factura_a", "fce_a"] and r["fce_habilitada"] is True

    # Un cliente sin CUIT de 11 dígitos no recibe FCE (ARCA: 10015).
    receptor(cliente, datos, "responsable_inscripto", cuit="")
    r = cliente.get("/api/comprobantes/tipos", params={"cliente_id": datos["cliente"]}).json()
    assert "fce_a" not in r["tipos"] and r["fce_habilitada"] is False


def test_una_fce_directa_lleva_vencimiento_cbu_y_modalidad(cliente, datos, emisor):
    receptor(cliente, datos, "responsable_inscripto")
    cliente.put("/api/arca", json={
        "empresa": "agencia", "cuit": CUIT_EMISOR, "punto_venta": 1, "ambiente": "produccion", "alias": "",
        "fce_cbu": "0000003100012345678901", "fce_transmision": "sca"})

    sin_vencimiento = directa(cliente, datos, tipo="fce_a", fecha="2099-01-01")
    assert sin_vencimiento.status_code == 422 and "vencimiento" in sin_vencimiento.text

    r = directa(cliente, datos, tipo="fce_a", fecha="2099-01-01", fecha_vencimiento_pago="2099-02-01")
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["tipo"] == "fce_a" and comp["fch_vto_pago"] == "2099-02-01"
    assert comp["fce_cbu"] == "0000003100012345678901" and comp["fce_transmision"] == "SCA"
    assert pedido_a_arca(emisor)["fch_vto_pago"] == "2099-02-01"
    assert cuenta(cliente, datos)["movimientos"][0]["movimiento"]["concepto"].startswith("Factura de credito")


# ── 3. Las garantías de toda emisión ────────────────────────────────────────


def test_sin_certificado_no_se_factura_y_no_se_toca_nada(cliente, datos):
    from libracore.db import arca_config as db_arca_config

    for fila in db_arca_config.obtener_todas_arca_configs():
        db_arca_config.eliminar_arca_config(fila["empresa"])
    r = directa(cliente, datos)
    assert r.status_code == 409, r.text
    assert "ARCA no está configurado" in r.json()["detail"] and "No se emitió nada" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []
    assert cuenta(cliente, datos)["movimientos"] == []
    assert cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"] == []


def test_si_arca_rechaza_no_queda_nada(cliente, datos, monkeypatch):
    arca_responde(monkeypatch, falla_cae="El comprobante ya fue autorizado")
    r = directa(cliente, datos)
    assert r.status_code == 502 and "ya fue autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []
    assert cuenta(cliente, datos)["movimientos"] == []
    arca_responde(monkeypatch)
    assert directa(cliente, datos).status_code == 201, "y se puede reintentar"


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, monkeypatch):
    arca_responde(monkeypatch, falla_numero="Computador no autorizado")
    r = directa(cliente, datos)
    assert r.status_code == 502 and "no autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == []


def test_con_el_cuit_del_cliente_roto_se_dice_antes_de_ir_a_arca(cliente, datos, emisor):
    receptor(cliente, datos, "responsable_inscripto", cuit="")
    r = directa(cliente, datos, tipo="factura_a")
    assert r.status_code == 422 and "CUIT" in r.text
    assert all(p[0] != "cae" for p in emisor)


def test_un_ensayo_contra_homologacion_se_corre_entero_y_no_deja_nada(cliente, datos, monkeypatch):
    from tests.conftest import configurar_arca

    configurar_arca(cliente, cuit=CUIT_EMISOR, punto_venta=1, ambiente="homologacion")
    pedidos = arca_responde(monkeypatch, ultimo=41)

    r = directa(cliente, datos)
    assert r.status_code == 200, r.text   # 200 y no 201: no se creó nada
    cuerpo = r.json()
    assert cuerpo["ensayo"] is True and cuerpo["ambiente"] == "homologacion" and cuerpo["numero"] == 42
    assert "id" not in cuerpo
    assert [p[0] for p in pedidos] == ["autenticar", "ultimo", "cae"], "habló con ARCA de verdad"

    assert cliente.get("/api/comprobantes").json() == []
    assert cuenta(cliente, datos)["movimientos"] == [], "una prueba no mueve la cuenta del cliente"
    assert cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"] == []


def test_un_doble_clic_emite_una_sola_factura(cliente, datos, monkeypatch):
    """🔴 Sin órdenes que lo frenen, lo único que lo impide es el candado de la base (por cliente)."""
    pedidos = arca_responde(monkeypatch)
    from app.servicios import emision_arca

    real = emision_arca.arca_wsfe.solicitar_cae
    adentro = threading.Event()

    async def cae_lento(*args, **kwargs):
        adentro.set()
        await asyncio.sleep(0.5)
        return await real(*args, **kwargs)

    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", cae_lento)
    respuestas = []

    def pedir():
        respuestas.append(directa(cliente, datos))

    primero = threading.Thread(target=pedir)
    primero.start()
    assert adentro.wait(10)
    time.sleep(0.1)
    segundo = threading.Thread(target=pedir)
    segundo.start()
    primero.join()
    segundo.join()

    assert sorted(r.status_code for r in respuestas) == [201, 409], [r.text for r in respuestas]
    rechazada = next(r for r in respuestas if r.status_code == 409)
    assert "ya hay una factura en curso" in rechazada.json()["detail"]
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert len([p for p in pedidos if p[0] == "cae"]) == 1, "ARCA autorizó una sola vez"
    assert len(cuenta(cliente, datos)["movimientos"]) == 1, "la deuda entró una sola vez"
    # Y pasado el primero, el siguiente es otra factura legítima.
    assert directa(cliente, datos).status_code == 201


def test_dos_clientes_a_la_vez_no_se_bloquean(cliente, datos, monkeypatch):
    """El candado es por cliente: facturar a uno no frena a otro (si el segundo choca, no es por «en curso»)."""
    arca_responde(monkeypatch)
    from app.servicios import emision_arca

    real = emision_arca.arca_wsfe.solicitar_cae
    adentro = threading.Event()

    async def cae_lento(*args, **kwargs):
        adentro.set()
        await asyncio.sleep(0.4)
        return await real(*args, **kwargs)

    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", cae_lento)
    respuestas = []
    primero = threading.Thread(target=lambda: respuestas.append(directa(cliente, datos)))
    primero.start()
    assert adentro.wait(10)
    otro = directa(cliente, datos, cliente_id=datos["otro_cliente"])
    primero.join()
    assert "ya hay una factura en curso" not in otro.text, otro.text
    assert respuestas[0].status_code == 201, respuestas[0].text


# ── 4. Lo que no se rompe ───────────────────────────────────────────────────


def test_el_gate_de_f5_no_se_pone_en_rojo_y_la_factura_directa_se_cuenta_aparte(cliente, datos):
    """Un comprobante sin órdenes no tiene con qué coincidir: comparado igual, el gate diría «no coinciden» siempre."""
    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a], tipo="factura_b").status_code == 201
    assert directa(cliente, datos, [concepto(precio="500.00")]).status_code == 201

    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is True
    assert total["cantidad_comprobantes"] == 1 and total["total_comprobantes"] == "1210.00", "sólo lo que tiene órdenes"
    assert total["cantidad_ordenes"] == 1 and total["total_ordenes"] == "1210.00"
    assert total["cantidad_sin_ordenes"] == 1 and total["total_sin_ordenes"] == "605.00"


def test_el_gate_sigue_sabiendo_decir_que_no_con_una_factura_directa_de_por_medio(cliente, datos, sesion):
    """El control: la marca `sin_ordenes` no apaga la alarma de las que sí tienen órdenes."""
    from sqlalchemy import text

    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a], tipo="factura_b").status_code == 201
    assert directa(cliente, datos).status_code == 201
    sesion.execute(text("UPDATE ordenes_carga SET tarifa = tarifa + 1, total = total + 1 WHERE id = :id"),
                   {"id": a["id"]})
    sesion.commit()
    assert cliente.get("/api/comprobantes/totales").json()["coinciden"] is False


def test_lo_facturado_de_los_reportes_incluye_la_factura_directa(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    assert facturar(cliente, datos, [a], tipo="factura_b").status_code == 201
    assert directa(cliente, datos, [concepto(precio="500.00")]).status_code == 201
    resumen = cliente.get("/api/reportes/resumen").json()
    assert resumen["comprobantes"] == 2
    assert Decimal(resumen["facturado"]) == Decimal("1815.00")


def test_la_factura_directa_se_acredita_con_una_nota_de_credito_parcial_y_total(cliente, datos):
    comp = directa(cliente, datos).json()   # 1210.00

    parcial = cliente.post(f"/api/comprobantes/{comp['id']}/nota-de-credito",
                           json={"motivo": "Descuento", "importe": "210.00"})
    assert parcial.status_code == 201, parcial.text
    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is True, "la nota parcial de una factura directa no toca el lado de las órdenes"
    assert total["total_sin_ordenes"] == "1000.00" and total["total_comprobantes"] == "0.00"
    assert Decimal(cuenta(cliente, datos)["saldo"]) == Decimal("1000.00")

    resto = cliente.post(f"/api/comprobantes/{comp['id']}/nota-de-credito",
                         json={"motivo": "Se anula", "importe": "1000.00"})
    assert resto.status_code == 201, resto.text
    detalle = cliente.get(f"/api/comprobantes/{comp['id']}").json()
    assert detalle["comprobante"]["anulado"] is True and detalle["coinciden"] is True
    assert len(detalle["notas"]) == 2
    total = cliente.get("/api/comprobantes/totales").json()
    assert total["cantidad_sin_ordenes"] == 0 and total["total_sin_ordenes"] == "0.00"
    assert Decimal(cuenta(cliente, datos)["saldo"]) == Decimal("0.00")
