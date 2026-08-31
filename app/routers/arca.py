"""Configuración de ARCA: el certificado y la clave con los que se factura.

**Esto configura; emitir lo hace `app.servicios.emision_arca`.** Una razón
social con el par cargado y `habilitado` emite con CAE y el número se lo da
ARCA; una sin habilitar sigue registrando con el número que tipea una persona.
O sea que lo que se carga acá es exactamente lo que decide cuál de los dos
caminos toma un alta de comprobante.

## Lo que la pantalla contesta y ningún nombre de archivo puede

- si el certificado es realmente un certificado, y no el `.csr` que se le manda
  a ARCA;
- **cuándo vence** — duran dos años y el día que vencen la facturación deja de
  andar sin que nadie haya tocado nada;
- si el certificado y la clave **son pareja**, que es el error de armado que
  se ve perfecto en pantalla y falla recién contra ARCA;
- y —con *Probar conexión*— si ARCA además **lo acepta**: un par impecable al
  que nadie le dio de alta la relación con `wsfe` en el Administrador de
  Relaciones pasa las tres validaciones locales y lo rechaza el organismo.

Todo el router es de administrador: acá se sube una clave privada.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from libracore import arca_wsaa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import obtener_sesion
from app.models.configuracion_arca import ConfiguracionArca
from app.models.enums import AccionAuditoria, AmbienteArca
from app.models.maestros import RazonSocial
from app.schemas.arca import ArcaIn, ArcaOut, CertificadoOut, PruebaArcaOut
from app.servicios import auditoria
from app.servicios.arca import ArchivoInvalido, leer_certificado, leer_clave, son_pareja

router = APIRouter(prefix="/api/arca", tags=["arca"], dependencies=[Depends(require_admin)])

#: Un certificado de ARCA son un par de KB. El tope está para que un archivo
#: equivocado —un PDF, un ZIP— se rechace por tamaño antes de intentar parsearlo.
MAXIMO = 64 * 1024

#: El webservice contra el que prueba *Probar conexión*.
#:
#: 🔑 Es **el mismo que usa la emisión** (`emision_arca`, que autentica con
#: `servicio="wsfe"` por defecto). Probar contra otro servicio diría que el
#: certificado está bien y dejaría afuera justo la relación que hace falta para
#: facturar, que es la que falta casi siempre.
SERVICIO = "wsfe"


def _razon_social(sesion: Session, razon_social_id: int) -> RazonSocial:
    rs = sesion.get(RazonSocial, razon_social_id)
    if rs is None:
        raise HTTPException(404, f"no existe la razón social {razon_social_id}")
    return rs


def _config(sesion: Session, razon_social_id: int) -> ConfiguracionArca:
    """La configuración de esa razón social, creándola vacía si no existe.

    Se crea al primer uso y no en una migración: una fila por razón social
    creada de antemano obligaría a mantenerlas sincronizadas cada vez que se da
    de alta una razón social nueva.
    """
    _razon_social(sesion, razon_social_id)
    cfg = sesion.scalar(
        select(ConfiguracionArca).where(ConfiguracionArca.razon_social_id == razon_social_id)
    )
    if cfg is None:
        cfg = ConfiguracionArca(razon_social_id=razon_social_id)
        sesion.add(cfg)
        sesion.flush()
    return cfg


def _a_salida(sesion: Session, cfg: ConfiguracionArca) -> ArcaOut:
    rs = _razon_social(sesion, cfg.razon_social_id)
    certificado = None
    if cfg.certificado is not None:
        try:
            datos = leer_certificado(cfg.certificado)
            certificado = CertificadoOut(
                nombre=cfg.certificado_nombre, sujeto=datos.sujeto, emisor=datos.emisor,
                vence=datos.vence, vencido=datos.vencido,
                dias_para_vencer=datos.dias_para_vencer,
            )
        except ArchivoInvalido:
            # Guardado por una versión anterior, o el archivo se corrompió en el
            # camino. Se informa que hay algo y que no se puede leer, en vez de
            # romper la pantalla entera de configuración.
            certificado = CertificadoOut(
                nombre=cfg.certificado_nombre, sujeto="(ilegible)", emisor="(ilegible)",
                vence=None, vencido=True, dias_para_vencer=0,
            )
    coinciden = None
    if cfg.certificado is not None and cfg.clave is not None:
        try:
            coinciden = son_pareja(cfg.certificado, cfg.clave)
        except ArchivoInvalido:
            coinciden = False
    # 🔑 `cfg` puede ser una fila que NO esta en la base: `listar` arma una al
    # vuelo para las razones sociales sin configurar. Los `default=` de
    # SQLAlchemy se aplican al INSERT, no al construir el objeto, asi que ahi
    # `ambiente` y `habilitado` valen None y hay que darles su valor de origen.
    return ArcaOut(
        razon_social_id=cfg.razon_social_id, razon_social=rs.nombre,
        cuit=rs.cuit, punto_venta=rs.punto_venta,
        ambiente=cfg.ambiente or AmbienteArca.HOMOLOGACION,
        habilitado=bool(cfg.habilitado),
        certificado=certificado, tiene_clave=cfg.clave is not None,
        clave_nombre=cfg.clave_nombre, coinciden=coinciden,
    )


@router.get("", response_model=list[ArcaOut])
def listar(sesion: Session = Depends(obtener_sesion)):
    """Una fila por razón social **activa**, tenga configuración o no.

    Las que no la tienen aparecen vacías y no ausentes: es la lista de lo que
    hay que configurar, no la de lo que ya se configuró.
    """
    razones = list(sesion.scalars(
        select(RazonSocial).where(RazonSocial.activa.is_(True)).order_by(RazonSocial.nombre)
    ))
    salida = []
    for rs in razones:
        cfg = sesion.scalar(
            select(ConfiguracionArca).where(ConfiguracionArca.razon_social_id == rs.id)
        )
        salida.append(_a_salida(sesion, cfg or ConfiguracionArca(razon_social_id=rs.id)))
    return salida


@router.put("/{razon_social_id}", response_model=ArcaOut)
def guardar(razon_social_id: int, datos: ArcaIn,
            sesion: Session = Depends(obtener_sesion),
            actual: dict = Depends(require_admin)):
    cfg = _config(sesion, razon_social_id)
    if datos.habilitado and (cfg.certificado is None or cfg.clave is None):
        raise HTTPException(
            422, "para habilitar la facturación hay que subir el certificado y la clave")
    antes = {"ambiente": cfg.ambiente.value, "habilitado": cfg.habilitado}
    cfg.ambiente = datos.ambiente
    cfg.habilitado = datos.habilitado
    auditoria.registrar(sesion, actual, "configuracion_arca", cfg.razon_social_id,
                        AccionAuditoria.MODIFICACION, antes=antes,
                        despues={"ambiente": cfg.ambiente.value, "habilitado": cfg.habilitado})
    sesion.commit()
    sesion.refresh(cfg)
    return _a_salida(sesion, cfg)


async def _leer_subida(archivo: UploadFile) -> bytes:
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(422, "el archivo está vacío")
    if len(contenido) > MAXIMO:
        raise HTTPException(
            422, f"el archivo pesa {len(contenido) // 1024} KB; un certificado son unos pocos")
    return contenido


@router.post("/{razon_social_id}/certificado", response_model=ArcaOut)
async def subir_certificado(razon_social_id: int, archivo: UploadFile = File(...),
                            sesion: Session = Depends(obtener_sesion),
                            actual: dict = Depends(require_admin)):
    contenido = await _leer_subida(archivo)
    try:
        leer_certificado(contenido)
    except ArchivoInvalido as err:
        raise HTTPException(422, str(err)) from None
    cfg = _config(sesion, razon_social_id)
    cfg.certificado = contenido
    cfg.certificado_nombre = archivo.filename
    # 🔴 Cambiar el certificado puede romper la pareja con la clave que ya
    # estaba. Se deshabilita hasta que alguien vuelva a decir que sí, en vez de
    # dejar una instancia "habilitada" con credenciales que no se autentican.
    cfg.habilitado = False
    auditoria.registrar(sesion, actual, "configuracion_arca", razon_social_id,
                        AccionAuditoria.MODIFICACION,
                        despues={"certificado_nombre": archivo.filename})
    sesion.commit()
    sesion.refresh(cfg)
    return _a_salida(sesion, cfg)


@router.post("/{razon_social_id}/clave", response_model=ArcaOut)
async def subir_clave(razon_social_id: int, archivo: UploadFile = File(...),
                      sesion: Session = Depends(obtener_sesion),
                      actual: dict = Depends(require_admin)):
    contenido = await _leer_subida(archivo)
    try:
        leer_clave(contenido)
    except ArchivoInvalido as err:
        raise HTTPException(422, str(err)) from None
    cfg = _config(sesion, razon_social_id)
    cfg.clave = contenido
    cfg.clave_nombre = archivo.filename
    cfg.habilitado = False
    auditoria.registrar(sesion, actual, "configuracion_arca", razon_social_id,
                        AccionAuditoria.MODIFICACION,
                        # El nombre del archivo, nunca el contenido: esto queda
                        # escrito en el log de actividad, que se puede imprimir.
                        despues={"clave_nombre": archivo.filename})
    sesion.commit()
    sesion.refresh(cfg)
    return _a_salida(sesion, cfg)


@router.delete("/{razon_social_id}/credenciales", response_model=ArcaOut)
def borrar_credenciales(razon_social_id: int, sesion: Session = Depends(obtener_sesion),
                        actual: dict = Depends(require_admin)):
    """Saca las dos mitades juntas.

    De a una no: media credencial no sirve para nada y deja la pantalla
    diciendo que falta algo que en realidad hay que volver a subir entero.
    """
    cfg = _config(sesion, razon_social_id)
    cfg.certificado = cfg.certificado_nombre = None
    cfg.clave = cfg.clave_nombre = None
    cfg.habilitado = False
    auditoria.registrar(sesion, actual, "configuracion_arca", razon_social_id,
                        AccionAuditoria.BAJA, despues={"credenciales": "borradas"})
    sesion.commit()
    sesion.refresh(cfg)
    return _a_salida(sesion, cfg)


@router.post("/{razon_social_id}/probar", response_model=PruebaArcaOut)
async def probar(razon_social_id: int, sesion: Session = Depends(obtener_sesion)):
    """Autentica de verdad contra WSAA con el par de esta razón social.

    🔑 **Es el único chequeo que dice que ARCA acepta el certificado.** Leer los
    archivos contesta que están bien armados —que parsean, que no vencieron, que
    son pareja— y las tres cosas pueden ser ciertas con un certificado que ARCA
    rechaza: el alta de la relación con `wsfe` en el Administrador de Relaciones
    es un trámite aparte, en el portal, y no deja ninguna marca en el archivo.

    Sin este botón esa diferencia recién aparecía **al emitir el primer
    comprobante**, con el texto de ARCA saliendo por el alta de un comprobante
    que además queda sin hacerse.

    No escribe nada: no crea la fila de configuración si no existe, no toca
    `habilitado` y no queda en el log de actividad — probar es una consulta.
    """
    rs = _razon_social(sesion, razon_social_id)
    cfg = sesion.scalar(
        select(ConfiguracionArca).where(ConfiguracionArca.razon_social_id == razon_social_id)
    )
    if cfg is None or cfg.certificado is None or cfg.clave is None:
        raise HTTPException(
            400, "faltan el certificado o la clave: subí las dos mitades antes de probar")
    try:
        pareja = son_pareja(cfg.certificado, cfg.clave)
    except ArchivoInvalido as err:
        raise HTTPException(400, str(err)) from None
    if not pareja:
        # Se corta acá y no se sale a la red: el par no coincide, así que el
        # rechazo de ARCA sería seguro y su texto hablaría de la firma, no de
        # la causa. La pantalla ya lo dice; el botón tiene que decir lo mismo.
        raise HTTPException(
            400, "el certificado y la clave no son pareja: ARCA va a rechazar la firma")

    ambiente = cfg.ambiente or AmbienteArca.HOMOLOGACION
    try:
        ticket = await arca_wsaa.autenticar_con_bytes(
            cfg.certificado, cfg.clave, ambiente.value, SERVICIO)
    except Exception as e:
        # El texto de ARCA va tal cual, igual que en la emisión: distingue "el
        # certificado no está habilitado para wsfe" de "la hora del servidor
        # está corrida", y las dos se arreglan en lugares distintos.
        raise HTTPException(502, f"ARCA rechazó la autenticación: {e}") from None

    return PruebaArcaOut(
        ok=True, ambiente=ambiente, cuit=rs.cuit, servicio=SERVICIO,
        # `.get`: lo que interesa del ticket es que lo haya dado. Si ARCA no
        # mandó el vencimiento, el aviso se muestra igual sin esa parte.
        expira=ticket.get("expiracion") or None,
    )
