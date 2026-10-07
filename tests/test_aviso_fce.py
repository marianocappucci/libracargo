"""¿A este comprobante le corresponde ser FCE? El aviso de «Facturar pendientes», antes de emitir.

La regla es del motor (`libracore.arca_wsfecred.corresponde_fce`, probada allá contra respuestas reales de
homologación); acá se prueba **lo propio**: con qué configuración se pregunta (la de ARCA si su CUIT es el de la
empresa, y ninguna si no), con el CUIT de qué cliente, y qué pasa cuando no se puede preguntar.
"""

from datetime import date
from decimal import Decimal

import pytest
from libracore import arca_wsfecred

from tests.conftest import cargar_empresa
from tests.test_emision_arca import CUIT, empresa_con_arca  # noqa: F401
from tests.test_fce import empresa_con_fce  # noqa: F401

RUTA = "/api/comprobantes/fce/corresponde"


@pytest.fixture
def registro(monkeypatch):
    """El registro de FCE de mentira: anota con qué se le preguntó y contesta lo que se le diga."""
    pedidos = []
    respuesta = {"disponible": True, "corresponde": True, "obligado": True, "monto_desde": "3958316"}

    async def corresponde(cfg, cuit, total, fecha):
        pedidos.append({"cuit_emisor": cfg and cfg["cuit"], "cuit": cuit, "total": total, "fecha": fecha})
        if cfg is None:
            return {"disponible": False,
                    "motivo": "ARCA no está configurado: no se puede consultar el registro de FCE."}
        return dict(respuesta)

    monkeypatch.setattr(arca_wsfecred, "corresponde_fce", corresponde)
    return pedidos


def test_pregunta_con_la_empresa_que_emite_y_el_cuit_del_cliente(cliente, datos, empresa_con_arca, registro):  # noqa: F811
    r = cliente.get(RUTA, params={"cliente_id": datos["cliente"],
                                  "total": "4840000.00", "fecha": "2026-10-05"})
    assert r.status_code == 200, r.text
    assert r.json() == {"disponible": True, "corresponde": True, "obligado": True, "monto_desde": "3958316",
                        "fce_habilitada": False}
    assert registro == [{"cuit_emisor": CUIT, "cuit": "30-12345678-1", "total": Decimal("4840000.00"),
                         "fecha": date(2026, 10, 5)}]


def test_con_cbu_y_modalidad_la_fce_esta_habilitada(cliente, datos, empresa_con_fce, registro):  # noqa: F811
    r = cliente.get(RUTA, params={"cliente_id": datos["cliente"], "total": "10"})
    assert r.status_code == 200 and r.json()["fce_habilitada"] is True


def test_si_el_cuit_de_arca_no_es_el_de_la_empresa_no_pregunta_con_esa_config(
        cliente, datos, empresa_con_arca, registro):  # noqa: F811
    """🔑 La configuración de ARCA sirve sólo al CUIT de la empresa: preguntar con ella estando la empresa con otro
    CUIT sería consultar el registro como otro contribuyente."""
    cargar_empresa(cliente, cuit="30-99999999-7")
    r = cliente.get(RUTA, params={"cliente_id": datos["cliente"], "total": "10"})
    assert r.status_code == 200
    assert r.json()["disponible"] is False
    assert registro[0]["cuit_emisor"] is None


def test_un_cliente_sin_cuit_no_se_pregunta(cliente, datos, empresa_con_arca, registro):  # noqa: F811
    r = cliente.get(RUTA, params={"cliente_id": datos["otro_cliente"],
                                  "total": "10"})
    assert r.status_code == 200
    assert r.json() == {"disponible": False, "motivo": "el cliente no tiene CUIT cargado", "fce_habilitada": False}
    assert registro == []


@pytest.mark.parametrize("cambio, status", [
    ({"total": "0"}, 422), ({"total": "true"}, 422), ({"cliente_id": 999}, 404),
])
def test_valida_lo_que_le_preguntan(cliente, datos, empresa_con_arca, registro, cambio, status):  # noqa: F811
    params = {"cliente_id": datos["cliente"], "total": "10"} | cambio
    assert cliente.get(RUTA, params=params).status_code == status
    assert registro == []
