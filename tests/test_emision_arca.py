"""Emitir por ARCA: F8.

Hasta acá este producto **registraba** comprobantes con un número tipeado a
mano. Ahora, cuando la razón social tiene ARCA habilitado, el número lo da ARCA
y el comprobante nace con CAE.

> 🔑 **El test que manda es el del rechazo**: si ARCA dice que no, **no puede
> quedar comprobante**. Un comprobante con un número que ARCA no autorizó deja
> el correlativo tomado de este lado y libre del otro — y el próximo intento
> choca contra la unicidad de la base sin que nadie entienda por qué.
"""

import datetime
from decimal import Decimal

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.servicios import emision_arca

# Las fixtures `cliente` y `datos` salen del conftest; de acá sólo los
# helpers, que son funciones normales.
from tests.conftest import _crear
from tests.test_comprobantes import facturar, orden


def _par():
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=730))
        .sign(clave, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        clave.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption()),
    )


@pytest.fixture
def razon_con_arca(cliente, datos):
    """Una razón social con CUIT, punto de venta y el par cargado y habilitado."""
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Suitrans SA", "cuit": "20-28993360-4", "punto_venta": 5,
    })
    certificado, clave = _par()
    assert cliente.post(f"/api/arca/{razon}/certificado",
                        files={"archivo": ("c.crt", certificado, "text/plain")},
                        ).status_code == 200
    assert cliente.post(f"/api/arca/{razon}/clave",
                        files={"archivo": ("c.key", clave, "text/plain")},
                        ).status_code == 200
    r = cliente.put(f"/api/arca/{razon}",
                    json={"ambiente": "homologacion", "habilitado": True})
    assert r.status_code == 200, r.text
    return razon


def _arca_responde(monkeypatch, *, ultimo=41, cae="75123456789012",
                   cae_vto="20261231", falla_numero=None, falla_cae=None):
    """Mockea las dos llamadas a ARCA. Devuelve la lista de lo que se le pidió."""
    pedidos = []

    async def autenticar(cert, key, ambiente, servicio="wsfe"):
        pedidos.append(("autenticar", ambiente))
        return {"token": "TKN", "sign": "SGN"}

    async def ultimo_numero(pv, tipo, cuit, token, sign, ambiente):
        pedidos.append(("ultimo", pv, tipo, cuit))
        if falla_numero:
            raise RuntimeError(falla_numero)
        return ultimo

    async def solicitar_cae(factura, cuit, token, sign, ambiente):
        pedidos.append(("cae", factura))
        if falla_cae:
            raise RuntimeError(falla_cae)
        return {"cae": cae, "cae_vto": cae_vto}

    monkeypatch.setattr(emision_arca.arca_wsaa, "autenticar_con_bytes", autenticar)
    monkeypatch.setattr(emision_arca.arca_wsfe, "ultimo_numero_autorizado", ultimo_numero)
    monkeypatch.setattr(emision_arca.arca_wsfe, "solicitar_cae", solicitar_cae)
    return pedidos


# ── El camino que sostiene la instancia viva ────────────────────────────────

def test_sin_arca_sigue_registrando_con_numero_a_mano(cliente, datos):
    """🔑 El control que evita la regresión.

    La instancia del cliente **no tiene ningún certificado cargado**. Si emitir
    reemplazara al alta de forma literal, se quedaría sin poder facturar.
    """
    a = orden(cliente, datos, "1000.00")
    r = facturar(cliente, datos, [a], numero=7)
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["numero"] == 7
    assert comp.get("cae") in (None, "")


def test_sin_arca_y_sin_numero_lo_dice(cliente, datos):
    a = orden(cliente, datos, "1000.00")
    r = cliente.post("/api/comprobantes", json={
        "fecha": "2026-08-15", "razon_social_id": datos["razon"],
        "cliente_id": datos["cliente"], "tipo": "factura_a",
        "punto_venta": 1, "orden_ids": [a["id"]],
    })
    assert r.status_code == 422
    assert "numero" in r.json()["detail"].lower()


# ── Emitir ──────────────────────────────────────────────────────────────────

def test_con_arca_el_numero_lo_da_arca(cliente, datos, razon_con_arca, monkeypatch):
    """Y el del payload se ignora: ARCA rechaza cualquiera que no sea el que
    sigue, así que mandarlo no tiene sentido."""
    pedidos = _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)

    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=999)
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["numero"] == 42, "tenia que ser el ultimo autorizado + 1"
    assert comp["cae"] == "75123456789012"
    assert comp["cae_vencimiento"] == "2026-12-31"
    # El punto de venta sale de la razon social, no del payload.
    assert comp["punto_venta"] == 5
    assert ("ultimo", 5, 1, "20-28993360-4") in pedidos


