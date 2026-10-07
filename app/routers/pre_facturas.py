"""Pre facturas: el documento que se manda al cliente antes de facturar (ADR-032).

El **ciclo, el PDF, el correo y la numeración** (`PF-0001`) son del motor: `build_pre_facturas_router` de
LibraCore (ADR-030 de allá), montado con el gate de auth y el SMTP de este producto. Lo que cambia acá es
que **las pre facturas se arman desde órdenes**: el motor las crea desde ítems tipeados, y una pre factura
de LibraCargo con ítems que no son de ninguna orden no se podría facturar. Por eso el router del motor
llega **sin** `POST /` y `PUT /{id}` (que ve el ítem como dato) y **sin** `GET /` y `GET /{id}` (que no
conocen la razón social ni las órdenes); acá van las propias, en los mismos caminos:

- `POST /api/pre-facturas`: genera la pre factura de unas órdenes del cliente y las reserva.
- `PUT /api/pre-facturas/{id}`: cambia razón social, tipo, fecha y órdenes.
- `POST /api/pre-facturas/{id}/facturar`: la emite por ARCA y la cierra.
- `GET /api/pre-facturas` y `GET /api/pre-facturas/{id}`: lo del motor, más la razón social y las órdenes.

Del motor quedan tal cual `GET /{id}/pdf`, `POST /{id}/enviar-email`, `POST /{id}/aceptar` y
`POST /{id}/anular` (que libera las órdenes por el gancho `al_anular`). El emisor de los PDF (razón social,
domicilio y logo) lo pone el resolvedor único del producto (`servicios/emisor_del_pdf.py`, ADR-034), que
registra `crear_app` para todos los PDF: este router ya no pasa uno propio.

🔴 **`def` y no `async def`, a propósito**, como `comprobantes.facturar` hasta ahora: la `Session` y
`openssl` son sincrónicos y bloquearían el loop de uvicorn, que corre con un solo proceso.
"""

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from libraauth.smtp_settings import resolver_smtp_config
from libracore import pre_facturas as dominio
from libracore.pre_facturas_router import build_pre_facturas_router
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db
from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.routers.maestros import traducir_integridad
from app.schemas.comprobantes import ComprobanteOut
from app.schemas.pre_facturas import FacturarPreFacturaIn, PreFacturaEditarIn, PreFacturaIn
from app.servicios import comprobantes
from app.servicios import pre_facturas as servicio
from app.servicios.comprobantes import _conexion_del_motor

PREFIJO = "/api/pre-facturas"


def _usuario(request: Request) -> str:
    """Con qué nombre se asienta quién aceptó o anuló: el del usuario de la sesión."""
    return get_current_user(request, request.app.state.session_auth)["username"]


def _traducir(e: servicio.Rechazo) -> HTTPException:
    return HTTPException(e.status, e.detalle)


