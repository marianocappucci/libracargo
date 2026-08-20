"""La aplicación instalable: el manifest, los iconos y el service worker.

**Por qué existe.** El frontend se sirve desde el mismo proceso que la API, con
un catch-all que devuelve `index.html` para cualquier ruta que no sea `/assets`.
Ese catch-all **no falla**: contesta 200. Así que un `/manifest.webmanifest` que
no se sirva no da 404 ni error de consola — da 200 con HTML adentro, el
navegador lo descarta en silencio y la aplicación simplemente no aparece como
instalable. No hay nada que mirar para darse cuenta.

Lo que le toca a `app/spa.py` —qué se sirve y qué cae en el index— ya está en
`test_spa.py`, sobre la función pura. Acá se afirma **lo que hay en el
repositorio**: que el manifest declare lo mínimo, que los iconos existan y midan
lo que dicen, que el `index.html` los enganche, y que el de iOS sea opaco.
"""

import json
import struct
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PUBLICO = RAIZ / "frontend" / "public"
MANIFEST = PUBLICO / "manifest.webmanifest"
INDEX = RAIZ / "frontend" / "index.html"


def _medidas_png(archivo: Path) -> tuple[int, int]:
    """Ancho y alto leídos del IHDR, sin depender de ninguna librería de imagen."""
    crudo = archivo.read_bytes()
    assert crudo[:8] == b"\x89PNG\r\n\x1a\n", f"{archivo.name} no es un PNG"
    ancho, alto = struct.unpack(">II", crudo[16:24])
    return ancho, alto


def test_el_manifest_declara_lo_minimo_para_instalarse():
    datos = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert datos["name"] == "LibraCargo"
    assert datos["start_url"] == "/"
    assert datos["scope"] == "/"
    assert datos["display"] == "standalone"
    assert datos["theme_color"].startswith("#") and len(datos["theme_color"]) == 7


def test_los_iconos_del_manifest_existen_y_miden_lo_que_dicen():
    """Un manifest que apunta a un icono que no está deja de ser instalable, y
    el navegador no dice cuál falta: dice que no encontró ninguno del tamaño
    que necesita."""
    datos = json.loads(MANIFEST.read_text(encoding="utf-8"))
    medidas = {"192x192", "512x512"}

    for icono in datos["icons"]:
        archivo = PUBLICO / icono["src"].lstrip("/")
        assert archivo.is_file(), f"{icono['src']} está en el manifest y no en el disco"
        ancho, alto = _medidas_png(archivo)
        assert f"{ancho}x{alto}" == icono["sizes"], f"{icono['src']} mide {ancho}x{alto}"

    declarados = {i["sizes"] for i in datos["icons"]}
    assert medidas <= declarados, f"faltan tamaños: {medidas - declarados}"

    # Chrome pide uno **maskable** para no dibujar el icono adentro de una
    # cápsula blanca en Android.
    assert any(i.get("purpose") == "maskable" for i in datos["icons"])


def test_el_index_engancha_el_manifest_y_el_color():
    """El manifest puede estar impecable y no servir de nada: si el `index.html`
    no lo enlaza, el navegador nunca lo pide."""
    html = INDEX.read_text(encoding="utf-8")
    datos = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert '<link rel="manifest" href="/manifest.webmanifest" />' in html
    assert f'<meta name="theme-color" content="{datos["theme_color"]}" />' in html, (
        "el color de la barra del navegador y el del manifest tienen que ser el mismo"
    )


def test_el_service_worker_no_cachea():
    """🔴 Es una decisión, no un olvido, y hay que poder verla.

    Un caché acá dejaría a un usuario con el bundle de anteayer contra una API
    nueva, sin manera de enterarse — el frontend se reemplaza entero en cada
    deploy. El service worker existe **sólo** para que el navegador ofrezca
    instalar la aplicación.
    """
    sw = (PUBLICO / "sw.js").read_text(encoding="utf-8")
    # Sin los comentarios: la explicación de por qué no se cachea nombra
    # justamente lo que está prohibido, y buscar sobre el archivo entero deja el
    # guard en rojo por su propia documentación.
    codigo = " ".join(l for l in sw.splitlines() if not l.lstrip().startswith("//"))

    assert "addEventListener('fetch'" in codigo, "sin manejador de fetch no es instalable"
    for prohibido in ("caches.open", "cache.put", "cache.addAll", "respondWith"):
        assert prohibido not in codigo, f"el service worker no tiene que cachear: apareció {prohibido}"


def test_el_icono_de_ios_no_tiene_transparencia():
    """🔴 El defecto no es que falte el archivo: es que tenga canal alfa.

    iOS no compone «Agregar a inicio» sobre ningún fondo — pinta la
    transparencia de **negro**. Con un icono de fondo transparente, las esquinas
    redondeadas del recuadro salen oscuras. Un test que sólo mirara que el
    archivo existe pasaba en verde con el defecto entero.

    Se lee el tipo de color del IHDR, que es el byte 26 del PNG: 2 es color sin
    alfa, 6 es color con alfa. Y se descarta `tRNS`, que es la otra forma de
    declarar transparencia.
    """
    icono = PUBLICO / "icons" / "icon-apple-180.png"
    assert icono.is_file(), "falta el icono de iOS"

    crudo = icono.read_bytes()
    assert crudo[:8] == b"\x89PNG\r\n\x1a\n"
    assert crudo[25] == 2, f"tipo de color {crudo[25]}: el PNG lleva canal alfa"
    assert b"tRNS" not in crudo, "el PNG declara transparencia por tRNS"
    assert _medidas_png(icono) == (180, 180)


def test_el_index_apunta_al_icono_opaco():
    """El archivo opaco no sirve de nada si el `<link>` sigue en el otro."""
    html = INDEX.read_text(encoding="utf-8")

    assert 'rel="apple-touch-icon"' in html
    assert 'href="/icons/icon-apple-180.png"' in html, (
        "el apple-touch-icon sigue apuntando a un icono con transparencia"
    )


def test_los_iconos_transparentes_SI_tienen_alfa():
    """El control positivo del test de iOS.

    Sin esto, `test_el_icono_de_ios_no_tiene_transparencia` pasaría en verde si
    alguien aplanara **todos** los iconos contra un fondo: el de iOS seguiría
    opaco, que es lo que ese test mira, y los otros dos perderían la
    transparencia que sí necesitan para el lanzador de escritorio.
    """
    for nombre in ("icon-192.png", "icon-512.png"):
        crudo = (PUBLICO / "icons" / nombre).read_bytes()
        assert crudo[25] == 6, f"{nombre} tendría que tener canal alfa (IHDR {crudo[25]})"
