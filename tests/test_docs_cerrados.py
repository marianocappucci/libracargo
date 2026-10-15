"""El Swagger de LibraCargo no se publica en producción (ADR-053 de libracore).

Medido el 2026-10-15: `/docs`, `/redoc` y `/openapi.json` daban 200 sin sesión en las instancias
reales y en la demo, con el mapa de todas las rutas. `app/main.py` llama ahora a
`libracore.docs_api.cerrar_docs_de_la_api(app)` justo después de crear la app: sólo `ENV=development`
(la marca de la suite y del compose de desarrollo) o `LIBRA_DOCS_API=1` a propósito los sirven.

El criterio y sus bordes tienen sus pruebas en libracore; acá se fija que **este** producto lo usa,
y se mide contra la app de verdad y sin sesión.
"""
import pytest
from fastapi.testclient import TestClient

RUTAS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


@pytest.fixture
def produccion(monkeypatch):
    """Lo que tiene una instancia real. Va **después** de la fixture de la app: ésa fija `ENV=development` al armarla.

    Una instancia real tiene `LIBRA_ENTORNO=cliente`, y ni `ENV=development` ni el interruptor del Swagger."""
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("LIBRA_DOCS_API", raising=False)
    monkeypatch.setenv("LIBRA_ENTORNO", "cliente")


def _estados(c) -> dict:
    return {ruta: c.get(ruta).status_code for ruta in RUTAS}


def test_en_produccion_el_swagger_da_404_sin_sesion(cliente, produccion):
    c = TestClient(cliente.app, base_url="https://testserver")
    assert _estados(c) == dict.fromkeys(RUTAS, 404)
    assert c.get("/openapi.json").json() == {"detail": "Not Found"}


def test_en_la_demo_tambien(cliente, produccion, monkeypatch):
    """Su esquema es el mismo que el de un cliente real y la demo es pública: cerrada igual."""
    monkeypatch.setenv("LIBRA_ENTORNO", "demo")
    assert _estados(TestClient(cliente.app, base_url="https://testserver")) == dict.fromkeys(RUTAS, 404)


def test_en_desarrollo_se_sigue_viendo(cliente, monkeypatch):
    """`ENV=development` lo fija la suite entera: el Swagger se ve y trae las rutas del producto."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("LIBRA_DOCS_API", raising=False)
    c = TestClient(cliente.app, base_url="https://testserver")
    esquema = c.get("/openapi.json")
    assert esquema.status_code == 200
    assert set(esquema.json()["paths"]) == set(c.app.openapi()["paths"]) and esquema.json()["paths"]
    assert c.get("/docs").status_code == 200 and c.get("/redoc").status_code == 200


def test_con_la_spa_montada_como_en_produccion_sigue_dando_404_y_no_el_index(cliente, produccion, tmp_path):
    """🔴 El catch-all de la SPA contesta `index.html` con 200 a lo que no existe: la guarda tiene que ganarle."""
    from libracore.spa import montar_spa

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>la SPA</html>")
    c = TestClient(cliente.app, base_url="https://testserver")
    montar_spa(c.app, tmp_path)
    assert _estados(c) == dict.fromkeys(RUTAS, 404)
    assert "la SPA" in c.get("/una-pantalla").text  # el control: la SPA sigue atendiendo lo suyo
