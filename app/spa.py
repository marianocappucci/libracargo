"""Qué se sirve del build del frontend y qué cae en la SPA.

Vive aparte de quien monta las rutas **para poder probarlo sin construir la
aplicación**: es una función y una tabla, sin nada que ocurra al importar.
"""

from __future__ import annotations

from pathlib import Path

# `mimetypes` no conoce `.webmanifest`, y sin un tipo que el navegador acepte
# no hay aplicación instalable.
TIPOS_PROPIOS = {".webmanifest": "application/manifest+json"}


def archivo_publico(dist, ruta: str) -> Path | None:
    """El archivo real de `dist` que corresponde a `ruta`, o None para caer al index.

    🔴 Existe por el catch-all de la SPA, que **devuelve `index.html` con 200
    para cualquier cosa**. Sin esto `/manifest.webmanifest` y `/sw.js` no
    fallan: contestan 200 con el cuerpo equivocado, el navegador descarta el
    manifest en silencio y no queda nada que mirar para darse cuenta.

    Sólo se sirve lo que existe de verdad adentro de `dist`. El resto cae en la
    SPA, que es lo que hace andar el ruteo del lado del cliente — e
    `index.html` también, para no tener dos caminos hacia el mismo archivo.
    """
    if not ruta or ruta.endswith("/"):
        return None
    raiz = Path(dist).resolve()
    candidato = (raiz / ruta).resolve()
    if raiz not in candidato.parents:
        return None  # un `..` que se escapa de dist
    if candidato.name == "index.html" or not candidato.is_file():
        return None
    return candidato
