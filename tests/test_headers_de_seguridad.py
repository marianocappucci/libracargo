"""Los headers de seguridad, montados en ESTE producto.

El middleware vive en libracore y ya tiene sus propios tests. Lo que este
archivo cuida es otra cosa: que **esté cableado acá**. Es la diferencia que se
cobró caro en septiembre — el middleware existía desde antes y seis de los ocho
productos no lo montaban, así que la política estaba escrita y no se aplicaba a
nadie.
"""
from libracore.security_headers import CSP, CSP_SPA


def test_las_respuestas_traen_los_headers_de_seguridad(cliente):
    r = cliente.get("/health")
    assert r.headers["Content-Security-Policy"] == CSP_SPA
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in r.headers["Permissions-Policy"]
    assert "includeSubDomains" in r.headers["Strict-Transport-Security"]


def test_es_la_politica_de_SPA_y_no_la_de_las_apps_Jinja(cliente):
    """El producto no carga nada externo: habilitarle un CDN que no usa sería
    superficie regalada. Y sin `unsafe-inline` en `script-src`, que es la
    diferencia que de verdad defiende."""
    csp = cliente.get("/health").headers["Content-Security-Policy"]
    assert "jsdelivr" not in csp
    assert "jsdelivr" in CSP, "control positivo: la de Jinja sí lo tiene"
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_tambien_en_una_respuesta_de_error(cliente):
    """El middleware se agrega último para quedar más externo. Si estuviera
    adentro, una ruta inexistente saldría sin headers — y una respuesta de error
    es tan renderizable en un navegador como cualquier otra."""
    r = cliente.get("/una-ruta-que-no-existe-en-ningun-producto")
    assert r.headers["Content-Security-Policy"] == CSP_SPA
