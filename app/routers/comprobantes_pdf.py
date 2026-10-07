"""El PDF de los comprobantes y su envío por correo (ADR-034).

Es `build_comprobantes_pdf_router` de LibraCore (ADR-031 de allá), montado con el gate y el SMTP de este
producto: **el mismo router y el mismo generador que usa toda la familia**, no un PDF propio.

- `GET /api/comprobantes/{id}/pdf`: el PDF, en línea.
- `POST /api/comprobantes/{id}/enviar-email`, `{"email": ...}`: el mismo PDF por correo.

El prefijo es el de los comprobantes y no `/api/facturas`: es el que ya usa la pantalla, y no choca con nada de
`routers/comprobantes.py` (ahí no hay `/{id}/pdf` ni `/{id}/enviar-email`).

**Qué comprobantes se ven** (`puede_ver`): los de LibraCargo —los que tienen su fila en `comprobantes_cargo`—,
**con CAE** y que no sean de homologación. Cualquier otro es un 404, el mismo de un id que no existe.

- Sin CAE (lo registrado a mano y lo migrado del legado) ARCA no lo conoce: un PDF con el formato de una
  factura, sin CAE ni QR, se podría mandar a un cliente como si lo fuera. No se ofrece.
- De homologación no queda ninguno (el ensayo se revierte entero, ver `servicios.pre_facturas.facturar`), pero
  si apareciera uno —un dato cargado por fuera— tampoco se imprime: tendría un CAE que no vale.

El emisor (razón social, domicilio y logo) lo pone el resolvedor registrado (`servicios/emisor_del_pdf.py`).
El PDF que se sirve es el que se guardó al emitir (`facturas.pdf_path`); sólo si falta se arma de nuevo.

🔴 **El motor lo lee con `db_facturas.get_factura`, o sea por la base de LibraCore**, que desde la etapa 3 es
la del dominio.
"""

from fastapi import APIRouter
from libraauth.smtp_settings import resolver_smtp_config
from libracore.facturas_router import build_comprobantes_pdf_router

from app import db
from app.auth import get_current_user
from app.models.operacion import ComprobanteCargo

PREFIJO = "/api/comprobantes"


def puede_ver(factura: dict) -> bool:
    """Si este comprobante es uno de los que este producto imprime. Ver el docstring del módulo."""
    if not factura.get("cae") or factura.get("ambiente") == "homologacion":
        return False
    with db.fabrica_de_sesiones()() as sesion:
        return sesion.get(ComprobanteCargo, factura["id"]) is not None


def construir_router() -> APIRouter:
    """Se construye al armar la app: lee el SMTP en cada envío, no al importar."""
    return build_comprobantes_pdf_router(
        usuario_actual=get_current_user,
        prefix=PREFIJO,
        puede_ver=puede_ver,
        # CALLABLE, como el de la pre factura y el de recuperación de contraseña: se resuelve en cada envío,
        # así guardar el SMTP por pantalla tiene efecto sin reiniciar.
        smtp_config=lambda: resolver_smtp_config(db.fabrica_de_sesiones()),
        donde_configurar_smtp="Configuración → Email",
    )
