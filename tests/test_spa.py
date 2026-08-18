"""El catch-all de la SPA sirve `index.html` con 200 para cualquier ruta.

Eso hace andar el ruteo del lado del cliente y, al mismo tiempo, es una trampa:
un archivo que el navegador espera con su propio tipo —un manifest, un service
worker— recibe HTML con 200 y se descarta en silencio.
"""

from __future__ import annotations

from app.spa import archivo_publico


def test_un_archivo_que_existe_se_sirve(tmp_path):
    (tmp_path / "manifest.webmanifest").write_text("{}")
    assert archivo_publico(tmp_path, "manifest.webmanifest") is not None


def test_lo_que_no_existe_cae_en_la_spa(tmp_path):
    assert archivo_publico(tmp_path, "ordenes/nueva") is None


def test_el_index_cae_en_la_spa_igual(tmp_path):
    """Para no tener dos caminos hacia el mismo archivo."""
    (tmp_path / "index.html").write_text("<html></html>")
    assert archivo_publico(tmp_path, "index.html") is None


def test_no_se_escapa_del_dist(tmp_path):
    """El control que importa: sin él, `../` sirve cualquier archivo del disco."""
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("no")
    dist = tmp_path / "dist"
    dist.mkdir()
    assert archivo_publico(dist, "../secreto.txt") is None


def test_una_ruta_vacia_o_de_directorio_cae_en_la_spa(tmp_path):
    assert archivo_publico(tmp_path, "") is None
    assert archivo_publico(tmp_path, "ordenes/") is None
