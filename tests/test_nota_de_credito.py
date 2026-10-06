"""La nota de crédito de LibraCargo: las costuras sobre `libracore.notas_de_credito`.

Lo que se prueba acá es **lo propio del producto**: dónde se guarda la nota, qué pasa con las órdenes y con la
cuenta corriente, y que los totales no la cuenten dos veces. Las reglas de la nota —una factura se acredita una vez,
el candado, el CUIT del receptor, la fecha de hoy— son del motor y las prueba el motor
(`tests/test_notas_de_credito.py` de `libracore`); acá hay un test de cada una sólo para fijar que **llegan** a este
producto con el código HTTP que corresponde.

Los valores de ARCA (la nota va asociada a su factura, tipo 3 para la A) salen de lo **medido en homologación el
2026-10-03 y el 2026-10-04**: no de este código.
"""

from datetime import date
from decimal import Decimal

import pytest
from libracore import notas_de_credito as motor
from sqlalchemy import func, select

from app import tiempo
from app.models import Comprobante, MovimientoCuenta, TipoComprobante
from app.models.enums import EstadoOrden
from app.models.operacion import OrdenCarga
from tests.conftest import comprobante_de_prueba
from tests.test_comprobantes import facturar, orden
from tests.test_emision_arca import _arca_responde, _configurar_arca, razon_con_arca  # noqa: F401


@pytest.fixture
def factura(cliente, datos, razon_con_arca, monkeypatch):  # noqa: F811
    """Una Factura A emitida por ARCA (CAE, número 42) con una orden, y el registro de lo que se le pidió."""
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None)
    assert r.status_code == 201, r.text
    return {"comprobante": r.json(), "orden": a, "pedidos": pedidos, "razon": razon_con_arca}


def _nota(cliente, id_, motivo="Error de tarifa", importe=None):
    cuerpo = {"motivo": motivo} if importe is None else {"motivo": motivo, "importe": importe}
    return cliente.post(f"/api/comprobantes/{id_}/nota-de-credito", json=cuerpo)


def _cuenta(cliente, datos):
    return cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()


# ── El camino feliz ─────────────────────────────────────────────────────────

def test_la_nota_total_sale_asociada_a_su_factura_y_con_la_fecha_de_hoy(cliente, datos, factura):
    original = factura["comprobante"]
    r = _nota(cliente, original["id"])
    assert r.status_code == 201, r.text
    nota = r.json()

    assert nota["tipo"] == "nota_credito_a"
    assert nota["comprobante_asociado_id"] == original["id"]
    assert nota["motivo"] == "Error de tarifa"
    assert nota["cae"], "la nota sale con CAE"
    # Los importes del original, tal cual: una nota que anula dice lo mismo que anula.
    assert (nota["neto"], nota["iva"], nota["total"]) == (
        original["neto"], original["iva"], original["total"])
    # 🔑 La fecha es la de hoy y no se elige: ARCA exige fechas no decrecientes por tipo y punto de venta.
    assert nota["fecha"] == tiempo.hoy().isoformat()
    assert nota["punto_venta"] == 5

    pedido = [p for p in factura["pedidos"] if p[0] == "cae"][-1][1]
    assert pedido["tipo"] == 3, "la nota de credito A es el tipo 3 de ARCA"
    # Lo que la ata a su factura ante ARCA (sin esto es un comprobante suelto: 10197).
    assert (pedido["cbte_asoc_tipo"], pedido["cbte_asoc_pv"], pedido["cbte_asoc_nro"]) == (1, 5, 42)
    assert pedido["fecha"] == tiempo.hoy().isoformat()


def test_la_factura_queda_anulada_y_sus_ordenes_vuelven_a_pendientes(cliente, datos, factura, monkeypatch):
    original = factura["comprobante"]
    assert _nota(cliente, original["id"]).status_code == 201

    detalle = cliente.get(f"/api/comprobantes/{original['id']}").json()
    assert detalle["comprobante"]["anulado"] is True
    assert detalle["ordenes"] == [], "no le puede quedar ninguna orden colgada"
    assert detalle["coinciden"] is True
    orden_ = cliente.get(f"/api/ordenes/{factura['orden']['id']}").json()
    assert orden_["estado"] == "pendiente"
    assert orden_["comprobante_id"] is None

    # Y se puede volver a facturar: ARCA ya tiene la factura *y* su nota, no hay dos facturas vigentes.
    _arca_responde(monkeypatch, ultimo=42)
    otra = facturar(cliente, datos, [factura["orden"]], razon=factura["razon"], numero=None)
    assert otra.status_code == 201, otra.text


