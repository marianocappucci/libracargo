"""Comprobantes: registrar la factura de un grupo de órdenes pendientes.

**"Facturar pendientes" es una operación sola, no tres pasos.** En el legado el
alta de una orden insertaba en `orden_carga`, después en `facturas` y después en
la cuenta corriente, con `INSERT` sueltos y sin transacción: si el segundo
fallaba, el primero ya estaba grabado. Acá el comprobante, el estado de las
órdenes y el movimiento de la cuenta del cliente entran o no entran juntos.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.cuentas import MovimientoCuenta
from app.models.enums import (
    AccionAuditoria,
    EstadoOrden,
    RolCuenta,
    TipoComprobante,
)
from app.models.maestros import RazonSocial, Tercero
from app.models.operacion import Comprobante, OrdenCarga
from app.routers.maestros import traducir_integridad
from app.schemas.comprobantes import (
    TIPOS_FACTURA,
    ComprobanteConOrdenes,
    ComprobanteOut,
    FacturarIn,
    TotalDeRazonSocial,
)
from app.servicios import auditoria, emision_arca
from app.servicios.comprobantes import etiqueta, sumar_ordenes, totales_por_razon_social

router = APIRouter(prefix="/api/comprobantes", tags=["comprobantes"],
                   dependencies=[Depends(require_staff)])


def _traer(sesion: Session, id_: int) -> Comprobante:
    comprobante = sesion.get(Comprobante, id_)
    if comprobante is None:
        raise HTTPException(404, f"no existe el comprobante {id_}")
    return comprobante


def _ordenes_de(sesion: Session, comprobante_id: int) -> list[OrdenCarga]:
    return list(sesion.scalars(
        select(OrdenCarga)
        .where(OrdenCarga.comprobante_id == comprobante_id)
        .order_by(OrdenCarga.fecha, OrdenCarga.id)
    ))


# ⚠️ `/totales` va declarada **antes** que `/{id_}`: FastAPI resuelve por orden
# de declaración, y con `/{id_}` primero la palabra "totales" entraría como id y
# el gate de la fase contestaría un 422 de parseo.
@router.get("/totales", response_model=list[TotalDeRazonSocial])
def totales(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = Query(default=None, description="fecha del comprobante, inclusive"),
    hasta: date | None = Query(default=None, description="fecha del comprobante, inclusive"),
):
    """El gate de F5: lo facturado por razón social, contado por los dos lados."""
    return totales_por_razon_social(sesion, desde, hasta)


@router.get("", response_model=list[ComprobanteOut])
def listar(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = None,
    hasta: date | None = None,
    razon_social_id: int | None = None,
    cliente_id: int | None = None,
    tipo: TipoComprobante | None = None,
    # `None` es "todos", y es distinto de `False`: el default muestra los dos,
    # porque esconder los anulados hace que un número que falta en la secuencia
    # no tenga explicación en pantalla.
    anulado: bool | None = Query(default=None),
    limite: int = Query(default=200, ge=1, le=1000),
    desplazamiento: int = Query(default=0, ge=0),
):
    consulta = select(Comprobante)
    for columna, valor in (
        (Comprobante.razon_social_id, razon_social_id),
        (Comprobante.cliente_id, cliente_id),
        (Comprobante.tipo, tipo),
        (Comprobante.anulado, anulado),
    ):
        if valor is not None:
            consulta = consulta.where(columna == valor)
    if desde is not None:
        consulta = consulta.where(Comprobante.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(Comprobante.fecha <= hasta)
    consulta = (
        consulta.order_by(Comprobante.fecha.desc(), Comprobante.id.desc())
        .limit(limite).offset(desplazamiento)
    )
    return list(sesion.scalars(consulta))


@router.get("/{id_}", response_model=ComprobanteConOrdenes)
def traer(id_: int, sesion: Session = Depends(obtener_sesion)):
    """El comprobante con sus órdenes, y si los dos importes dan lo mismo."""
    comprobante = _traer(sesion, id_)
    ordenes = _ordenes_de(sesion, id_)
    suma = sumar_ordenes(ordenes)
    if comprobante.anulado:
        # Un anulado devolvió sus órdenes a pendientes, así que sus importes ya
        # no tienen contra qué compararse. Lo que sí tiene que valer es que no
        # le haya quedado ninguna colgada — una orden todavía apuntando a un
        # comprobante anulado no se podría volver a facturar nunca.
        coinciden = suma.cantidad == 0
    else:
        coinciden = ((comprobante.neto, comprobante.iva, comprobante.total)
                     == (suma.neto, suma.iva, suma.total))
    return ComprobanteConOrdenes(
        comprobante=comprobante, ordenes=ordenes, suma_de_ordenes=suma,
        coinciden=coinciden,
    )


@router.post("", response_model=ComprobanteOut, status_code=201)
async def facturar(datos: FacturarIn, sesion: Session = Depends(obtener_sesion),
             actual: dict = Depends(get_current_user)):
    """Agrupa órdenes pendientes en un comprobante, en una sola transacción.

    🔑 **Hay dos caminos, y los decide la razón social**, no el que llama:

    - **Emite** si tiene ARCA habilitado: el número lo da ARCA
      (`FECompUltimoAutorizado + 1`), el punto de venta sale de la razón social,
      y el comprobante nace con CAE. Un `numero` en el payload se ignora — ARCA
      rechaza cualquiera que no sea el que sigue.
    - **Registra** si no: el número lo tipea una persona, como hasta ahora. Es
      el camino de lo que todavía no tiene certificado cargado, y el que sostiene
      la instancia del cliente mientras tanto.

    ⚠️ **Si ARCA rechaza, no queda comprobante.** El pedido de CAE va adentro de
    la misma transacción: o existe con CAE, o no existe. Un comprobante con un
    número que ARCA no autorizó dejaría el correlativo tomado del lado de acá y
    libre del lado de ellos.

    La unicidad la garantiza la base con `(razon_social, tipo, punto_venta,
    numero)` — el legado tenía `(numero, razon_social)` y no contemplaba ni el
    tipo ni el punto de venta, así que dos comprobantes distintos con el mismo
    número entraban sin que nada los frenara.
    """
    if datos.tipo not in TIPOS_FACTURA:
        raise HTTPException(
            422,
            "una nota de credito no agrupa ordenes pendientes: "
            "para revertir un comprobante hay que anularlo",
        )
    if sesion.get(RazonSocial, datos.razon_social_id) is None:
        raise HTTPException(404, f"no existe la razon social {datos.razon_social_id}")
    cliente = sesion.get(Tercero, datos.cliente_id)
    if cliente is None:
        raise HTTPException(404, f"no existe el tercero {datos.cliente_id}")

    ordenes = list(sesion.scalars(
        select(OrdenCarga).where(OrdenCarga.id.in_(datos.orden_ids))
    ))
    faltan = sorted(set(datos.orden_ids) - {o.id for o in ordenes})
    if faltan:
        raise HTTPException(404, f"no existen las ordenes {faltan}")

    for orden in ordenes:
        if orden.cliente_id != datos.cliente_id:
            raise HTTPException(
                422, f"la orden {orden.id} es de otro cliente: un comprobante "
                     "es de un solo cliente")
        if orden.estado is not EstadoOrden.PENDIENTE or orden.comprobante_id is not None:
            raise HTTPException(
                409, f"la orden {orden.id} no esta pendiente (esta {orden.estado.value})")
        if (orden.razon_social_id is not None
                and orden.razon_social_id != datos.razon_social_id):
            # No se pisa en silencio: la razón social de la orden es la que
            # después suma del lado de las órdenes en el gate de totales, y
            # cambiarla sin decirlo movería plata de una razón social a otra.
            raise HTTPException(
                422, f"la orden {orden.id} tiene otra razon social: "
                     "cambiarla primero, o facturar con la suya")

    suma = sumar_ordenes(ordenes)
    if suma.total <= 0:
        # Sin esto el rechazo llega igual, pero de la base: la contrapartida en
        # la cuenta corriente tiene un CHECK que exige que el asiento mueva el
        # debe o el haber, y un total en cero no mueve ninguno. Eso saldría como
        # un 409 con el nombre de una restricción, que no explica nada.
        raise HTTPException(422, "las ordenes elegidas suman cero: no hay nada que facturar")

    # ── El número: de ARCA si emite, del payload si registra ───────────────
    # 🔴 Envuelto porque `emite_por_arca` puede **negarse a decidir**: con dos
    # configuraciones de ARCA activas no hay forma de saber con qué CUIT
    # firmar, y elegir una es facturar por otro contribuyente sin fallar. Sin
    # este `except` sale como un 500 sin texto, que manda a leer un traceback
    # en vez de a arreglar la configuración.
    try:
        emite = emision_arca.emite_por_arca(sesion, datos.razon_social_id)
    except emision_arca.ArcaAmbiguo as e:
        raise HTTPException(409, str(e)) from None
    ta = cfg_arca = razon = None
    if emite:
        try:
            numero, ta, cfg_arca, razon = await emision_arca.numero_que_sigue(
                sesion, datos.razon_social_id, datos.tipo,
            )
        except emision_arca.ArcaNoConfigurado as e:
            raise HTTPException(409, str(e)) from None
        except emision_arca.ArcaRechazo as e:
            raise HTTPException(502, f"ARCA no pudo dar el numero: {e}") from None
        punto_venta = razon.punto_venta
    else:
        if datos.numero is None:
            raise HTTPException(
                422,
                "falta el numero: esta razon social no tiene ARCA habilitado, "
                "asi que el comprobante se registra con el numero que tenga",
            )
        numero, punto_venta = datos.numero, datos.punto_venta

    comprobante = Comprobante(
        razon_social_id=datos.razon_social_id, tipo=datos.tipo,
        punto_venta=punto_venta, numero=numero, fecha=datos.fecha,
        cliente_id=datos.cliente_id,
        neto=suma.neto, iva=suma.iva, total=suma.total,
    )
    sesion.add(comprobante)
    try:
        # `flush` y no `commit`: hace falta el id para las órdenes y para el
        # movimiento de cuenta, pero la transacción sigue abierta. Con un commit
        # acá, un fallo más abajo dejaría el comprobante grabado sin órdenes.
        sesion.flush()
        for orden in ordenes:
            orden.comprobante_id = comprobante.id
            orden.estado = EstadoOrden.FACTURADA
            # Las órdenes sin razón social heredan la del comprobante; las que
            # ya tenían una, la conservan — el chequeo de arriba garantiza que
            # es la misma.
            orden.razon_social_id = datos.razon_social_id
        sesion.add(MovimientoCuenta(
            fecha=datos.fecha, tercero_id=datos.cliente_id, rol=RolCuenta.CLIENTE,
            # El numero REAL, no el del payload: cuando emite ARCA el del
            # payload viene vacio, y la cuenta corriente nombraria un
            # comprobante inexistente.
            concepto=etiqueta(datos.tipo, punto_venta, numero),
            descripcion="Ordenes " + ", ".join(str(o.id) for o in ordenes),
            debe=suma.total, haber=0, comprobante_id=comprobante.id,
        ))
        if emite:
            # Adentro de la transaccion a proposito: si ARCA rechaza, el
            # `commit` NUNCA ocurre y el comprobante no existe --- las ordenes
            # siguen pendientes. No queda un numero tomado de este lado y libre
            # del otro.
            #
            # ⚠️ La garantia es esa, no el `rollback` de abajo: `obtener_sesion`
            # cierra la sesion en su `finally` y SQLAlchemy descarta la
            # transaccion abierta al cerrar. Medido: sacar el rollback no cambia
            # el resultado. Se deja igual porque hace explicita la intencion y
            # no depende de la semantica de `close()`.
            try:
                await emision_arca.pedir_cae(sesion, comprobante, ta, cfg_arca, razon)
            except emision_arca.ArcaRechazo as e:
                sesion.rollback()
                raise HTTPException(502, f"ARCA rechazo el comprobante: {e}") from None
        auditoria.registrar(sesion, actual, "comprobante", comprobante.id,
                            AccionAuditoria.ALTA, despues=comprobante)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(comprobante)
    return comprobante


@router.delete("/{id_}", response_model=ComprobanteOut)
def anular(id_: int, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    """Anular, no borrar: las órdenes vuelven a pendientes y la cuenta se revierte.

    La reversión es **un movimiento nuevo**, no el borrado del original: la
    cuenta corriente es un registro de lo que pasó, y borrar el asiento haría que
    una cuenta impresa antes de la anulación no se pueda reconstruir después.

    > La contrapartida lleva **la fecha del comprobante**, no la de hoy. Los
    > anulados quedan fuera de los totales por razón social en todo el rango, así
    > que fechar la reversión hoy dejaría a la cuenta corriente mostrando una
    > deuda —entre la factura y su anulación— que los totales ya no reconocen.
    """
    comprobante = _traer(sesion, id_)
    if comprobante.anulado:
        raise HTTPException(409, f"el comprobante {id_} ya esta anulado")

    antes = auditoria.instantanea(comprobante)
    ordenes = _ordenes_de(sesion, id_)
    for orden in ordenes:
        orden.comprobante_id = None
        orden.estado = EstadoOrden.PENDIENTE
    comprobante.anulado = True
    sesion.add(MovimientoCuenta(
        fecha=comprobante.fecha, tercero_id=comprobante.cliente_id,
        rol=RolCuenta.CLIENTE,
        concepto="Anulacion " + etiqueta(
            comprobante.tipo, comprobante.punto_venta, comprobante.numero),
        descripcion="Ordenes " + ", ".join(str(o.id) for o in ordenes),
        debe=0, haber=comprobante.total, comprobante_id=comprobante.id,
    ))
    auditoria.registrar(sesion, actual, "comprobante", comprobante.id,
                        AccionAuditoria.BAJA, antes=antes, despues=comprobante)
    try:
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(comprobante)
    return comprobante
