"""La nota de débito de LibraCargo: las costuras sobre `libracore.notas_de_debito` (ADR-048).

Como con la nota de crédito, lo que se prueba acá es **lo propio del producto**: dónde se guarda la nota, que la cuenta
corriente recibe el **cargo**, que los totales la cuentan sin ponerse en rojo, y que **no toca** lo que la nota de
crédito sí toca (las órdenes, el original, el saldo acreditable). Las reglas de la nota —la letra se hereda, el original
tiene que tener CAE, el receptor, un solo pedido a la vez— son del motor y las prueba el motor
(`tests/test_notas_de_debito.py` de `libracore`); acá hay un caso de cada una sólo para fijar que **llegan** con el
código HTTP que corresponde.

Lo que distingue a la nota de débito de la de crédito, medido con su control: va **siempre por un importe**, **no tiene
tope** y **suma**.

> ⚠️ Sin medir contra ARCA de homologación (no hay certificado en la máquina de desarrollo): el pedido que se verifica
> acá es el que arma el motor, con los tipos 2/7/12 y 202/207/212.
"""

import asyncio
import threading
import time
from decimal import Decimal

import pytest

from app import tiempo
from tests.conftest import CUIT_EMISOR, arca_responde, cargar_empresa, comprobante_de_prueba, configurar_arca
from tests.test_comprobantes import facturado_a_mano, facturar, orden
from tests.test_factura_directa import concepto, directa, receptor

pytestmark = pytest.mark.con_emisor


def _nota(cliente, id_, importe="605.00", motivo="Intereses por mora"):
    cuerpo = {"motivo": motivo}
    if importe is not None:
        cuerpo["importe"] = importe
    return cliente.post(f"/api/comprobantes/{id_}/nota-de-debito", json=cuerpo)


def _cuenta(cliente, datos):
    return cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()


@pytest.fixture
def factura(cliente, datos, emisor):
    """Una Factura A de 1210.00 emitida por ARCA (CAE, número 1) a un inscripto, con una orden."""
    receptor(cliente, datos, "responsable_inscripto")
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a])
    assert r.status_code == 201, r.text
    return {"comprobante": r.json(), "orden": a, "pedidos": emisor}


# ── El camino feliz ─────────────────────────────────────────────────────────