def test_la_cuenta_del_cliente_recibe_el_abono_con_la_fecha_de_la_nota(cliente, datos, factura):
    original = factura["comprobante"]
    nota = _nota(cliente, original["id"]).json()

    cuenta = _cuenta(cliente, datos)
    assert Decimal(cuenta["saldo"]) == 0, "la factura y su nota se compensan"
    movimientos = [m["movimiento"] for m in cuenta["movimientos"]]
    assert len(movimientos) == 2, "no se borra nada: la factura queda y la nota se suma"
    abono = movimientos[-1]
    assert Decimal(abono["haber"]) == Decimal(original["total"])
    assert Decimal(abono["debe"]) == 0
    assert abono["fecha"] == nota["fecha"]
    # (El ARCA de prueba contesta el mismo "ultimo" para todo tipo, por eso los dos llevan el 42.)
    assert abono["concepto"] == "Nota de credito A 0005-00000042 s/ Factura A 0005-00000042"
    assert abono["comprobante_id"] == nota["id"]


def test_los_totales_no_cuentan_la_nota_y_siguen_coincidiendo(cliente, datos, factura):
    """La factura queda `anulado` (afuera de los totales) y la nota total no suma: lo facturado baja a cero."""
    assert _nota(cliente, factura["comprobante"]["id"]).status_code == 201

    filas = cliente.get("/api/comprobantes/totales").json()
    assert all(f["coinciden"] for f in filas)
    assert all(f["cantidad_comprobantes"] == 0 and Decimal(f["total_comprobantes"]) == 0 for f in filas)
    resumen = cliente.get("/api/reportes/resumen").json()
    assert resumen["comprobantes"] == 0
    assert Decimal(resumen["facturado"]) == 0


def test_el_detalle_de_una_nota_no_la_compara_con_ordenes_que_no_tiene(cliente, datos, factura):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    detalle = cliente.get(f"/api/comprobantes/{nota['id']}").json()
    assert detalle["ordenes"] == []
    assert detalle["coinciden"] is True, "una nota no agrupa ordenes: no es un comprobante que no cierra"


def test_la_nota_deja_su_rastro_en_la_auditoria(cliente, datos, factura, sesion):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    eventos = cliente.get("/api/auditoria", params={"entidad": "comprobante"}).json()
    por_id = {(e["entidad_id"], e["accion"]) for e in eventos["registros"]}
    assert (nota["id"], "alta") in por_id
    assert (factura["comprobante"]["id"], "modificacion") in por_id


# ── Lo que el motor decide, y que llega con su código ──────────────────────

def test_una_factura_ya_acreditada_no_admite_otra_nota(cliente, datos, factura):
    assert _nota(cliente, factura["comprobante"]["id"]).status_code == 201
    r = _nota(cliente, factura["comprobante"]["id"])
    assert r.status_code == 409
    assert "anulado" in r.json()["detail"]


def test_la_guarda_de_la_nota_repetida_del_motor_llega_con_409(cliente, datos, factura, sesion):
    """Una nota previa colgada del original (aunque el original no figure anulado): el motor la ve y frena."""
    original = factura["comprobante"]
    comprobante_de_prueba(
        sesion, razon_social_id=original["razon_social_id"], tipo=TipoComprobante.NOTA_CREDITO_A,
        punto_venta=5, numero=99, fecha=date(2026, 8, 20), cliente_id=original["cliente_id"],
        neto=original["neto"], iva=original["iva"], total=original["total"],
        comprobante_asociado_id=original["id"], cae="75000000000001",
    )

    r = _nota(cliente, original["id"])
    assert r.status_code == 409, r.text
    assert "una sola vez" in r.json()["detail"]
    assert sesion.scalar(select(func.count(Comprobante.id)).where(
        Comprobante.comprobante_asociado_id == original["id"])) == 1, "no se pidio otra nota encima"


def test_dos_pedidos_a_la_vez_emiten_una_sola_nota(cliente, datos, factura):
    """El candado es del motor, con la clave de **este** producto: mientras otro pedido tiene la factura, 409."""
    original_id = factura["comprobante"]["id"]
    with motor.una_nota_a_la_vez(("comprobantes", original_id)):
        r = _nota(cliente, original_id)
    assert r.status_code == 409, r.text
    assert "en curso" in r.json()["detail"]
    assert not motor.en_curso(("comprobantes", original_id)), "el candado se libera"
    assert cliente.get(f"/api/comprobantes/{original_id}").json()["comprobante"]["anulado"] is False


