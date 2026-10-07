"""Quién emite lo que sale en un PDF de LibraCargo: **la empresa**, para todo documento (ADR-034, ADR-035).

Todos los PDF del motor —la factura, la nota de crédito, la FCE y la pre factura— arman su membrete con un
`dict` de emisor que sale de `libracore.emisor_del_pdf.emisor_para(documento)`: la configuración global de la
instancia, el nombre y el CUIT del `arca_config` del comprobante, y **el resolvedor que registra el producto**
(libracore ADR-031). Este módulo es ese resolvedor. Lo registra `crear_app` (`registrar()`), y lo usan por
igual el PDF de la pre factura, el de cada comprobante, el que se guarda al emitir y el que va por correo.

## Qué sale

Desde ADR-035 el emisor es **uno solo**: «Datos de la empresa» (`configuracion_empresa`). Antes había que
elegir entre varias razones sociales, y el domicilio y el logo salían sólo si el CUIT de la empresa coincidía
con el de la razón social elegida; sin esa regla —no hay otra razón social con la que confundirse— el logo y
el domicilio salen **siempre**.

`nombre` es la razón social de la empresa; `cuit` e `iva_condition`, los suyos; el domicilio, los ingresos
brutos, el inicio de actividades, el teléfono, el correo y **el logo**, los de la misma ficha. El logo viaja
como `logo_bytes`: vive en la base, no en el disco del contenedor, que se pierde en cada despliegue.

Si la instancia todavía no cargó la empresa devuelve `None`, y el motor cae a su membrete por defecto.

🔴 **Lo que levante, sube** (así lo pide el motor): caer al membrete de la instancia ante un error sería
imprimir un comprobante con datos que no son los del emisor.
"""

from __future__ import annotations

import re

from libracore import emisor_del_pdf as motor
from sqlalchemy.orm import Session

from app import db
from app.models.configuracion import ConfiguracionEmpresa
from app.models.enums import CondicionIVA

#: Cómo se lee la condición de IVA de la empresa en el encabezado del PDF.
CONDICION_IVA = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: "Responsable Inscripto",
    CondicionIVA.MONOTRIBUTO: "Monotributista",
    CondicionIVA.EXENTO: "Exento",
    CondicionIVA.CONSUMIDOR_FINAL: "Consumidor Final",
    CondicionIVA.NO_CATEGORIZADO: "",
}


def _inicio_para_el_pdf(texto: str | None) -> str:
    """El inicio de actividades como lo dibuja el motor: **ISO** (`2020-01-31`), que él pasa a `31-01-2020`.

    En «Datos de la empresa» es un texto libre, y quien lo carga escribe `31/01/2020`: el motor le leería las
    posiciones fijas y el comprobante diría `20-/1-31/0`. Se acepta `d/m/aaaa` y `d-m-aaaa`; lo que no se
    entiende se deja vacío, que es mejor que un dato mal impreso en un papel fiscal.
    """
    texto = (texto or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return texto
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", texto):
        dia, mes, anio = m.groups()
        return f"{anio}-{int(mes):02d}-{int(dia):02d}"
    return ""


def emisor_de(sesion: Session, documento: dict | None = None) -> dict | None:
    """Los datos del emisor: los de la empresa, sea cual sea el documento (ver el docstring del módulo).

    `documento` no se mira: hay un solo emisor. Se acepta porque es la forma del resolvedor del motor.
    """
    empresa = sesion.get(ConfiguracionEmpresa, 1)
    if empresa is None:
        return None
    partes = [empresa.domicilio, empresa.localidad, empresa.provincia]
    emisor = {
        "nombre": empresa.razon_social, "cuit": empresa.cuit or "",
        "iva_condition": CONDICION_IVA.get(empresa.condicion_iva, ""),
        "direccion": ", ".join(p.strip() for p in partes if p and p.strip()),
        "iibb": empresa.ingresos_brutos or "",
        "inicio_actividades": _inicio_para_el_pdf(empresa.inicio_actividades),
        "telefono": empresa.telefono or "",
        "email": empresa.email or "",
    }
    if empresa.logo:
        emisor["logo_bytes"] = bytes(empresa.logo)
    return emisor


def resolvedor(documento: dict) -> dict | None:
    """El resolvedor que se registra en el motor: abre su propia sesión, porque el motor lo llama sin la del pedido."""
    with db.fabrica_de_sesiones()() as sesion:
        return emisor_de(sesion, documento)


def registrar() -> None:
    """Lo registra para todos los PDF del proceso. Lo llama `crear_app`; registrar de nuevo reemplaza al anterior."""
    motor.registrar_resolvedor(resolvedor)