def test_la_nota_sale_asociada_a_su_factura_con_el_motivo_y_la_fecha_de_hoy(cliente, datos, factura):
    original = factura["comprobante"]
    r = _nota(cliente, original["id"])
    assert r.status_code == 201, r.text
    nota = r.json()

    assert nota["tipo"] == "nota_debito_a", "la letra se hereda de la factura"
    assert nota["comprobante_asociado_id"] == original["id"]
    assert nota["motivo"] == "Intereses por mora"
    assert nota["cae"], "la nota sale con CAE"
    assert nota["sin_ordenes"] is True
    # El importe es con IVA y se reparte con la alícuota de la factura: 605 = 500 + 105.
    assert (nota["neto"], nota["iva"], nota["total"]) == ("500.00", "105.00", "605.00")
    # 🔑 La fecha es la de hoy y no se elige: ARCA exige fechas no decrecientes por tipo y punto de venta.
    assert nota["fecha"] == tiempo.hoy().isoformat()

    pedido = [p for p in factura["pedidos"] if p[0] == "cae"][-1][1]
    assert pedido["tipo"] == 2, "la nota de débito A es el tipo 2 de ARCA"
    assert (pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (500.0, 105.0, 605.0)
    # Lo que la ata a su factura ante ARCA (sin esto es un comprobante suelto: 10197).
    assert (pedido["cbte_asoc_tipo"], pedido["cbte_asoc_pv"], pedido["cbte_asoc_nro"]) == (1, 1, 1)


def test_la_cuenta_del_cliente_recibe_el_cargo_con_la_fecha_de_la_nota(cliente, datos, factura):
    original = factura["comprobante"]
    nota = _nota(cliente, original["id"]).json()

    cuenta = _cuenta(cliente, datos)
    assert Decimal(cuenta["saldo"]) == Decimal("1210.00") + Decimal("605.00"), "la deuda SUBE (la de crédito la baja)"
    movimientos = [m["movimiento"] for m in cuenta["movimientos"]]
    assert len(movimientos) == 2
    cargo = movimientos[-1]
    assert Decimal(cargo["debe"]) == Decimal("605.00") and Decimal(cargo["haber"]) == 0
    assert cargo["fecha"] == nota["fecha"]
    assert cargo["concepto"] == "Nota de debito A 0001-00000001 s/ Factura A 0001-00000001"
    assert cargo["descripcion"] == "Intereses por mora"
    assert cargo["comprobante_id"] == nota["id"]
    assert cuenta["coinciden"] is True


def test_no_toca_ni_la_factura_ni_las_ordenes(cliente, datos, factura):
    """La nota de crédito total anula el original y libera las órdenes; la de débito agrega plata y nada más."""
    original = factura["comprobante"]
    assert _nota(cliente, original["id"]).status_code == 201

    detalle = cliente.get(f"/api/comprobantes/{original['id']}").json()
    assert detalle["comprobante"]["anulado"] is False
    assert [o["id"] for o in detalle["ordenes"]] == [factura["orden"]["id"]]
    assert detalle["coinciden"] is True
    assert cliente.get(f"/api/ordenes/{factura['orden']['id']}").json()["estado"] == "facturada"


def test_no_tiene_tope_puede_superar_el_total_de_la_factura(cliente, datos, factura):
    """El control de la diferencia con la nota de crédito: acá un importe mayor que la factura es válido."""
    original = factura["comprobante"]
    credito = cliente.post(f"/api/comprobantes/{original['id']}/nota-de-credito",
                           json={"motivo": "Se pasó", "importe": "5000.00"})
    assert credito.status_code == 409, "la de crédito sí tiene tope"

    r = _nota(cliente, original["id"], importe="5000.00")
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["total"]) == Decimal("5000.00")


def test_una_factura_admite_varias_notas_de_debito(cliente, datos, factura):
    original = factura["comprobante"]
    for importe in ("100.00", "200.00", "300.00"):
        assert _nota(cliente, original["id"], importe=importe).status_code == 201
    detalle = cliente.get(f"/api/comprobantes/{original['id']}").json()
    assert [Decimal(n["total"]) for n in detalle["notas_debito"]] == [Decimal("100.00"), Decimal("200.00"),
                                                                       Decimal("300.00")]
    assert Decimal(_cuenta(cliente, datos)["saldo"]) == Decimal("1210.00") + Decimal("600.00")


def test_el_detalle_separa_las_notas_de_debito_de_las_de_credito_y_el_saldo_acreditable_no_cambia(
        cliente, datos, factura):
    original = factura["comprobante"]
    assert _nota(cliente, original["id"], importe="605.00").status_code == 201

    detalle = cliente.get(f"/api/comprobantes/{original['id']}").json()
    assert detalle["notas"] == [], "no es una nota de crédito"
    assert len(detalle["notas_debito"]) == 1
    # 🔴 Contarla como acreditada bajaría lo que se puede acreditar: la factura sigue valiendo 1210.00.
    assert detalle["acreditado"] == "0.00" and detalle["saldo_acreditable"] == "1210.00"

    # Y se puede acreditar entera: la nota de débito no es una previa que frene a la de crédito.
    total = cliente.post(f"/api/comprobantes/{original['id']}/nota-de-credito", json={"motivo": "Se anula"})
    assert total.status_code == 201, total.text
    assert Decimal(_cuenta(cliente, datos)["saldo"]) == Decimal("605.00"), "queda la deuda de la nota de débito"