def test_la_cuenta_corriente_nombra_el_numero_real(cliente, datos, razon_con_arca,
                                                   monkeypatch):
    """🔑 El concepto del movimiento se armaba con el número del payload. Con
    ARCA ese viene vacío, así que la cuenta corriente nombraría un comprobante
    inexistente."""
    _arca_responde(monkeypatch, ultimo=41)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    comp = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None).json()

    cuenta = cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()
    concepto = cuenta["movimientos"][0]["movimiento"]["concepto"]
    assert concepto == "Factura A 0005-00000042", concepto
    assert str(comp["numero"]) in concepto


# ── El rechazo, que es lo que importa ───────────────────────────────────────

def test_si_arca_rechaza_el_cae_no_queda_comprobante(cliente, datos, razon_con_arca,
                                                     monkeypatch):
    """🔴 Ni comprobante, ni movimiento de cuenta, y las órdenes vuelven a
    pendientes.

    Un comprobante con un número que ARCA no autorizó deja el correlativo
    tomado de este lado y libre del otro: el próximo intento choca contra la
    unicidad de la base sin que nadie entienda por qué.
    """
    _arca_responde(monkeypatch, falla_cae="El comprobante ya fue autorizado")
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)

    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None)
    assert r.status_code == 502, r.text
    assert "ya fue autorizado" in r.json()["detail"]

    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []
    quedo = cliente.get(f"/api/ordenes/{a['id']}").json()
    assert quedo["estado"] == "pendiente", "la orden tenia que volver a pendiente"
    assert quedo["comprobante_id"] is None


def test_si_arca_no_da_el_numero_tampoco_queda_nada(cliente, datos, razon_con_arca,
                                                    monkeypatch):
    _arca_responde(monkeypatch, falla_numero="Computador no autorizado")
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)

    r = facturar(cliente, datos, [a], razon=razon_con_arca, numero=None)
    assert r.status_code == 502
    assert "no autorizado" in r.json()["detail"]
    assert cliente.get("/api/comprobantes").json() == [], "no puede haber quedado comprobante"


def test_el_par_cargado_pero_sin_habilitar_no_emite(cliente, datos, monkeypatch):
    """Cargar el par y no habilitar es un estado legítimo: el cliente lo subió y
    todavía no quiere emitir. Ahí sigue registrando a mano."""
    razon = _crear(cliente, "/api/razones-sociales", {
        "nombre": "Todavia No", "cuit": "20-28993360-4", "punto_venta": 3,
    })
    certificado, clave = _par()
    cliente.post(f"/api/arca/{razon}/certificado",
                 files={"archivo": ("c.crt", certificado, "text/plain")})
    cliente.post(f"/api/arca/{razon}/clave",
                 files={"archivo": ("c.key", clave, "text/plain")})
    # habilitado se queda en False

    pedidos = _arca_responde(monkeypatch)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon)
    r = facturar(cliente, datos, [a], razon=razon, numero=11)
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == 11
    assert pedidos == [], "no tenia que hablar con ARCA"


# ── Los importes que se le mandan ───────────────────────────────────────────

def test_la_factura_c_va_sin_iva_discriminado(cliente, datos, razon_con_arca,
                                              monkeypatch):
    """No es una simplificación: ARCA exige `ImpIVA = 0` e `ImpNeto = ImpTotal`
    para los tipos C, y rechaza el comprobante si se manda el IVA aparte."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    facturar(cliente, datos, [a], razon=razon_con_arca, numero=None, tipo="factura_c")

    enviado = [p[1] for p in pedidos if p[0] == "cae"][0]
    assert enviado["tipo"] == 11
    assert enviado["iva_amount"] == 0.0
    assert enviado["subtotal"] == enviado["total"]


def test_la_factura_a_manda_el_iva_aparte(cliente, datos, razon_con_arca, monkeypatch):
    """La otra mitad: sin esto, "el IVA va en cero" pasaría igual con un
    servicio que siempre manda cero."""
    pedidos = _arca_responde(monkeypatch, ultimo=0)
    a = orden(cliente, datos, "1000.00", razon_social_id=razon_con_arca)
    comp = facturar(cliente, datos, [a], razon=razon_con_arca,
                    numero=None, tipo="factura_a").json()

    enviado = [p[1] for p in pedidos if p[0] == "cae"][0]
    assert enviado["tipo"] == 1
    assert enviado["iva_amount"] > 0
    assert enviado["iva_amount"] == float(Decimal(comp["iva"]))
    assert enviado["subtotal"] == float(Decimal(comp["neto"]))
