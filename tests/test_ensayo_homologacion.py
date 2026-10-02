"""El ensayo de emisión contra **ARCA de verdad** (homologación).

Los tests de `test_emision_arca.py` mockean las llamadas a ARCA: prueban que
LibraCargo arma bien el pedido, no que ARCA lo acepte. Éstos corren **la misma app
y el mismo camino de emisión sin mockear nada**, contra el WSFE de homologación, con
un certificado real. Es lo que faltaba para dar por buena la facturación: el
2026-10-02 apareció así que ARCA rechaza una factura sin la condición de IVA del
receptor, algo que ningún mock podía mostrar.

**No corren solos**: sin las variables de abajo se saltean, y el CI no los ve. Un
comprobante de homologación no tiene efecto fiscal, pero el WSFE de prueba lo
numera, así que no se corren en cada push.

    ARCA_HOMO_CERT=~/.arca-certs/suitrans-wscpe/wscpe-homologacion.crt \\
    ARCA_HOMO_KEY=~/.arca-certs/suitrans-wscpe/wscpe-homologacion.key \\
    ARCA_HOMO_CUIT=23277071614 \\
    ARCA_HOMO_TICKET=~/.arca-certs/suitrans-wscpe/ta-homologacion-wsfe.json \\
    pytest tests/test_ensayo_homologacion.py -v

- `ARCA_HOMO_CERT` / `ARCA_HOMO_KEY`: el par de **homologación**, con el servicio
  `wsfe` asociado en WSASS. Nunca el de producción.
- `ARCA_HOMO_CUIT`: el CUIT del certificado, que es el de la razón social que emite
  (la guarda de `emision_arca.configuracion_activa` los exige iguales).
- `ARCA_HOMO_PV`: el punto de venta. Por defecto 1, que homologación acepta.
- `ARCA_HOMO_TICKET` (opcional): un ticket de WSAA **vigente** de ese certificado.
  WSAA rechaza pedir uno nuevo mientras haya otro válido (`coe.alreadyAuthenticated`),
  así que si ya hay uno afuera se siembra la caché del motor con él en lugar de
  hacer otro login.

El certificado, la clave y el ticket **no se imprimen** ni se copian a ningún repo.

🔴 **La FCE MiPyME no está cubierta acá**: `TipoComprobante` de este producto no
tiene los tipos 201 a 213 (pide una migración del `ENUM`). La FCE está probada
contra homologación en el motor, por su camino de facturas.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from libracore import arca_credenciales, arca_wsaa

from app.servicios import emision_arca
from tests.test_comprobantes import facturar, orden

CERT = os.environ.get("ARCA_HOMO_CERT")
CLAVE = os.environ.get("ARCA_HOMO_KEY")
CUIT = os.environ.get("ARCA_HOMO_CUIT")
PUNTO_VENTA = int(os.environ.get("ARCA_HOMO_PV", "1"))
TICKET = os.environ.get("ARCA_HOMO_TICKET")

pytestmark = pytest.mark.skipif(
    not (CERT and CLAVE and CUIT),
    reason="ensayo contra ARCA: faltan ARCA_HOMO_CERT, ARCA_HOMO_KEY y ARCA_HOMO_CUIT",
)

#: Un CUIT de receptor con dígito verificador válido, para las facturas A.
CUIT_DEL_RECEPTOR = "30-70933285-2"
#: Otro, para el monotributista: tiene que ser distinto del emisor.
CUIT_MONOTRIBUTISTA = "20-28993360-4"


def _cargar_par_real(cliente):
    """Deja la instancia en homologación con el par real. Mismo camino que la pantalla."""
    r = cliente.put("/api/arca", json={
        "empresa": emision_arca.EMPRESA_ARCA, "cuit": CUIT,
        "punto_venta": PUNTO_VENTA, "ambiente": "homologacion", "alias": "",
    })
    assert r.status_code == 200, r.text
    for tramo, ruta in (("certificado", CERT), ("clave", CLAVE)):
        contenido = Path(ruta).expanduser().read_bytes()
        r = cliente.post(f"/api/arca/{tramo}", params={"ambiente": "homologacion"},
                         files={"archivo": (f"c.{tramo}", contenido, "text/plain")})
        assert r.status_code == 200, r.text


def _sembrar_ticket(tmp_path, monkeypatch):
    """Aísla la caché de tickets del test y, si hay uno vigente afuera, lo siembra."""
    monkeypatch.setenv("ARCA_TA_DIR", str(tmp_path / "arca_ta"))
    if not TICKET:
        return
    cert, _clave = arca_credenciales.paths_en_disco(
        emision_arca.configuracion_de_la_instancia(), "homologacion")
    ticket = json.loads(Path(TICKET).expanduser().read_text(encoding="utf-8"))
    ruta = arca_wsaa._ruta_del_ticket(cert, "homologacion", "wsfe")
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    # API privada del motor: no hay una pública para sembrar la caché.
    arca_wsaa._guardar_ticket(ruta, ticket)
    assert arca_wsaa._leer_ticket(ruta), (
        "el ticket de ARCA_HOMO_TICKET ya venció: borralo o pasá uno vigente")


@pytest.fixture
def instancia(cliente, datos, tmp_path, monkeypatch):
    """Una instancia **de prueba**, con una razón social que tiene el CUIT del certificado."""
    razon = cliente.post("/api/razones-sociales", json={
        "nombre": "Razón de ensayo", "cuit": CUIT, "punto_venta": PUNTO_VENTA,
    })
    assert razon.status_code == 201, razon.text
    _cargar_par_real(cliente)
    _sembrar_ticket(tmp_path, monkeypatch)
    return razon.json()["id"]


def _receptor(cliente, datos, **campos):
    r = cliente.put(f"/api/terceros/{datos['cliente']}", json={
        "razon_social": "Agro Norte", "es_cliente": True, **campos})
    assert r.status_code == 200, r.text


def _hoy() -> str:
    """La fecha del comprobante. **Tiene que ser de hoy:** ARCA rechaza con el 10016 una
    factura de productos con fecha de más de 5 días de distancia, y los helpers de la
    suite facturan con una fecha fija de agosto, que sirve contra un mock y no contra ARCA."""
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date().isoformat()


def _ensayar(cliente, datos, instancia, tipo):
    a = orden(cliente, datos, "1000.00", razon_social_id=instancia, fecha=_hoy())
    r = facturar(cliente, datos, [a], razon=instancia, tipo=tipo, numero=None, fecha=_hoy())
    if r.status_code == 502 and "alreadyAuthenticated" in r.text:
        pytest.skip("ARCA ya tiene un ticket vigente de este certificado: "
                    "pasá ARCA_HOMO_TICKET con ese ticket y reintentá")
    return a, r


def test_una_factura_b_a_consumidor_final_obtiene_cae(cliente, datos, instancia):
    """Lo básico: el pedido sale completo —con la condición de IVA del receptor— y ARCA lo autoriza."""
    _receptor(cliente, datos, condicion_iva="consumidor_final")

    _, r = _ensayar(cliente, datos, instancia, "factura_b")

    assert r.status_code == 200, r.text   # 200 y no 201: es un ensayo
    cuerpo = r.json()
    assert cuerpo["ensayo"] is True and cuerpo["ambiente"] == "homologacion"
    assert re.fullmatch(r"\d{14}", cuerpo["cae"]), cuerpo
    assert cuerpo["numero"] >= 1, "el número lo da ARCA"
    assert cuerpo["punto_venta"] == PUNTO_VENTA


def test_una_factura_a_a_un_responsable_inscripto_obtiene_cae(cliente, datos, instancia):
    _receptor(cliente, datos, condicion_iva="responsable_inscripto", cuit=CUIT_DEL_RECEPTOR)

    _, r = _ensayar(cliente, datos, instancia, "factura_a")

    assert r.status_code == 200, r.text
    assert re.fullmatch(r"\d{14}", r.json()["cae"]), r.json()


def test_dos_ensayos_seguidos_no_chocan_con_el_ticket(cliente, datos, instancia):
    """El defecto de `libracore` v1.118.0: pedía un ticket por emisión y la segunda fallaba.

    Con la caché del motor (v1.119.0) los dos salen con CAE y distintos.
    """
    _receptor(cliente, datos, condicion_iva="consumidor_final")

    _, primero = _ensayar(cliente, datos, instancia, "factura_b")
    _, segundo = _ensayar(cliente, datos, instancia, "factura_b")

    assert primero.status_code == 200 and segundo.status_code == 200, (primero.text, segundo.text)
    assert primero.json()["cae"] != segundo.json()["cae"]
    assert segundo.json()["numero"] == primero.json()["numero"] + 1


def test_el_ensayo_contra_arca_real_no_deja_nada(cliente, datos, instancia):
    """El mismo rollback de siempre, ahora con un CAE verdadero de por medio."""
    _receptor(cliente, datos, condicion_iva="consumidor_final")

    a, r = _ensayar(cliente, datos, instancia, "factura_b")

    assert r.status_code == 200, r.text
    assert cliente.get("/api/comprobantes").json() == []
    quedo = cliente.get(f"/api/ordenes/{a['id']}").json()
    assert quedo["estado"] == "pendiente" and quedo["comprobante_id"] is None
    assert cliente.get(f"/api/cuentas/cliente/{datos['cliente']}").json()["movimientos"] == []


def test_una_factura_b_a_un_monotributista_la_rechaza_arca_y_no_queda_nada(
        cliente, datos, instancia):
    """Medido el 2026-10-02: ARCA no acepta la letra B para un receptor monotributista (10243).

    LibraCargo deja elegir la letra a quien factura y no la valida: el error de ARCA
    llega tal cual, y sin dejar comprobante. Es un hueco de la pantalla (podría
    sugerir la letra), no de la emisión.
    """
    _receptor(cliente, datos, condicion_iva="monotributo", cuit=CUIT_MONOTRIBUTISTA)

    a, r = _ensayar(cliente, datos, instancia, "factura_b")

    assert r.status_code == 502, r.text
    assert "10243" in r.text, r.text
    assert cliente.get("/api/comprobantes").json() == []
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"


def test_un_cliente_con_cuit_y_sin_condicion_no_obtiene_cae_y_dice_que_cargar(
        cliente, datos, instancia):
    """`no_categorizado` es «no sé»: el motor no adivina y el mensaje dice qué hacer."""
    _receptor(cliente, datos, condicion_iva="no_categorizado", cuit=CUIT_DEL_RECEPTOR)

    a, r = _ensayar(cliente, datos, instancia, "factura_a")

    assert r.status_code == 502, r.text
    assert "condición de IVA del cliente" in r.text, r.text
    assert cliente.get(f"/api/ordenes/{a['id']}").json()["estado"] == "pendiente"