def test_una_nota_de_debito_no_tiene_saldo_acreditable_ni_se_le_pide_nota_de_credito(cliente, datos, factura):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    detalle = cliente.get(f"/api/comprobantes/{nota['id']}").json()
    assert detalle["saldo_acreditable"] is None and detalle["acreditado"] is None
    assert detalle["coinciden"] is True, "no agrupa órdenes: no hay con qué compararla"

    credito = cliente.post(f"/api/comprobantes/{nota['id']}/nota-de-credito", json={"motivo": "A la nota"})
    assert credito.status_code == 400, credito.text
    debito = _nota(cliente, nota["id"])
    assert debito.status_code == 400 and "no admite nota de débito" in debito.text


# ── Lo facturado ────────────────────────────────────────────────────────────


def test_las_notas_de_debito_suman_a_lo_facturado_sin_poner_el_gate_en_rojo(cliente, datos, factura):
    assert _nota(cliente, factura["comprobante"]["id"], importe="605.00").status_code == 201

    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is True
    assert total["total_comprobantes"] == "1210.00" and total["total_ordenes"] == "1210.00"
    assert total["cantidad_sin_ordenes"] == 1 and total["total_sin_ordenes"] == "605.00"
    resumen = cliente.get("/api/reportes/resumen").json()
    assert Decimal(resumen["facturado"]) == Decimal("1815.00"), "la nota de crédito resta y la de débito suma"


def test_la_nota_de_credito_de_una_factura_con_ordenes_no_resta_la_nota_de_debito(cliente, datos, factura):
    """El control del filtro por tipo en `acreditado_por_notas`: si contara la de débito, restaría de más."""
    original = factura["comprobante"]
    assert _nota(cliente, original["id"], importe="605.00").status_code == 201
    parcial = cliente.post(f"/api/comprobantes/{original['id']}/nota-de-credito",
                           json={"motivo": "Descuento", "importe": "210.00"})
    assert parcial.status_code == 201

    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is True
    assert total["total_comprobantes"] == "1000.00" and total["total_ordenes"] == "1000.00"
    assert total["total_sin_ordenes"] == "605.00"
    assert Decimal(cliente.get("/api/reportes/resumen").json()["facturado"]) == Decimal("1605.00")


def test_el_listado_trae_la_nota_y_se_filtra_por_su_tipo(cliente, datos, factura):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    todos = cliente.get("/api/comprobantes").json()
    assert {c["id"] for c in todos} == {factura["comprobante"]["id"], nota["id"]}
    solo = cliente.get("/api/comprobantes", params={"tipo": "nota_debito_a"}).json()
    assert [c["id"] for c in solo] == [nota["id"]]


def test_la_nota_con_cae_no_se_anula_desde_aca(cliente, datos, factura):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    assert cliente.delete(f"/api/comprobantes/{nota['id']}").status_code == 409


# ── Otras clases ────────────────────────────────────────────────────────────


def test_la_nota_de_una_fce_es_de_debito_fce_y_dice_que_no_anula(cliente, datos, emisor):
    receptor(cliente, datos, "responsable_inscripto")
    cliente.put("/api/arca", json={
        "empresa": "agencia", "cuit": CUIT_EMISOR, "punto_venta": 1, "ambiente": "produccion", "alias": "",
        "fce_cbu": "0000003100012345678901", "fce_transmision": "SCA"})
    fce = directa(cliente, datos, tipo="fce_a", fecha="2099-01-01", fecha_vencimiento_pago="2099-02-01").json()

    r = _nota(cliente, fce["id"])
    assert r.status_code == 201, r.text
    assert r.json()["tipo"] == "nota_debito_fce_a"
    pedido = [p for p in emisor if p[0] == "cae"][-1][1]
    assert pedido["tipo"] == 202
    assert pedido["fce_anulacion"] == "N", "anular una FCE lo decide el comprador, no quien emite"
    assert (pedido["cbte_asoc_tipo"], pedido["cbte_asoc_nro"]) == (201, 1)


