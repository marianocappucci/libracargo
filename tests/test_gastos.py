"""Gastos de proveedor.

Lo que más se prueba acá es que **las dos cuentas se muevan juntas**: es el
bloque que en el legado eran dos `INSERT` sueltos en `ctacteprov` y
`fleteroctacte`, y si el segundo fallaba el primero ya estaba grabado.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.main import crear_app
from tests.conftest import config_de_prueba

USUARIO, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": USUARIO, "password": CLAVE}).status_code == 200
    yield c
    AuthBase.metadata.drop_all(engine)


@pytest.fixture
def partes(cliente):
    def alta(cuerpo):
        r = cliente.post("/api/terceros", json=cuerpo)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {
        "proveedor": alta({"razon_social": "Gomería Del Centro", "es_proveedor": True}),
        "fletero": alta({"razon_social": "Fletes SRL", "es_fletero": True}),
    }


def gasto(p, **extra):
    base = {
        "fecha": "2026-08-21", "proveedor_id": p["proveedor"], "fletero_id": p["fletero"],
        "descripcion": "2 cubiertas", "importe": "150000.00",
    }
    base.update(extra)
    return base


def cuenta(cliente, rol, tercero_id):
    r = cliente.get(f"/api/cuentas/{rol}/{tercero_id}")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["coinciden"] is True, "los dos caminos del saldo no coinciden"
    return Decimal(c["saldo"]), [f["movimiento"] for f in c["movimientos"]]


def test_un_gasto_mueve_las_dos_cuentas(cliente, partes):
    """🔑 Proveedor al debe, fletero al haber, en la misma transacción.

    Es el circuito entero del bloque COMPROBANTES PROVEEDORES del legado: la
    agencia le debe al proveedor lo que este entregó, y se lo descuenta al
    fletero de lo que le debe a él.
    """
    r = cliente.post("/api/gastos", json=gasto(partes))
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]

    saldo_prov, movs_prov = cuenta(cliente, "proveedor", partes["proveedor"])
    assert saldo_prov == Decimal("150000.00")
    assert Decimal(movs_prov[0]["debe"]) == Decimal("150000.00")
    assert movs_prov[0]["gasto_id"] == id_

    saldo_flet, movs_flet = cuenta(cliente, "fletero", partes["fletero"])
    assert saldo_flet == Decimal("-150000.00")
    assert Decimal(movs_flet[0]["haber"]) == Decimal("150000.00")
    assert movs_flet[0]["gasto_id"] == id_


def test_editar_corrige_las_dos_cuentas_sin_duplicar(cliente, partes):
    """Una línea por cuenta, no dos: es lo que hace el `UPDATE` del legado."""
    id_ = cliente.post("/api/gastos", json=gasto(partes)).json()["id"]
    r = cliente.put(f"/api/gastos/{id_}", json=gasto(partes, importe="180000.00"))
    assert r.status_code == 200, r.text

    saldo_prov, movs_prov = cuenta(cliente, "proveedor", partes["proveedor"])
    assert saldo_prov == Decimal("180000.00")
    assert len(movs_prov) == 1
    saldo_flet, movs_flet = cuenta(cliente, "fletero", partes["fletero"])
    assert saldo_flet == Decimal("-180000.00")
    assert len(movs_flet) == 1


def test_cambiar_el_fletero_mueve_el_descuento_de_cuenta(cliente, partes):
    otro = cliente.post("/api/terceros",
                        json={"razon_social": "Otro Flete", "es_fletero": True}).json()["id"]
    id_ = cliente.post("/api/gastos", json=gasto(partes)).json()["id"]
    cliente.put(f"/api/gastos/{id_}", json=gasto(partes, fletero_id=otro))

    assert cuenta(cliente, "fletero", partes["fletero"]) == (Decimal("0.00"), [])
    saldo_otro, _ = cuenta(cliente, "fletero", otro)
    assert saldo_otro == Decimal("-150000.00")


def test_anular_deja_las_cuatro_lineas_y_los_saldos_en_cero(cliente, partes):
    """Anular no borra: quedan las dos originales y sus dos contrapartidas."""
    id_ = cliente.post("/api/gastos", json=gasto(partes)).json()["id"]
    r = cliente.delete(f"/api/gastos/{id_}")
    assert r.status_code == 200, r.text
    assert r.json()["anulado"] is True

    saldo_prov, movs_prov = cuenta(cliente, "proveedor", partes["proveedor"])
    assert saldo_prov == Decimal("0.00")
    assert len(movs_prov) == 2
    saldo_flet, movs_flet = cuenta(cliente, "fletero", partes["fletero"])
    assert saldo_flet == Decimal("0.00")
    assert len(movs_flet) == 2
    # La reversión lleva la fecha del gasto, no la de hoy: con la de hoy, entre
    # el cargo y su anulación la cuenta mostraría una deuda que ningún total
    # del período reconoce.
    assert movs_prov[1]["fecha"] == "2026-08-21"


def test_un_gasto_anulado_no_se_edita_ni_se_vuelve_a_anular(cliente, partes):
    id_ = cliente.post("/api/gastos", json=gasto(partes)).json()["id"]
    cliente.delete(f"/api/gastos/{id_}")
    assert cliente.put(f"/api/gastos/{id_}", json=gasto(partes)).status_code == 409
    assert cliente.delete(f"/api/gastos/{id_}").status_code == 409


def test_el_fletero_es_obligatorio(cliente, partes):
    """No es comodidad del modelo: en el legado los 2.799 gastos lo tienen. Uno
    que no se le descuenta a nadie es un gasto general y va por caja."""
    cuerpo = gasto(partes)
    del cuerpo["fletero_id"]
    assert cliente.post("/api/gastos", json=cuerpo).status_code == 422


def test_el_mismo_tercero_no_puede_ser_las_dos_partes(cliente, partes):
    """Los dos desplegables tienen los mismos terceros adentro."""
    ambos = cliente.post("/api/terceros", json={
        "razon_social": "Mixto", "es_proveedor": True, "es_fletero": True}).json()["id"]
    r = cliente.post("/api/gastos",
                     json=gasto(partes, proveedor_id=ambos, fletero_id=ambos))
    assert r.status_code in (409, 422), r.text


def test_el_importe_tiene_que_ser_positivo(cliente, partes):
    assert cliente.post("/api/gastos", json=gasto(partes, importe="0")).status_code == 422
    assert cliente.post("/api/gastos", json=gasto(partes, importe="-5")).status_code == 422


def test_el_listado_filtra_por_proveedor_fletero_y_fecha(cliente, partes):
    otro = cliente.post("/api/terceros",
                        json={"razon_social": "Otro Flete", "es_fletero": True}).json()["id"]
    cliente.post("/api/gastos", json=gasto(partes, fecha="2026-07-10"))
    cliente.post("/api/gastos", json=gasto(partes, fecha="2026-08-15", fletero_id=otro))

    assert len(cliente.get("/api/gastos").json()) == 2
    assert len(cliente.get(f"/api/gastos?fletero_id={otro}").json()) == 1
    assert len(cliente.get("/api/gastos?desde=2026-08-01").json()) == 1
    assert len(cliente.get(f"/api/gastos?proveedor_id={partes['proveedor']}").json()) == 2
    # Control negativo: un filtro que no matchea da vacío, no todo.
    assert cliente.get("/api/gastos?desde=2030-01-01").json() == []


def test_los_anulados_se_ven_por_omision(cliente, partes):
    """Esconderlos haría que un importe que no aparece en la cuenta no tenga
    explicación en pantalla. Mismo criterio que comprobantes."""
    id_ = cliente.post("/api/gastos", json=gasto(partes)).json()["id"]
    cliente.delete(f"/api/gastos/{id_}")
    assert len(cliente.get("/api/gastos").json()) == 1
    assert len(cliente.get("/api/gastos?anulado=false").json()) == 0
    assert len(cliente.get("/api/gastos?anulado=true").json()) == 1


def test_dar_de_baja_un_proveedor_con_gastos_no_pierde_el_gasto(cliente, partes):
    """La baja del ABM es **lógica**: marca `activo=false` y no borra la fila.

    Por eso el `RESTRICT` de la clave foránea no llega a actuar desde la API —
    está para lo que pase por debajo—. Lo que hay que fijar es que el gasto
    siga apuntando a su proveedor y la cuenta siga cuadrando, que es lo que le
    importa a quien la mira.
    """
    id_ = cliente.post("/api/gastos", json=gasto(partes)).json()["id"]
    r = cliente.delete(f"/api/terceros/{partes['proveedor']}")
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False

    assert cliente.get(f"/api/gastos/{id_}").json()["proveedor_id"] == partes["proveedor"]
    saldo, _ = cuenta(cliente, "proveedor", partes["proveedor"])
    assert saldo == Decimal("150000.00")


def test_sin_sesion_no_se_cargan_gastos(engine, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = config_de_prueba()
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get("/api/gastos").status_code == 401
        assert anonimo.post("/api/gastos", json={}).status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)
