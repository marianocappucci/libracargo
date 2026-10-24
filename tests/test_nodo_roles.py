"""La matriz de roles del nodo: quién puede entrar a cada ruta de LibraEdge (ADR-056).

Una segunda declaración, escrita a mano y **no derivada del código**, de quién tiene que poder entrar a las rutas que
suma el nodo. Si saliera del código, un cambio de guarda movería el código y el test juntos y no se pondría rojo nunca.

- **`NODO`**: las que autentica el secreto del nodo (`libraedge.sync.api.RUTAS_AUTENTICADAS_POR_NODO`). No las decide el
  rol: una sesión de administrador **no** alcanza (401), y sin el secreto tampoco.
- **`CODIGO`**: `POST /sync/v1/vinculacion`, el canje del código. Lo llama el instalador del nodo, sin sesión; lo
  protegen el código (un solo uso, 15 minutos) y el límite de intentos del motor. Anónimo llega al motor (no es 401 ni
  403).
- **`SALUD`**: las dos de uptime-kuma, con su propio token (`LIBRAEDGE_TOKEN_MONITOREO`): sin la variable, 404.
- **`ADMIN`**: la pantalla «Sucursal sin internet» (`/api/nodos-offline*`) y lo que decide sobre un documento fiscal
  de la cola (reintentar, descartar y marcar emitido). Un operador (`staff`) recibe 403.
- **`STAFF`**: ver la cola, pedir que se emita y la barra de estado. Cualquier usuario de la instancia.

**Cobertura.** Una ruta nueva de estos prefijos que la tabla no conoce hace fallar `test_toda_ruta_tiene_fila`: un
router que alguien monta sin decidir quién entra se nota acá. Las filas que ya no existen también fallan.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

NODO, CODIGO, SALUD, ADMIN, STAFF = "NODO", "CODIGO", "SALUD", "ADMIN", "STAFF"

TABLA = {
    ("POST", "/sync/v1/push"): NODO,
    ("GET", "/sync/v1/pull"): NODO,
    ("POST", "/sync/v1/ticket-arca"): NODO,
    ("GET", "/sync/v1/carga-inicial"): NODO,
    ("POST", "/sync/v1/vinculacion"): CODIGO,
    ("GET", "/sync/v1/salud"): SALUD,
    ("GET", "/sync/v1/salud/{node_id}"): SALUD,
    ("GET", "/api/nodos-offline"): ADMIN,
    ("GET", "/api/nodos-offline/menu"): ADMIN,
    ("POST", "/api/nodos-offline"): ADMIN,
    ("POST", "/api/nodos-offline/vinculacion"): ADMIN,
    ("POST", "/api/nodos-offline/{node_id}/carga"): ADMIN,
    ("POST", "/api/nodos-offline/{node_id}/vinculacion"): ADMIN,
    ("DELETE", "/api/nodos-offline/{node_id}/vinculacion"): ADMIN,
    ("DELETE", "/api/nodos-offline/{node_id}"): ADMIN,
    ("GET", "/api/nodo/cola"): STAFF,
    ("POST", "/api/nodo/cola/emitir"): STAFF,
    ("POST", "/api/nodo/cola/{pedido_id}/reintentar"): ADMIN,
    ("POST", "/api/nodo/cola/{pedido_id}/descartar"): ADMIN,
    ("POST", "/api/nodo/cola/{pedido_id}/emitido"): ADMIN,
    ("GET", "/api/estado-del-sistema"): STAFF,
}
PREFIJOS = ("/sync/", "/api/nodos-offline", "/api/nodo/", "/api/estado-del-sistema")


def _rutas_reales(app) -> set[tuple[str, str]]:
    """Las operaciones que publica `openapi.json` bajo los prefijos del nodo. (FastAPI arma las rutas de un router
    incluido de forma perezosa: `app.routes` no las lista, el esquema sí.)"""
    reales = set()
    for camino, operaciones in app.openapi()["paths"].items():
        if camino.startswith(PREFIJOS):
            reales.update((m.upper(), camino) for m in operaciones if m.upper() not in ("HEAD", "OPTIONS"))
    return reales


#: Las rutas del nodo autentican **adentro** del handler, después de leer el cuerpo: con uno mal formado contestan 422
#: antes de llegar al 401. Se les manda uno bien formado (e inofensivo: el nodo «x» no existe).
CUERPOS = {
    ("POST", "/sync/v1/push"): {
        "operation_id": "x:1", "node_id": "x", "sequence": 1, "operation_type": "cargo.orden",
        "aggregate_type": "orden", "aggregate_id": "x:orden:1", "occurred_at": "2026-10-24T00:00:00+00:00",
        "schema_version": 1, "payload": {}},
    ("POST", "/sync/v1/ticket-arca"): {"node_id": "x", "emisor_id": None, "servicio": "wsfe"},
}


def _sondeo(cliente, metodo: str, camino: str):
    """Pega con ids que no existen y un cuerpo que no es un objeto: el rol se chequea antes de validar el cuerpo, así
    que quien no debe recibe 401/403 y quien debe recibe otra cosa (422, 404...) sin que se ejecute nada."""
    url = re.sub(r"\{[^}]+\}", "999999", camino)
    if metodo == "GET":
        return cliente.get(url, params={"node_id": "x"})
    return cliente.request(metodo, url, json=CUERPOS.get((metodo, camino), []))


@pytest.fixture
def staff(cliente):
    r = cliente.post("/api/usuarios", json={
        "username": "marta", "name": "Marta", "password": "una-clave", "role": "staff"})
    assert r.status_code == 201, r.text
    otro = TestClient(cliente.app, base_url="https://testserver")
    assert otro.post("/auth/login", json={"username": "marta", "password": "una-clave"}).status_code == 200
    return otro


@pytest.fixture
def anonimo(cliente):
    return TestClient(cliente.app, base_url="https://testserver")


def test_toda_ruta_tiene_fila(cliente):
    reales = _rutas_reales(cliente.app)
    assert not reales - set(TABLA), f"rutas del nodo sin fila en la matriz: {sorted(reales - set(TABLA))}"
    assert not set(TABLA) - reales, f"filas de la matriz que ya no existen: {sorted(set(TABLA) - reales)}"


@pytest.mark.parametrize("ruta", [r for r, quien in TABLA.items() if quien == NODO])
def test_las_rutas_del_nodo_las_autentica_el_secreto_y_no_la_sesion(cliente, anonimo, ruta):
    metodo, camino = ruta
    assert _sondeo(anonimo, metodo, camino).status_code == 401
    # Una sesión de administrador no es el secreto del nodo.
    assert _sondeo(cliente, metodo, camino).status_code == 401


def test_el_canje_del_codigo_no_pide_sesion(cliente, anonimo):
    for quien in (anonimo, cliente):
        r = _sondeo(quien, "POST", "/sync/v1/vinculacion")
        assert r.status_code not in (401, 403), r.text


@pytest.mark.parametrize("ruta", [r for r, quien in TABLA.items() if quien == SALUD])
def test_la_salud_sin_token_de_monitoreo_no_existe(cliente, anonimo, ruta):
    metodo, camino = ruta
    assert _sondeo(anonimo, metodo, camino).status_code == 404


@pytest.mark.parametrize("ruta", [r for r, quien in TABLA.items() if quien == ADMIN])
def test_las_de_administrador_rechazan_al_anonimo_y_al_operador(cliente, staff, anonimo, ruta):
    metodo, camino = ruta
    assert _sondeo(anonimo, metodo, camino).status_code == 401
    assert _sondeo(staff, metodo, camino).status_code == 403
    assert _sondeo(cliente, metodo, camino).status_code not in (401, 403)


@pytest.mark.parametrize("ruta", [r for r, quien in TABLA.items() if quien == STAFF])
def test_las_de_staff_las_abre_cualquier_usuario_de_la_instancia(cliente, staff, anonimo, ruta):
    metodo, camino = ruta
    assert _sondeo(anonimo, metodo, camino).status_code == 401
    for quien in (staff, cliente):
        assert _sondeo(quien, metodo, camino).status_code not in (401, 403)