def test_la_nota_de_una_clase_c_no_discrimina_iva(cliente, datos, emisor):
    cargar_empresa(cliente, condicion_iva="monotributo")
    comp = directa(cliente, datos, [concepto(precio="1000.00")], tipo="factura_c").json()

    r = _nota(cliente, comp["id"], importe="300.00")
    assert r.status_code == 201, r.text
    assert r.json()["tipo"] == "nota_debito_c"
    assert (r.json()["neto"], r.json()["iva"], r.json()["total"]) == ("300.00", "0.00", "300.00")
    pedido = [p for p in emisor if p[0] == "cae"][-1][1]
    assert (pedido["tipo"], pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (12, 300.0, 0.0, 300.0)


def test_la_nota_de_una_factura_directa_tambien_se_puede(cliente, datos):
    receptor(cliente, datos, "responsable_inscripto")
    comp = directa(cliente, datos, tipo="factura_a").json()
    r = _nota(cliente, comp["id"])
    assert r.status_code == 201, r.text
    total = cliente.get("/api/comprobantes/totales").json()
    assert total["coinciden"] is True and total["total_sin_ordenes"] == "1815.00"


# ── Las guardas llegan con su código HTTP ───────────────────────────────────


def test_un_comprobante_sin_cae_no_admite_nota_de_debito(cliente, datos, sesion):
    a = orden(cliente, datos, "100.00")
    sin_cae = facturado_a_mano(sesion, datos, [a], numero=77)
    r = _nota(cliente, sin_cae.id)
    assert r.status_code == 409
    assert "no tiene CAE" in r.text
    assert Decimal(_cuenta(cliente, datos)["saldo"]) == Decimal("121.00"), "no se movió la cuenta"


def test_un_comprobante_anulado_no_admite_nota_de_debito(cliente, datos, factura):
    original = factura["comprobante"]
    assert cliente.post(f"/api/comprobantes/{original['id']}/nota-de-credito",
                        json={"motivo": "Se anula"}).status_code == 201
    r = _nota(cliente, original["id"])
    assert r.status_code == 409 and "ya esta anulado" in r.text


def test_un_comprobante_que_no_existe_da_404(cliente, datos):
    assert _nota(cliente, 9999).status_code == 404


def test_una_clase_a_sin_cuit_se_rechaza_antes_de_ir_a_arca(cliente, datos, sesion, emisor):
    """Una A exige CUIT de 11 dígitos aunque sea una nota (`problema_del_receptor` del motor): 422 y sin ARCA."""
    comp = comprobante_de_prueba(
        sesion, tipo=_tipo("factura_a"), punto_venta=1, numero=50, cae="75123456789012",
        fecha=tiempo.hoy(), cliente_id=datos["otro_cliente"], neto=100, iva=21, total=121)
    antes = len(emisor)
    r = _nota(cliente, comp.id)
    assert r.status_code == 422, r.text
    assert "CUIT" in r.text
    assert len(emisor) == antes, "no se le pidió nada a ARCA"


def _tipo(valor):
    from app.models.enums import TipoComprobante

    return TipoComprobante(valor)


@pytest.mark.parametrize("cuerpo", [
    {"motivo": "Intereses"},                                              # sin importe: no hay nota de débito total
    {"motivo": "Intereses", "importe": None},
    {"motivo": "Intereses", "importe": "0"},
    {"motivo": "Intereses", "importe": "-10.00"},
    {"motivo": "Intereses", "importe": "10.005"},
    {"motivo": "Intereses", "importe": True},
    {"motivo": "Intereses", "importe": "abc"},
    {"motivo": "ab", "importe": "10.00"},
    {"motivo": "   ", "importe": "10.00"},
    {"importe": "10.00"},
    {"motivo": "Intereses", "importe": "10.00", "fecha": "2026-08-01"},   # la fecha es la de hoy y no se elige
    {"motivo": "Intereses", "importe": "10.00", "tipo": "nota_debito_b"},  # el tipo sale de la factura
])
def test_el_cuerpo_se_valida_antes_de_tocar_nada(cliente, datos, factura, cuerpo):
    r = cliente.post(f"/api/comprobantes/{factura['comprobante']['id']}/nota-de-debito", json=cuerpo)
    assert r.status_code == 422, (cuerpo, r.text)
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert len(_cuenta(cliente, datos)["movimientos"]) == 1


# ── Si ARCA no la autoriza, no queda nada ───────────────────────────────────


def test_si_arca_rechaza_no_queda_ni_la_nota_ni_el_cargo(cliente, datos, factura, monkeypatch):
    arca_responde(monkeypatch, falla_cae="Importe de IVA inconsistente")
    r = _nota(cliente, factura["comprobante"]["id"])
    assert r.status_code == 502, r.text
    assert "rechazo la nota de debito" in r.json()["detail"]

    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert Decimal(_cuenta(cliente, datos)["saldo"]) == Decimal("1210.00")
    assert cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"][0]["accion"] == "alta"
    assert len(cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"]) == 1

    # Y se reintenta cuando ARCA vuelve: la nota fallida no quedó "sin CAE" frenando a la siguiente.
    arca_responde(monkeypatch)
    assert _nota(cliente, factura["comprobante"]["id"]).status_code == 201


def test_sin_certificado_no_se_emite_la_nota(cliente, datos, factura):
    from libracore.db import arca_config as db_arca_config

    for fila in db_arca_config.obtener_todas_arca_configs():
        db_arca_config.eliminar_arca_config(fila["empresa"])
    r = _nota(cliente, factura["comprobante"]["id"])
    assert r.status_code == 409 and "ARCA no está configurado" in r.json()["detail"]
    assert len(cliente.get("/api/comprobantes").json()) == 1


def test_un_ensayo_contra_homologacion_no_mueve_la_cuenta(cliente, datos, factura, monkeypatch):
    configurar_arca(cliente, cuit=CUIT_EMISOR, punto_venta=1, ambiente="homologacion")
    arca_responde(monkeypatch, ultimo=7)
    r = _nota(cliente, factura["comprobante"]["id"])
    assert r.status_code == 200, r.text
    assert r.json()["ensayo"] is True and r.json()["numero"] == 8 and "id" not in r.json()
    assert len(cliente.get("/api/comprobantes").json()) == 1
    assert Decimal(_cuenta(cliente, datos)["saldo"]) == Decimal("1210.00"), "una prueba no mueve la cuenta"


def test_el_alta_de_la_nota_deja_un_asiento_de_auditoria(cliente, datos, factura):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    registros = cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()["registros"]
    assert (nota["id"], "alta") in [(r["entidad_id"], r["accion"]) for r in registros]


def test_un_doble_clic_emite_una_sola_nota(cliente, datos, factura, monkeypatch):
    """El candado del motor con `conn=sesion`: el segundo pedido es un 409 «en curso» y ARCA ve una sola nota."""
    from app.servicios import emision_arca

    real = emision_arca.arca_wsfe.solicitar_cae
    adentro = threading.Event()

    async def cae_lento(*args, **kwargs):
        adentro.set()
        await asyncio.sleep(0.5)
        return await real(*args, **kwargs)

    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", cae_lento)
    respuestas = []
    id_ = factura["comprobante"]["id"]
    primero = threading.Thread(target=lambda: respuestas.append(_nota(cliente, id_)))
    primero.start()
    assert adentro.wait(10)
    time.sleep(0.1)
    segundo = threading.Thread(target=lambda: respuestas.append(_nota(cliente, id_)))
    segundo.start()
    primero.join()
    segundo.join()

    assert sorted(r.status_code for r in respuestas) == [201, 409], [r.text for r in respuestas]
    assert "nota de débito en curso" in next(r for r in respuestas if r.status_code == 409).json()["detail"]
    assert len(cliente.get(f"/api/comprobantes/{id_}").json()["notas_debito"]) == 1
    assert len(_cuenta(cliente, datos)["movimientos"]) == 2
