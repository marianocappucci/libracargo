"""Los datos de la empresa: los lee cualquiera, los edita un admin.

**Lectura para todos los usuarios**: el nombre de la empresa se muestra en la
barra lateral y el encabezado va en cada papel que imprime un operador. Si leerlo
exigiera rol admin, la orden de carga saldría sin membrete para quien la imprime.

**Escritura sólo admin**: es la identidad fiscal de la empresa.
"""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.db import obtener_sesion
from app.models.configuracion import ConfiguracionEmpresa
from app.models.enums import AccionAuditoria
from app.servicios import auditoria

router = APIRouter(prefix="/api/configuracion", tags=["configuracion"])

#: Los formatos que un navegador dibuja sin plugins y que entran en un papel.
#: El SVG queda afuera **a propósito**: es ejecutable —lleva scripts— y esto se
#: sirve desde el mismo origen que la aplicación.
TIPOS_DE_LOGO = {"image/png", "image/jpeg", "image/webp"}

#: 2 MB. Un logo de membrete no pesa más, y el límite evita que la fila de
#: configuración se convierta en el archivo más grande de la base.
LOGO_MAXIMO = 2 * 1024 * 1024


class CamposDeConfiguracion(BaseModel):
    """Los campos, **sin reglas**.

    🔴 Segunda vez que aparece lo mismo: `ConfiguracionOut` heredaba de
    `ConfiguracionIn` y con la herencia su `min_length=1` en `razon_social`. Una
    instancia recién entregada no tiene configuración, la respuesta vacía no
    pasaba su propia validación, y `GET /api/configuracion` devolvía 500 — en la
    pantalla que **la barra lateral pide en cada carga**. Es el mismo defecto que
    tenía `OrdenOut` (PR #17): una regla de entrada aplicada a la salida no
    valida, rechaza lo que ya existe.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    razon_social: str = ""
    nombre_fantasia: str | None = Field(default=None, max_length=120)
    cuit: str | None = Field(default=None, max_length=13)
    condicion_iva: str | None = Field(default=None, max_length=60)
    ingresos_brutos: str | None = Field(default=None, max_length=30)
    inicio_actividades: str | None = Field(default=None, max_length=10)
    domicilio: str | None = Field(default=None, max_length=160)
    localidad: str | None = Field(default=None, max_length=80)
    provincia: str | None = Field(default=None, max_length=60)
    codigo_postal: str | None = Field(default=None, max_length=12)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    sitio_web: str | None = Field(default=None, max_length=120)
    pie_de_impresion: str | None = None


class ConfiguracionIn(CamposDeConfiguracion):
    """Lo que se acepta al guardar. Acá sí va la regla."""

    razon_social: str = Field(min_length=1, max_length=120)


class ConfiguracionOut(CamposDeConfiguracion):
    #: El logo **no** viaja en el JSON: se pide aparte por `/logo`, así el
    #: `GET` de la configuración —que la barra lateral hace en cada carga— no
    #: arrastra dos megabytes de imagen.
    tiene_logo: bool = False


def _traer(sesion: Session) -> ConfiguracionEmpresa | None:
    return sesion.get(ConfiguracionEmpresa, 1)


@router.get("", response_model=ConfiguracionOut, dependencies=[Depends(require_staff)])
def ver(sesion: Session = Depends(obtener_sesion)):
    """Devuelve la configuración, y una vacía si todavía no se cargó.

    Un 404 obligaría a cada pantalla a distinguir "no hay configuración" de "no
    se pudo leer", y la barra lateral quedaría rota en una instancia recién
    entregada.
    """
    actual = _traer(sesion)
    if actual is None:
        return ConfiguracionOut(razon_social="")
    return ConfiguracionOut(**CamposDeConfiguracion.model_validate(actual).model_dump(),
                            tiene_logo=actual.logo is not None)


@router.put("", response_model=ConfiguracionOut, dependencies=[Depends(require_admin)])
def guardar(datos: ConfiguracionIn, sesion: Session = Depends(obtener_sesion),
            actual_usuario: dict = Depends(require_admin)):
    actual = _traer(sesion)
    if actual is None:
        actual = ConfiguracionEmpresa(id=1, razon_social=datos.razon_social)
        sesion.add(actual)
        antes, accion = None, AccionAuditoria.ALTA
    else:
        antes, accion = auditoria.instantanea(actual), AccionAuditoria.MODIFICACION
    for campo, valor in datos.model_dump().items():
        setattr(actual, campo, valor)
    auditoria.registrar(sesion, actual_usuario, "configuracion", 1, accion,
                        antes=antes, despues=actual)
    sesion.commit()
    sesion.refresh(actual)
    return ConfiguracionOut(**CamposDeConfiguracion.model_validate(actual).model_dump(),
                            tiene_logo=actual.logo is not None)


@router.get("/logo", dependencies=[Depends(require_staff)])
def logo(sesion: Session = Depends(obtener_sesion)):
    actual = _traer(sesion)
    if actual is None or actual.logo is None:
        raise HTTPException(404, "no hay logo cargado")
    return Response(
        content=actual.logo, media_type=actual.logo_tipo or "application/octet-stream",
        # Se cachea poco: el logo cambia cuando el cliente lo cambia, y una hora
        # de caché haría que el papel siguiera saliendo con el anterior.
        headers={"Cache-Control": "no-cache"})


@router.post("/logo", response_model=ConfiguracionOut, dependencies=[Depends(require_admin)])
async def subir_logo(archivo: UploadFile = File(...),
                     sesion: Session = Depends(obtener_sesion),
                     actual_usuario: dict = Depends(require_admin)):
    """Guarda el logo del membrete.

    🔴 **El tipo se acepta por lista blanca y el SVG queda afuera**: un SVG
    puede llevar scripts, y esto se sirve desde el **mismo origen** que la
    aplicación — o sea con la cookie de sesión al alcance.
    """
    if archivo.content_type not in TIPOS_DE_LOGO:
        raise HTTPException(
            422, f"formato no admitido: {archivo.content_type!r}. PNG, JPG o WebP")
    contenido = await archivo.read()
    if len(contenido) > LOGO_MAXIMO:
        raise HTTPException(422, f"el logo pesa {len(contenido) // 1024} KB y el máximo son 2048")
    if not contenido:
        raise HTTPException(422, "el archivo está vacío")

    actual = _traer(sesion)
    if actual is None:
        raise HTTPException(409, "cargá primero los datos de la empresa")
    actual.logo = contenido
    actual.logo_tipo = archivo.content_type
    actual.logo_nombre = archivo.filename
    auditoria.registrar(sesion, actual_usuario, "configuracion", 1,
                        AccionAuditoria.MODIFICACION,
                        antes={"logo_nombre": None}, despues={"logo_nombre": archivo.filename})
    sesion.commit()
    sesion.refresh(actual)
    return ConfiguracionOut(**CamposDeConfiguracion.model_validate(actual).model_dump(),
                            tiene_logo=True)


@router.delete("/logo", response_model=ConfiguracionOut, dependencies=[Depends(require_admin)])
def borrar_logo(sesion: Session = Depends(obtener_sesion),
                actual_usuario: dict = Depends(require_admin)):
    actual = _traer(sesion)
    if actual is None or actual.logo is None:
        raise HTTPException(404, "no hay logo cargado")
    auditoria.registrar(sesion, actual_usuario, "configuracion", 1,
                        AccionAuditoria.MODIFICACION,
                        antes={"logo_nombre": actual.logo_nombre}, despues={"logo_nombre": None})
    actual.logo = None
    actual.logo_tipo = None
    actual.logo_nombre = None
    sesion.commit()
    sesion.refresh(actual)
    return ConfiguracionOut(**CamposDeConfiguracion.model_validate(actual).model_dump(),
                            tiene_logo=False)
