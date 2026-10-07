"""Quién emite lo que sale en un PDF de LibraCargo: **un solo lugar** (ADR-034).

Todos los PDF del motor —la factura, la nota de crédito, la FCE y la pre factura— arman su membrete con un
`dict` de emisor que sale de `libracore.emisor_del_pdf.emisor_para(documento)`: la configuración global de la
instancia, el nombre y el CUIT del `arca_config` del comprobante, y **el resolvedor que registra el producto**
(libracore ADR-031). Este módulo es ese resolvedor. Lo registra `crear_app` (`registrar()`), y lo usan por
igual el PDF de la pre factura, el de cada comprobante, el que se guarda al emitir y el que va por correo.

## Qué razón social emite

- **Una pre factura** (`numero_interno`): la de `pre_facturas_cargo`.
- **Un comprobante** (una fila de `facturas`): la de `comprobantes_cargo`, que es la que lo emitió. Es la
  fuente exacta: no depende de que el CUIT de la razón social siga siendo el mismo que el del `arca_config`.
- Sin fila propia (algo que el motor guardó por su cuenta), el `emisor_id`: la razón social cuyo CUIT es el
  del `arca_config` con el que se emitió. Si hay dos con el mismo CUIT no se adivina: se queda con lo que dejó
  el motor.

## Lo que sale

`nombre`, `cuit` e `iva_condition` son de la razón social (una instancia puede tener más de una). El domicilio,
los ingresos brutos, el inicio de actividades, el teléfono, el correo y **el logo** salen de los datos de la
empresa de la instancia (`configuracion_empresa`), **sólo si son de esa razón social** —mismo CUIT, o la
empresa no cargó CUIT—: el membrete de otra razón social con el domicilio o el logo equivocado es peor que sin
ellos. El logo viaja como `logo_bytes`: vive en la base, no en el disco del contenedor, que se pierde en cada
despliegue.

🔴 **Lo que levante, sube** (así lo pide el motor): caer al membrete de la instancia ante un error sería
imprimir un comprobante con los datos de otra razón social.
"""

from __future__ import annotations

import re

from libracore import emisor_del_pdf as motor
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models.configuracion import ConfiguracionEmpresa
from app.models.enums import CondicionIVA
from app.models.maestros import RazonSocial
from app.models.operacion import ComprobanteCargo, PreFacturaCargo

#: De quién son las pre facturas en el motor (`servicios.pre_facturas.ORIGEN_PRODUCTO`; se repite acá para
#: no importar ese módulo, que es más grande y depende de éste).
_ORIGEN_PRODUCTO = "libracargo"

#: Cómo se lee la condición de IVA de la razón social en el encabezado del PDF.
CONDICION_IVA = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: "Responsable Inscripto",
    CondicionIVA.MONOTRIBUTO: "Monotributista",
    CondicionIVA.EXENTO: "Exento",
    CondicionIVA.CONSUMIDOR_FINAL: "Consumidor Final",
    CondicionIVA.NO_CATEGORIZADO: "",
}


def _digitos(cuit: str | None) -> str:
    return "".join(c for c in (cuit or "") if c.isdigit())


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


def _razon_de(sesion: Session, documento: dict) -> RazonSocial | None:
    """La razón social que emite este documento, o `None` si no se sabe."""
    if documento.get("numero_interno"):
        # Una pre factura: su `id` es de `comprobantes_pendientes`, no de `facturas`.
        if documento.get("origen_producto") == _ORIGEN_PRODUCTO:
            cargo = sesion.get(PreFacturaCargo, documento["id"])
            if cargo is not None:
                return sesion.get(RazonSocial, cargo.razon_social_id)
    elif documento.get("id") is not None:
        cargo = sesion.get(ComprobanteCargo, documento["id"])
        if cargo is not None:
            return sesion.get(RazonSocial, cargo.razon_social_id)
    emisor_id = documento.get("emisor_id")
    if emisor_id is None:
        return None
    cuit = _digitos(motor.datos_de_arca_config(emisor_id)["cuit"])
    if not cuit:
        return None
    candidatas = [r for r in sesion.scalars(select(RazonSocial)) if _digitos(r.cuit) == cuit]
    return candidatas[0] if len(candidatas) == 1 else None


def emisor_de(sesion: Session, documento: dict) -> dict | None:
    """Los datos del emisor de `documento` (ver el docstring del módulo), o `None` si no hay nada que agregar."""
    razon = _razon_de(sesion, documento)
    if razon is None:
        return None
    emisor = {
        "nombre": razon.nombre, "cuit": razon.cuit or "",
        "iva_condition": CONDICION_IVA[razon.condicion_iva],
    }
    empresa = sesion.get(ConfiguracionEmpresa, 1)
    if empresa is not None and (not _digitos(empresa.cuit) or _digitos(empresa.cuit) == _digitos(razon.cuit)):
        partes = [empresa.domicilio, empresa.localidad, empresa.provincia]
        emisor["direccion"] = ", ".join(p.strip() for p in partes if p and p.strip())
        emisor["iibb"] = empresa.ingresos_brutos or ""
        emisor["inicio_actividades"] = _inicio_para_el_pdf(empresa.inicio_actividades)
        emisor["telefono"] = empresa.telefono or ""
        emisor["email"] = empresa.email or ""
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