def test_un_cuit_que_no_cierra_no_impide_acreditar(cliente, datos, factura):
    """🔴 Medido el 2026-10-04: ARCA autoriza la nota A a un CUIT que no cierra, igual que la factura (aviso
    `10238`). Si el producto frenara acá, un error de CUIT en una factura **no tendría arreglo**."""
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True, "cuit": "30-70933285-3"})
    assert r.status_code == 200, r.text
    assert _nota(cliente, factura["comprobante"]["id"]).status_code == 201


def test_una_nota_no_se_acredita(cliente, datos, factura):
    nota = _nota(cliente, factura["comprobante"]["id"]).json()
    r = _nota(cliente, nota["id"])
    assert r.status_code == 400, r.text
    assert "no admite nota" in r.json()["detail"]


# ── Lo que el producto decide antes de llamar al motor ─────────────────────

def test_un_comprobante_sin_cae_se_anula_como_siempre_y_no_pide_nota(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    comp = facturar(cliente, datos, [a], numero=7).json()
    r = _nota(cliente, comp["id"])
    assert r.status_code == 409
    assert "no tiene CAE" in r.json()["detail"]
    assert cliente.delete(f"/api/comprobantes/{comp['id']}").status_code == 200


def test_el_mensaje_de_anular_con_cae_apunta_a_la_nota(cliente, datos, factura):
    r = cliente.delete(f"/api/comprobantes/{factura['comprobante']['id']}")
    assert r.status_code == 409
    assert "nota-de-credito" in r.json()["detail"]


def test_un_comprobante_que_no_existe_da_404(cliente):
    assert _nota(cliente, 9999).status_code == 404


def test_el_motivo_es_obligatorio_y_la_fecha_y_el_tipo_no_se_eligen(cliente, datos, factura):
    id_ = factura["comprobante"]["id"]
    ruta = f"/api/comprobantes/{id_}/nota-de-credito"
    assert cliente.post(ruta, json={}).status_code == 422
    assert cliente.post(ruta, json={"motivo": "  "}).status_code == 422
    # La fecha y el tipo no se eligen: la nota es de hoy y de la letra del original. El importe sí (parcial).
    for campo in ({"fecha": "2026-01-01"}, {"tipo": "nota_credito_b"}):
        assert cliente.post(ruta, json={"motivo": "Error", **campo}).status_code == 422, campo
    # Un importe que no es un importe no llega ni al motor: cero, negativo, tres decimales, un booleano.
    for importe in (0, -10, "1.234", True, "diez"):
        assert cliente.post(ruta, json={"motivo": "Error", "importe": importe}).status_code == 422, importe
    assert cliente.get(f"/api/comprobantes/{id_}").json()["comprobante"]["anulado"] is False
    assert [p for p in factura["pedidos"] if p[0] == "cae"][1:] == [], "no se le pidio nada a ARCA"


# ── La nota parcial (ADR-028) ──────────────────────────────────────────────

def _detalle(cliente, id_):
    return cliente.get(f"/api/comprobantes/{id_}").json()


def test_la_nota_parcial_acredita_un_importe_y_no_toca_las_ordenes(cliente, datos, factura):
    """121 sobre una Factura A de 1210: neto 100 e IVA 21 (la alícuota de la factura, la cuenta es del motor)."""
    original = factura["comprobante"]
    r = _nota(cliente, original["id"], motivo="Diferencia de kilos", importe="121.00")
    assert r.status_code == 201, r.text
    nota = r.json()
    assert (nota["tipo"], nota["comprobante_asociado_id"]) == ("nota_credito_a", original["id"])
    assert (nota["neto"], nota["iva"], nota["total"]) == ("100.00", "21.00", "121.00")

    pedido = [p for p in factura["pedidos"] if p[0] == "cae"][-1][1]
    # Lo que va a ARCA sale de la fila: el mismo neto, IVA y total que quedaron guardados.
    assert (pedido["tipo"], pedido["subtotal"], pedido["iva_amount"], pedido["total"]) == (3, 100.0, 21.0, 121.0)
    assert (pedido["cbte_asoc_tipo"], pedido["cbte_asoc_nro"]) == (1, 42)

    detalle = _detalle(cliente, original["id"])
    assert detalle["comprobante"]["anulado"] is False, "con saldo, el original sigue vigente"
    assert [o["id"] for o in detalle["ordenes"]] == [factura["orden"]["id"]], "las ordenes no se tocan"
    assert detalle["coinciden"] is True, "la factura sigue diciendo lo mismo que sus ordenes"
    assert (detalle["acreditado"], detalle["saldo_acreditable"]) == ("121.00", "1089.00")
    assert [n["id"] for n in detalle["notas"]] == [nota["id"]]

    cuenta = _cuenta(cliente, datos)
    assert Decimal(cuenta["saldo"]) == Decimal("1089.00")
    abono = cuenta["movimientos"][-1]["movimiento"]
    assert (Decimal(abono["haber"]), abono["comprobante_id"]) == (Decimal("121.00"), nota["id"])
    assert abono["descripcion"] == "Diferencia de kilos"


def test_las_parciales_que_suman_el_total_liberan_las_ordenes(cliente, datos, factura, monkeypatch):
    """Decisión del humano (2026-10-05): acreditada por completo, la factura queda anulada y sus órdenes
    vuelven a pendientes, igual que con la nota total. Así una parcial seguida de «estaba toda mal» tiene arreglo."""
    original = factura["comprobante"]
    assert _nota(cliente, original["id"], importe="121.00").status_code == 201
    _arca_responde(monkeypatch, ultimo=42)
    r = _nota(cliente, original["id"], motivo="Estaba toda mal", importe="1089.00")
    assert r.status_code == 201, r.text

    detalle = _detalle(cliente, original["id"])
    assert detalle["comprobante"]["anulado"] is True
    assert detalle["ordenes"] == [] and detalle["coinciden"] is True
    assert (detalle["acreditado"], detalle["saldo_acreditable"]) == (None, None), "anulado: no hay nota posible"
    assert len(detalle["notas"]) == 2
    assert cliente.get(f"/api/ordenes/{factura['orden']['id']}").json()["estado"] == "pendiente"
    assert Decimal(_cuenta(cliente, datos)["saldo"]) == 0
    # Los totales: el original anulado sale, y sus notas con él (si no, se restaría dos veces).
    filas = cliente.get("/api/comprobantes/totales").json()
    assert all(f["coinciden"] and Decimal(f["total_comprobantes"]) == 0 for f in filas)
    assert Decimal(cliente.get("/api/reportes/resumen").json()["facturado"]) == 0


def test_los_totales_restan_la_nota_parcial_de_los_dos_lados(cliente, datos, factura):
    assert _nota(cliente, factura["comprobante"]["id"], importe="121.00").status_code == 201

    fila = next(f for f in cliente.get("/api/comprobantes/totales").json()
                if f["razon_social_id"] == factura["razon"])
    assert fila["coinciden"] is True, "una nota parcial no es una diferencia entre comprobantes y ordenes"
    assert (fila["neto_comprobantes"], fila["iva_comprobantes"], fila["total_comprobantes"]) == (
        "900.00", "189.00", "1089.00")
    assert (fila["total_ordenes"], fila["cantidad_comprobantes"]) == ("1089.00", 1)
    resumen = cliente.get("/api/reportes/resumen").json()
    assert (resumen["comprobantes"], Decimal(resumen["facturado"])) == (1, Decimal("1089.00"))


def test_la_nota_parcial_resta_en_el_rango_de_su_fecha(cliente, datos, factura):
    """La factura es del 15/08 y la nota de hoy: cada una cuenta en el rango de su propia fecha, y los dos lados
    del gate siguen coincidiendo en cualquier recorte."""
    assert _nota(cliente, factura["comprobante"]["id"], importe="121.00").status_code == 201
    hoy = tiempo.hoy().isoformat()

    def total(**rango):
        filas = cliente.get("/api/comprobantes/totales", params=rango).json()
        assert all(f["coinciden"] for f in filas), rango
        return sum((Decimal(f["total_comprobantes"]) for f in filas), Decimal(0))

    assert total(hasta="2026-09-30") == Decimal("1210.00"), "antes de la nota, la factura entera"
    assert total(desde=hoy) == Decimal("-121.00"), "en el rango de la nota, sólo lo que acredita"
    assert total() == Decimal("1089.00")


def test_el_tope_acumulado_del_motor_llega_con_409(cliente, datos, factura, monkeypatch):
    original_id = factura["comprobante"]["id"]
    assert _nota(cliente, original_id, importe="121.00").status_code == 201
    _arca_responde(monkeypatch, ultimo=42)
    r = _nota(cliente, original_id, importe="1100.00")
    assert r.status_code == 409, r.text
    assert "supera lo que queda por acreditar" in r.json()["detail"]
    # Y con notas previas la total ya no corresponde: pide una por el saldo.
    r = _nota(cliente, original_id)
    assert r.status_code == 409, r.text
    assert "saldo acreditable (1089.00)" in r.json()["detail"]
    assert len(_detalle(cliente, original_id)["notas"]) == 1


def test_un_importe_igual_al_total_es_la_nota_total(cliente, datos, factura):
    original = factura["comprobante"]
    nota = _nota(cliente, original["id"], importe=original["total"]).json()
    assert (nota["neto"], nota["iva"], nota["total"]) == (original["neto"], original["iva"], original["total"])
    assert _detalle(cliente, original["id"])["comprobante"]["anulado"] is True


# ── La nota de una FCE: sólo parcial (ADR-028; la regla es del motor) ──────

@pytest.fixture
def fce(factura, sesion):
    """Una FCE A emitida (con CAE) de 1210, del mismo cliente y razón social que la factura."""
    original = factura["comprobante"]
    fce = comprobante_de_prueba(
        sesion, razon_social_id=original["razon_social_id"], tipo=TipoComprobante.FCE_A, punto_venta=5,
        numero=7, fecha=date(2026, 8, 20), cliente_id=original["cliente_id"], neto="1000.00",
        iva="210.00", total="1210.00", cae="75000000000002", fch_vto_pago=date(2026, 9, 20),
    )
    return fce.id


def test_la_nota_de_una_fce_es_parcial_y_va_con_la_marca_de_que_no_anula(cliente, datos, factura, fce):
    r = _nota(cliente, fce, importe="121.00")
    assert r.status_code == 201, r.text
    nota = r.json()
    assert (nota["tipo"], nota["total"]) == ("nota_credito_fce_a", "121.00")

    pedido = [p for p in factura["pedidos"] if p[0] == "cae"][-1][1]
    assert pedido["tipo"] == 203, "la nota de credito FCE A es el tipo 203 de ARCA"
    # Lo arma el motor: la FCE asociada con su fecha (10158) y `N` (S pide el rechazo del comprador, 10154).
    assert (pedido["cbte_asoc_tipo"], pedido["cbte_asoc_nro"], pedido["cbte_asoc_fecha"]) == (201, 7, "2026-08-20")
    assert pedido["fce_anulacion"] == "N"
    # Una nota no es una factura FCE: no lleva vencimiento de pago ni CBU propios.
    assert "fce_cbu" not in pedido and "fch_vto_pago" not in pedido
    assert _detalle(cliente, fce)["saldo_acreditable"] == "1089.00"


@pytest.mark.parametrize("importe", [None, "1210.00"])
def test_una_fce_no_admite_la_nota_por_el_total(cliente, datos, factura, fce, importe):
    """Medido: sin que el comprador la rechace, ARCA no deja anular una FCE (10154) y una nota por el total supera
    su saldo (10184). Lo frena el motor —también la total sin importe, libracore#343— sin pedirle nada a ARCA."""
    antes = len(factura["pedidos"])
    r = _nota(cliente, fce, importe=importe)
    assert r.status_code == 422, r.text
    assert "rechaz" in r.json()["detail"]
    assert len(factura["pedidos"]) == antes, "no se le pidio nada a ARCA"


# ── Si ARCA dice que no, no queda nada ─────────────────────────────────────

def _estado(cliente, sesion, datos, original_id):
    """Todo lo que la nota puede tocar, para comparar antes y después."""
    return {
        "notas": sesion.scalar(select(func.count(Comprobante.id)).where(
            Comprobante.comprobante_asociado_id.is_not(None))),
        "anulado": cliente.get(f"/api/comprobantes/{original_id}").json()["comprobante"]["anulado"],
        "movimientos": sesion.scalar(select(func.count(MovimientoCuenta.id))),
        "facturadas": sesion.scalar(select(func.count(OrdenCarga.id)).where(
            OrdenCarga.estado == EstadoOrden.FACTURADA)),
        "saldo": _cuenta(cliente, datos)["saldo"],
    }


def test_si_arca_rechaza_el_cae_de_la_nota_no_queda_nada(cliente, datos, factura, sesion, monkeypatch):
    original_id = factura["comprobante"]["id"]
    antes = _estado(cliente, sesion, datos, original_id)
    _arca_responde(monkeypatch, ultimo=42, falla_cae="El comprobante asociado no existe")

    r = _nota(cliente, original_id)
    assert r.status_code == 502, r.text
    assert "asociado no existe" in r.json()["detail"]
    assert _estado(cliente, sesion, datos, original_id) == antes
    assert not motor.en_curso(("comprobantes", original_id))

    # Y se puede volver a intentar: no quedó un número tomado ni un candado puesto.
    _arca_responde(monkeypatch, ultimo=42)
    assert _nota(cliente, original_id).status_code == 201


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, factura, sesion, monkeypatch):
    original_id = factura["comprobante"]["id"]
    antes = _estado(cliente, sesion, datos, original_id)
    _arca_responde(monkeypatch, falla_numero="Computador no autorizado")

    r = _nota(cliente, original_id)
    assert r.status_code == 502, r.text
    assert _estado(cliente, sesion, datos, original_id) == antes


