"""«Sólo los dígitos del CUIT» es del motor: este producto no tiene su copia.

Hubo cinco helpers casi idénticos (`"".join(c for c in (cuit or "") if c.isdigit())`) en
`emision_arca`, `pre_facturas`, `routers/maestros`, `cartas_porte` y `routers/comprobantes`, más dos
validadores de los esquemas. La regla es `libracore.cuit.solo_digitos` (la misma que usa
`arca_wsfe.cuit_del_receptor` y, con ella, la guarda `problema_del_receptor`): si un producto escribe la
suya, la próxima vez que el motor cambie la regla (qué se considera «un CUIT cargado») la pantalla y la
emisión dejan de coincidir.
"""

import re
from pathlib import Path

import pytest
from libracore.cuit import solo_digitos

from app.routers import maestros
from app.servicios import cartas_porte, emision_arca, pre_facturas

RAIZ_APP = Path(__file__).resolve().parent.parent / "app"

#: El patrón de la copia: un `join` de caracteres filtrados por `isdigit()`.
COPIA = re.compile(r"join\(\s*\w+\s+for\s+\w+\s+in\b[^\n]*\bif\s+\w+\.isdigit\(\)")


@pytest.mark.parametrize("modulo, nombre", [
    (emision_arca, "_solo_digitos"),
    (pre_facturas, "_digitos"),
    (maestros, "_digitos"),
    (cartas_porte, "digitos"),
])
def test_no_vuelve_un_helper_propio_de_solo_digitos(modulo, nombre):
    assert not hasattr(modulo, nombre), f"{modulo.__name__}.{nombre}: una copia propia; usar el del motor"


def test_ningun_archivo_de_la_app_filtra_los_digitos_por_su_cuenta():
    copias = [
        f"{ruta.relative_to(RAIZ_APP.parent)}:{n}"
        for ruta in sorted(RAIZ_APP.rglob("*.py"))
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1)
        if COPIA.search(linea)
    ]
    assert not copias, f"copias de «sólo los dígitos»: {copias}; usar libracore.cuit.solo_digitos"


def test_ningun_archivo_de_la_app_envuelve_el_cuit_en_un_dict_de_factura():
    """`cuit_del_receptor` es de la factura; para un CUIT suelto está `solo_digitos`."""
    envueltos = [
        f"{ruta.relative_to(RAIZ_APP.parent)}:{n}"
        for ruta in sorted(RAIZ_APP.rglob("*.py"))
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1)
        if 'cuit_del_receptor({"cliente_cuit"' in linea
    ]
    assert not envueltos, f"usar libracore.cuit.solo_digitos(valor): {envueltos}"


@pytest.mark.parametrize("crudo, esperado", [
    (None, ""),
    ("", ""),
    ("   ", ""),
    ("20-12345678-6", "20123456786"),
    ("20 12345678 6", "20123456786"),
    ("30.70933285.2", "30709332852"),
    ("20123456786", "20123456786"),
    ("sin cuit", ""),
])
def test_el_motor_quita_todo_lo_que_no_es_digito(crudo, esperado):
    assert solo_digitos(crudo) == esperado
