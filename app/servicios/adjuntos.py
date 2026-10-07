"""Adjuntos de una orden: la foto del ticket de descarga, un remito escaneado (ADR-037).

🔑 **El tipo se decide por el contenido, no por lo que declara el navegador.** Un celular manda la foto con el
`Content-Type` que quiera, y uno falso hace que el navegador la abra como otra cosa al descargarla. Se miran los
primeros bytes (la «firma» del formato) y se guarda el tipo que corresponde a esa firma.
"""

from __future__ import annotations

import re

#: 10 MB. Una foto de celular ronda 2-5 MB; un PDF escaneado de una página, menos.
TAMANIO_MAXIMO = 10 * 1024 * 1024


class AdjuntoInvalido(ValueError):
    """El archivo no se puede adjuntar: vacío, muy grande o de un tipo que no se acepta."""


def _es_heic(cabecera: bytes) -> bool:
    # ISO-BMFF: `....ftyp` y la marca del formato. Es lo que manda la cámara de un iPhone.
    return cabecera[4:8] == b"ftyp" and cabecera[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc")


#: `(tipo, prueba sobre los primeros bytes)`.
_FORMATOS = (
    ("image/jpeg", lambda c: c.startswith(b"\xff\xd8\xff")),
    ("image/png", lambda c: c.startswith(b"\x89PNG\r\n\x1a\n")),
    ("image/webp", lambda c: c[:4] == b"RIFF" and c[8:12] == b"WEBP"),
    ("image/heic", _es_heic),
    ("application/pdf", lambda c: c.startswith(b"%PDF-")),
)

TIPOS_ACEPTADOS = tuple(tipo for tipo, _ in _FORMATOS)


def tipo_por_contenido(contenido: bytes) -> str:
    """El tipo del archivo según sus primeros bytes, o `AdjuntoInvalido` si no es uno de los aceptados."""
    if not contenido:
        raise AdjuntoInvalido("el archivo está vacío")
    if len(contenido) > TAMANIO_MAXIMO:
        raise AdjuntoInvalido(f"el archivo pesa más de {TAMANIO_MAXIMO // (1024 * 1024)} MB")
    cabecera = contenido[:16]
    for tipo, prueba in _FORMATOS:
        if prueba(cabecera):
            return tipo
    raise AdjuntoInvalido("sólo se aceptan fotos (JPG, PNG, WEBP, HEIC) o PDF")


def nombre_seguro(nombre: str | None) -> str:
    """El nombre original, sin rutas ni caracteres que rompan el encabezado de la descarga. Nunca vacío."""
    base = re.split(r"[\\/]", nombre or "")[-1]
    base = re.sub(r'[\x00-\x1f"\\;]', "", base).strip()
    return base[:200] or "adjunto"