def test_si_la_razon_social_ya_no_emite_por_arca_lo_dice(cliente, datos, factura, monkeypatch):
    """Cambió el CUIT de la razón social después de facturar: no hay con qué firmar la nota."""
    r = cliente.put(f"/api/razones-sociales/{factura['razon']}", json={
        "nombre": "Suitrans SA", "cuit": "30-99999999-7", "punto_venta": 5})
    assert r.status_code == 200, r.text
    r = _nota(cliente, factura["comprobante"]["id"])
    assert r.status_code == 409, r.text
    assert "ARCA" in r.json()["detail"]


# ── Homologación: se corre todo y no se guarda nada ────────────────────────

def test_contra_homologacion_se_ensaya_y_no_se_guarda(cliente, datos, sesion, monkeypatch):
    """Una nota de prueba no mueve la cuenta del cliente ni libera las órdenes (mismo criterio que `facturar`)."""
    from tests.test_emision_arca import CUIT

    razon = datos["razon"]
    cliente.put(f"/api/razones-sociales/{razon}", json={"nombre": "Suitrans SA", "cuit": CUIT, "punto_venta": 5})
    _configurar_arca(cliente, ambiente="homologacion")
    pedidos = _arca_responde(monkeypatch, ultimo=41)

    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    original = comprobante_de_prueba(
        sesion, razon_social_id=razon, tipo=TipoComprobante.FACTURA_A, punto_venta=5, numero=42,
        fecha=date(2026, 8, 20), cliente_id=datos["cliente"], neto="1000.00", iva="210.00",
        total="1210.00", cae="75000000000003",
    )
    sesion.execute(OrdenCarga.__table__.update().where(OrdenCarga.id == a["id"]).values(
        comprobante_id=original.id, estado=EstadoOrden.FACTURADA))
    sesion.commit()
    antes = _estado(cliente, sesion, datos, original.id)

    r = _nota(cliente, original.id)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["ensayo"] is True and cuerpo["ambiente"] == "homologacion"
    assert cuerpo["tipo"] == "nota_credito_a" and cuerpo["cae"]
    assert any(p[0] == "cae" for p in pedidos), "se recorrio el camino entero contra ARCA"
    sesion.expire_all()
    assert _estado(cliente, sesion, datos, original.id) == antes


# ── La base ─────────────────────────────────────────────────────────────────

def test_no_se_crea_una_nota_sin_asociado_ni_una_factura_con_asociado(cliente, datos, factura, sesion):
    """Era un CHECK de la tabla propia; `facturas` no lo tiene, así que lo dice `crear` (ADR-030)."""
    original = factura["comprobante"]
    comun = dict(razon_social_id=original["razon_social_id"], punto_venta=5, fecha=date(2026, 8, 20),
                 cliente_id=original["cliente_id"], neto="1.00", iva="0.21", total="1.21")
    with pytest.raises(ValueError, match="acredita a un comprobante"):
        comprobante_de_prueba(sesion, tipo=TipoComprobante.NOTA_CREDITO_A, numero=500, **comun)
    with pytest.raises(ValueError, match="acredita a un comprobante"):
        comprobante_de_prueba(sesion, tipo=TipoComprobante.FACTURA_A, numero=501,
                              comprobante_asociado_id=original["id"], **comun)