def construir_router():
    """El router de pre facturas de este producto. Se construye al armar la app (lee el SMTP en cada envío)."""
    router = build_pre_facturas_router(
        origen_producto=servicio.ORIGEN_PRODUCTO, origen_instancia=servicio.ORIGEN_INSTANCIA,
        usuario_actual=_usuario,
        # CALLABLE, como el del restablecimiento de contraseña: se resuelve en cada envío, así guardar el
        # SMTP por pantalla tiene efecto sin reiniciar. Es el mismo que usan la prueba de SMTP y el correo
        # de recuperación.
        smtp_resolver=lambda: resolver_smtp_config(db.fabrica_de_sesiones()),
        al_anular=servicio.liberar,
        donde_configurar_smtp="Configuración → Email",
        dependencies=[Depends(require_staff)],
        prefix=PREFIJO,
    )
    # Las rutas del motor que se reemplazan acá (ver el docstring del módulo).
    reemplazadas = {("GET", PREFIJO), ("POST", PREFIJO), ("GET", PREFIJO + "/{pre_factura_id}"),
                    ("PUT", PREFIJO + "/{pre_factura_id}")}
    router.routes[:] = [
        r for r in router.routes
        if not any((m, r.path) in reemplazadas for m in getattr(r, "methods", ()))
    ]

    def _filas(sesion: Session, filas: list[dict]) -> list[dict]:
        return servicio.enriquecer(sesion, filas)

    @router.get("")
    def listar(estado: str = "", cliente: str = "", cliente_id: int | None = None,
               limite: int = 500, sesion: Session = Depends(obtener_sesion)):
        if estado and estado not in dominio.ESTADOS:
            raise HTTPException(422, f"Estado inválido: {estado!r}.")
        conn = _conexion_del_motor(sesion)
        propio = dict(origen_producto=servicio.ORIGEN_PRODUCTO, origen_instancia=servicio.ORIGEN_INSTANCIA)
        filas = _filas(sesion, dominio.listar(estado=estado or None, cliente=cliente, conn=conn, **propio))
        if cliente_id is not None:
            # El tercero no está en la bandeja del motor (su `cliente_id` apunta a `clients`): sale de lo propio.
            filas = [f for f in filas if f["cliente_id"] == cliente_id]
        return {"items": filas[:limite], "counts": dominio.contar_por_estado(conn=conn, **propio)}

    @router.get("/{pre_factura_id}")
    def detalle(pre_factura_id: int, sesion: Session = Depends(obtener_sesion)):
        try:
            return _filas(sesion, [servicio.pre_factura_de(sesion, pre_factura_id)])[0]
        except servicio.Rechazo as e:
            raise _traducir(e) from None

    @router.post("", status_code=201)
    def crear(datos: PreFacturaIn, sesion: Session = Depends(obtener_sesion),
              actual: dict = Depends(get_current_user)):
        """Genera la pre factura de las órdenes del cliente y las reserva, en una sola transacción."""
        try:
            pf = servicio.crear(
                sesion, actual, cliente_id=datos.cliente_id, razon_social_id=datos.razon_social_id,
                tipo=datos.tipo, fecha=datos.fecha, vencimiento=datos.fecha_vencimiento_pago,
                orden_ids=datos.orden_ids, observaciones=datos.observaciones)
            sesion.commit()
        except servicio.Rechazo as e:
            sesion.rollback()
            raise _traducir(e) from None
        except IntegrityError as err:
            sesion.rollback()
            raise traducir_integridad(err) from None
        return _filas(sesion, [pf])[0]

    @router.put("/{pre_factura_id}")
    def editar(pre_factura_id: int, datos: PreFacturaEditarIn, sesion: Session = Depends(obtener_sesion),
               actual: dict = Depends(get_current_user)):
        """Cambia razón social, tipo, fecha y órdenes. Una enviada o aceptada vuelve a pendiente."""
        try:
            pf = servicio.editar(
                sesion, actual, pre_factura_id, razon_social_id=datos.razon_social_id, tipo=datos.tipo,
                fecha=datos.fecha, vencimiento=datos.fecha_vencimiento_pago, orden_ids=datos.orden_ids,
                observaciones=datos.observaciones)
            sesion.commit()
        except servicio.Rechazo as e:
            sesion.rollback()
            raise _traducir(e) from None
        except IntegrityError as err:
            sesion.rollback()
            raise traducir_integridad(err) from None
        return _filas(sesion, [pf])[0]

    @router.post("/{pre_factura_id}/facturar", response_model=ComprobanteOut, status_code=201)
    def facturar(pre_factura_id: int, datos: FacturarPreFacturaIn | None = None,
                 sesion: Session = Depends(obtener_sesion), actual: dict = Depends(get_current_user)):
        """Emite por ARCA el comprobante de la pre factura y la cierra, en una sola transacción.

        El número y el punto de venta los pone ARCA y la razón social. **Sin certificado de ARCA para la
        razón social no se toca nada** (409). Si ARCA rechaza, no queda nada (502). Contra homologación se
        corre todo y se revierte, y contesta 200 con el resultado del ensayo.
        """
        try:
            comprobante = servicio.facturar(sesion, actual, pre_factura_id,
                                            fecha=datos.fecha if datos else None)
            sesion.commit()
        except servicio.Ensayo as e:
            # Sale con **200 y no 201**: no se creó nada. La pantalla se guía por `ensayo`, no por el
            # código, pero el código tiene que decir la verdad igual.
            return JSONResponse(status_code=200, content=e.respuesta)
        except servicio.Rechazo as e:
            sesion.rollback()
            raise _traducir(e) from None
        except IntegrityError as err:
            sesion.rollback()
            raise traducir_integridad(err) from None
        # Ya autorizado y guardado: el PDF va después, y si no sale el comprobante queda igual (ver `guardar_pdf`).
        comprobantes.guardar_pdf(sesion, comprobante)
        sesion.refresh(comprobante)
        return comprobante

    return router
