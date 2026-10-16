"""La empresa ficticia de la demo pública (ADR-038 y ADR-061 de libracore).

En una demo (`DEMO_MODE=1`) el motor nunca muestra los datos de la empresa que
haya en `config.json`, en `arca_config` ni en el resolvedor del producto: el
emisor de un PDF es esta empresa y nada más. Es ficticia de punta a punta —CUIT
con dígito verificador válido y cuerpo `99999xxx`, que ARCA no asigna, correo en
`.example`— y es **la misma** que `scripts/seed_demo.py` guarda en «Datos de la
empresa», para que la pantalla y el PDF digan lo mismo. Sin ella el PDF de la
demo sale con «Empresa Demo SRL», la empresa genérica del motor.

Sin logo: el de «Datos de la empresa» vive en la base, que en una demo no se lee
para el emisor (ADR-061), y esta demo no trae uno propio en la imagen.

Fuera de una demo, registrar no cambia nada.
"""
from libracore import config_manager

EMPRESA = {
    "empresa_nombre":             "Transportes del Plata Demo SRL",
    "empresa_cuit":               "30-99999903-0",
    "empresa_direccion":          "Av. Demo 1234, Rosario, Santa Fe",
    "empresa_telefono":           "0341 400-0000",
    "empresa_email":              "administracion@transportesdelplata.example",
    "empresa_iibb":               "901-000000-3",
    "empresa_iva_condition":      "Responsable Inscripto",
    "empresa_inicio_actividades": "2016-04-01",
}


def registrar() -> None:
    """Idempotente: se puede llamar en cada arranque."""
    config_manager.usar_empresa_demo(EMPRESA)
