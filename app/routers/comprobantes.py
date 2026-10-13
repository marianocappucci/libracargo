"""Comprobantes: facturar directo por ARCA, lo facturado, y sus notas de crédito y de débito.

**El comprobante sale de dos caminos y los dos van directo a ARCA** (ADR-048, que reemplaza a la pre factura de
ADR-032): `POST /api/comprobantes/desde-ordenes` (**Facturar pendientes**: las órdenes de un cliente) y
`POST /api/comprobantes/directa` (**Nueva factura**: conceptos libres, sin órdenes ni remitos). El número lo pone ARCA,
el punto de venta es el de su configuración y el emisor es siempre la empresa (ADR-035). Sin certificado de producción,
409 con el motivo y sin tocar nada. Lo que se registró a mano antes y lo migrado del legado sigue ahí, y se anula como
siempre (`DELETE`, sólo sin CAE).

Una factura con CAE se corrige con una **nota de crédito** (la acredita, total o por un importe) o se completa con una
**nota de débito** (le suma un importe: intereses, un gasto). Las dos las emite ARCA y las dos salen del motor.

**La operación es una sola, no tres pasos.** En el legado el alta de una orden insertaba en `orden_carga`,
después en `facturas` y después en la cuenta corriente, con `INSERT` sueltos y sin transacción: si el segundo
fallaba, el primero ya estaba grabado. Acá el comprobante, el estado de las órdenes y el movimiento de la
cuenta del cliente entran o no entran juntos (ver `app/servicios/facturacion.py`).
"""

import asyncio
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from libracore import arca_wsfecred
from libracore.cuit import solo_digitos
from libracore.db import arca_config
from libracore.notas_de_credito import NotaNoPermitida
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import tiempo
from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.enums import (
    AccionAuditoria,
    EstadoOrden,
    RolCuenta,
    TipoComprobante,
)
from app.models.maestros import Tercero
from app.models.operacion import Comprobante, OrdenCarga
from app.routers.maestros import traducir_integridad
from app.schemas.comprobantes import (
    TIPOS_FCE,
    ComprobanteConOrdenes,
    ComprobanteOut,
    FacturaDirectaIn,
    FacturarOrdenesIn,
    NotaDeCreditoIn,
    NotaDeDebitoIn,
    TotalDeComprobantes,
)
from app.servicios import (
    auditoria,
    comprobantes,
    cuentas,
    emision_arca,
    facturacion,
    notas_de_credito,
    notas_de_debito,
)
from app.servicios.comprobantes import (
    TIPOS_CON_ASOCIADO,
    etiqueta,
    sumar_ordenes,
    totales_facturados,
)

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
@router.get("/totales", response_model=TotalDeComprobantes)
def totales(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = Query(default=None, description="fecha del comprobante, inclusive"),
    hasta: date | None = Query(default=None, description="fecha del comprobante, inclusive"),
):
    """El gate de F5: lo facturado, contado por los dos lados."""
    return totales_facturados(sesion, desde, hasta)


@router.get("", response_model=list[ComprobanteOut])
def listar(
    sesion: Session = Depends(obtener_sesion),
    desde: date | None = None,
    hasta: date | None = None,
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


@router.get("/fce/cuentas")
def fce_cuentas(sesion: Session = Depends(obtener_sesion)):
    """En qué cuentas puede cobrar una FCE la empresa (libracore ADR-040): para elegir una al facturar.

    `cuentas` es `[{cbu, alias, etiqueta}]` y `predeterminada` el CBU que sale si no se elige otra. Sin configuración
    de ARCA, o con más de una que no se sabe cuál es, la lista viene vacía: la pantalla dice que no se puede.
    """
    try:
        cfg = emision_arca.configuracion_activa(sesion)
    except emision_arca.ArcaAmbiguo:
        cfg = None
    return {
        "cuentas": arca_config.cbus_fce(cfg),
        "predeterminada": arca_config.cbu_para_fce(cfg, None),
        "transmision": ((cfg or {}).get("fce_transmision") or "").upper(),
    }


@router.get("/fce/corresponde")
def fce_corresponde(
    cliente_id: int,
    total: Decimal = Query(..., gt=0, description="total del comprobante, con IVA"),
    fecha: date | None = Query(default=None, description="fecha de emisión; hoy si no viene"),
    sesion: Session = Depends(obtener_sesion),
):
    """¿A este comprobante le corresponde ser FCE? Lo pregunta «Facturar pendientes» **antes de emitir**.

    La regla es del motor (`libracore.arca_wsfecred.corresponde_fce`, ADR-019 de allá): consulta el registro de FCE
    de ARCA, que no frena una factura común a un receptor obligado. Lo propio de acá es **con qué configuración**:
    la de ARCA (`configuracion_activa`, que sólo devuelve una si su CUIT es el de la empresa) y el CUIT del
    cliente. Es un aviso: nunca falla por ARCA (`disponible: false` y el motivo).
    `fce_habilitada` dice si la empresa ya puede emitir FCE (emite por ARCA y tiene CBU y modalidad cargados).
    """
    cliente = sesion.get(Tercero, cliente_id)
    if cliente is None:
        raise HTTPException(404, f"no existe el tercero {cliente_id}")
    try:
        cfg = emision_arca.configuracion_activa(sesion)
    except emision_arca.ArcaAmbiguo as e:
        return {"disponible": False, "motivo": str(e), "fce_habilitada": False}
    if not solo_digitos(cliente.cuit):
        return {"disponible": False, "motivo": "el cliente no tiene CUIT cargado", "fce_habilitada": False}
    resultado = asyncio.run(arca_wsfecred.corresponde_fce(cfg, cliente.cuit, total, fecha or tiempo.hoy()))
    habilitada = bool(cfg and cfg.get("fce_cbu") and cfg.get("fce_transmision"))
    return resultado | {"fce_habilitada": habilitada}


@router.get("/tipos")
def tipos_de_factura(cliente_id: int | None = None, sesion: Session = Depends(obtener_sesion)):
    """Qué clases de comprobante puede emitir la empresa (a este cliente, si se pasa): la lista de «Nueva factura».

    El emisor manda (monotributo: C; inscripto: A o B; exento: B) y después el receptor (a un inscripto o monotributista
    le corresponde A). `sugerido` es la clase común que le toca cuando hay una sola. `problema` dice por qué no se puede
    emitir ninguna (la empresa sin condición de IVA). Es una ayuda para la pantalla: lo que vale lo vuelve a validar
    `POST /directa`.
    """
    cliente = sesion.get(Tercero, cliente_id) if cliente_id is not None else None
    if cliente_id is not None and cliente is None:
        raise HTTPException(404, f"no existe el tercero {cliente_id}")
    return facturacion.opciones_de_tipo(sesion, cliente)


def _facturar(sesion: Session, emision) -> Comprobante | JSONResponse:
    """El borde HTTP de las dos emisiones: confirma, o traduce lo que pasó (`Rechazo`, `Ensayo`, la base).

    `emision` es una función sin argumentos que llama al servicio. **Un ensayo contra homologación contesta 200 y no
    201** (no se creó nada): la pantalla se guía por `ensayo`, pero el código tiene que decir la verdad igual.
    """
    try:
        comprobante = emision()
        sesion.commit()
    except facturacion.Ensayo as e:
        return JSONResponse(status_code=200, content=e.respuesta)
    except facturacion.Rechazo as e:
        sesion.rollback()
        raise HTTPException(e.status, e.detalle) from None
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    # Ya autorizado y guardado: el PDF va después, y si no sale el comprobante queda igual (ver `guardar_pdf`).
    comprobantes.guardar_pdf(sesion, comprobante)
    sesion.refresh(comprobante)
    return comprobante


# `def` y no `async def`, a propósito: la `Session` y `openssl` son sincrónicos y bloquearían el loop de uvicorn, que
# corre con un solo proceso. Lo asincrónico (WSAA y WSFE) va con `asyncio.run` en un loop propio de este hilo.
@router.post("/desde-ordenes", response_model=ComprobanteOut, status_code=201)
def facturar_ordenes(datos: FacturarOrdenesIn, sesion: Session = Depends(obtener_sesion),
                     actual: dict = Depends(get_current_user)):
    """**Facturar pendientes**: emite por ARCA el comprobante de las órdenes elegidas de un cliente.

    Sin pre factura: el CAE sale en el momento. Los ítems y los importes salen de las órdenes; el número lo pone ARCA y
    el punto de venta es el de su configuración. **Si la empresa no puede emitir (sin CUIT, sin certificado o con otro
    CUIT) no se toca nada** (409, y dice cuál). Si ARCA rechaza, no queda nada (502). Contra homologación se corre todo
    y se revierte, y contesta 200 con el resultado del ensayo.
    """
    return _facturar(sesion, lambda: facturacion.facturar_ordenes(
        sesion, actual, cliente_id=datos.cliente_id, orden_ids=datos.orden_ids, tipo=datos.tipo, fecha=datos.fecha,
        vencimiento=datos.fecha_vencimiento_pago, cuenta=datos.fce_cbu, observaciones=datos.observaciones))


@router.post("/directa", response_model=ComprobanteOut, status_code=201)
def facturar_directa(datos: FacturaDirectaIn, sesion: Session = Depends(obtener_sesion),
                     actual: dict = Depends(get_current_user)):
    """**Nueva factura**: emite por ARCA un comprobante de conceptos libres, sin órdenes ni remitos.

    Cliente, clase (la que corresponde a la empresa y al cliente: `GET /tipos`), fecha y conceptos —descripción,
    cantidad, precio y alícuota de IVA—. Los importes los calcula el servidor. Mismas garantías que
    `POST /desde-ordenes`: sin certificado de producción, 409 y no se toca nada; si ARCA rechaza, no queda nada; contra
    homologación se corre todo y se revierte. El comprobante suma a la cuenta corriente del cliente.
    """
    return _facturar(sesion, lambda: facturacion.facturar_directa(
        sesion, actual, cliente_id=datos.cliente_id, conceptos=datos.conceptos, tipo=datos.tipo, fecha=datos.fecha,
        vencimiento=datos.fecha_vencimiento_pago, cuenta=datos.fce_cbu, observaciones=datos.observaciones))


@router.get("/{id_}", response_model=ComprobanteConOrdenes)
def traer(id_: int, sesion: Session = Depends(obtener_sesion)):
    """El comprobante con sus órdenes, y si los dos importes dan lo mismo."""
    comprobante = _traer(sesion, id_)
    ordenes = _ordenes_de(sesion, id_)
    suma = sumar_ordenes(ordenes)
    if comprobante.sin_ordenes:
        # Una factura directa o una nota de débito no agrupa órdenes (ADR-048): no hay con qué compararla, y compararla
        # con una suma que no tiene la mostraría siempre como un comprobante que no coincide.
        coinciden = suma.cantidad == 0
    elif comprobante.anulado or comprobante.tipo in TIPOS_CON_ASOCIADO:
        # Una nota de crédito no agrupa órdenes: acredita a un comprobante. Compararla con una suma de
        # órdenes que no tiene la mostraría siempre como un comprobante que no coincide con las suyas.
        # Un anulado devolvió sus órdenes a pendientes, así que sus importes ya
        # no tienen contra qué compararse. Lo que sí tiene que valer es que no
        # le haya quedado ninguna colgada — una orden todavía apuntando a un
        # comprobante anulado no se podría volver a facturar nunca.
        coinciden = suma.cantidad == 0
    else:
        coinciden = ((comprobante.neto, comprobante.iva, comprobante.total)
                     == (suma.neto, suma.iva, suma.total))
    acreditado = saldo = None
    if comprobante.cae and not comprobante.anulado and comprobante.tipo not in TIPOS_CON_ASOCIADO:
        # Lo que la pantalla necesita para ofrecer la nota: cuánto se acreditó y cuánto queda. Lo cuenta el motor.
        acreditado, saldo = notas_de_credito.saldo(sesion, comprobante)
    return ComprobanteConOrdenes(
        comprobante=comprobante, ordenes=ordenes, suma_de_ordenes=suma,
        coinciden=coinciden, notas=notas_de_credito.notas_de(sesion, id_),
        notas_debito=notas_de_debito.notas_de(sesion, id_),
        acreditado=acreditado, saldo_acreditable=saldo,
    )


#: Lo que devuelve un ensayo contra homologación. **No es un comprobante**: no
#: tiene `id` porque no hay fila, y por eso tampoco puede ir por `ComprobanteOut`.
#:
#: 🔴 Sale con **200 y no 201**: no se creó nada. La pantalla se guía por
#: `ensayo`, no por el código — pero el código tiene que decir la verdad igual,
#: porque es lo que ve cualquier otro consumidor de la API.
def _respuesta_de_ensayo(comprobante: Comprobante, cfg: dict) -> JSONResponse:
    return JSONResponse(status_code=200, content={
        "ensayo": True,
        "ambiente": cfg["ambiente"],
        "tipo": comprobante.tipo.value,
        "punto_venta": comprobante.punto_venta,
        "numero": comprobante.numero,
        "total": str(comprobante.total),
        "cae": comprobante.cae,
        "cae_vencimiento": (comprobante.cae_vencimiento.isoformat()
                            if comprobante.cae_vencimiento else None),
    })


@router.delete("/{id_}", response_model=ComprobanteOut)
def anular(id_: int, sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    """Anular, no borrar: las órdenes vuelven a pendientes y la cuenta se revierte.

    La reversión es **un movimiento nuevo**, no el borrado del original: la
    cuenta corriente es un registro de lo que pasó, y borrar el asiento haría que
    una cuenta impresa antes de la anulación no se pueda reconstruir después.

    > La contrapartida lleva **la fecha del comprobante**, no la de hoy. Los
    > anulados quedan fuera de los totales en todo el rango, así
    > que fechar la reversión hoy dejaría a la cuenta corriente mostrando una
    > deuda —entre la factura y su anulación— que los totales ya no reconocen.
    """
    comprobante = _traer(sesion, id_)
    if comprobante.anulado:
        raise HTTPException(409, f"el comprobante {id_} ya esta anulado")
    if comprobante.cae:
        # 🔴 **Un comprobante con CAE no se anula desde acá, sea cual sea su tipo.** Anular
        # NO llega a ARCA: el comprobante seguiría vigente allá mientras las órdenes
        # vuelven a pendientes y se pueden facturar de nuevo —dos facturas por lo
        # mismo—, y la cuenta corriente quedaría revertida contra un comprobante que ARCA
        # y el cliente siguen teniendo. Revertirlo pide una nota de crédito **emitida por
        # ARCA** (ADR-026), que sale de `POST /{id}/nota-de-credito` (ADR-027).
        #
        # `cae IS NULL` es el estado de todo lo registrado a mano y de lo migrado del
        # legado: eso se sigue anulando como siempre.
        raise HTTPException(
            409,
            "un comprobante emitido por ARCA (tiene CAE) no se puede anular desde aca: ARCA "
            "lo tiene registrado y sigue vigente alla"
            + (", y el comprador puede aceptarlo" if comprobante.tipo in TIPOS_FCE else "")
            + ". Para revertirlo, emiti una nota de credito (POST "
            f"/api/comprobantes/{id_}/nota-de-credito): sale de ARCA y deja las ordenes pendientes",
        )

    antes = auditoria.instantanea(comprobante)
    ordenes = _ordenes_de(sesion, id_)
    for orden in ordenes:
        orden.comprobante_id = None
        orden.estado = EstadoOrden.PENDIENTE
    # El rastro lo deja el motor, que además lo saca del libro IVA (ADR-022 de LibraCore).
    usuario_id = int(actual["id"]) if str(actual.get("id", "")).isdigit() else None
    comprobantes.anular(sesion, comprobante, usuario_id=usuario_id)
    cuentas.asentar(
        sesion,
        fecha=comprobante.fecha, tercero_id=comprobante.cliente_id,
        rol=RolCuenta.CLIENTE,
        concepto="Anulacion " + etiqueta(
            comprobante.tipo, comprobante.punto_venta, comprobante.numero),
        descripcion="Ordenes " + ", ".join(str(o.id) for o in ordenes),
        debe=0, haber=comprobante.total, comprobante_id=comprobante.id,
    )
    auditoria.registrar(sesion, actual, "comprobante", comprobante.id,
                        AccionAuditoria.BAJA, antes=antes, despues=comprobante)
    try:
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    sesion.refresh(comprobante)
    return comprobante


#: El mismo mapa que el router de facturas del motor: la nota es una sola para toda la familia, y quien la
#: consume por HTTP tiene que recibir el mismo código por el mismo motivo en cualquier producto.
_STATUS_DE_NOTA = {
    NotaNoPermitida.TIPO: 400,
    NotaNoPermitida.YA_TIENE_NOTA: 409,
    NotaNoPermitida.NOTA_SIN_CAE: 409,
    NotaNoPermitida.EN_CURSO: 409,
    NotaNoPermitida.RECEPTOR: 422,
    NotaNoPermitida.IMPORTE: 422,
    NotaNoPermitida.SUPERA_SALDO: 409,
    NotaNoPermitida.ORIGINAL_SIN_CAE: 409,
}


@router.post("/{id_}/nota-de-credito", response_model=ComprobanteOut, status_code=201)
# `def` y no `async def`, por lo mismo que `facturar`: la sesión y `openssl` son sincrónicos y bloquearían el
# loop de uvicorn. Lo asincrónico (WSAA y WSFE) va con `asyncio.run` en un loop propio de este hilo.
def nota_de_credito(id_: int, datos: NotaDeCreditoIn, sesion: Session = Depends(obtener_sesion),
                    actual: dict = Depends(get_current_user)):
    """Acredita un comprobante emitido por ARCA con una nota de crédito autorizada por ARCA: **total** (sin
    `importe`) o **parcial** (`importe`, con IVA).

    La lógica es la del motor (`libracore.notas_de_credito`): la nota total sólo sobre un comprobante sin notas, la
    suma de las notas nunca supera su total, una FCE sólo admite notas por menos que su saldo, el CUIT del receptor
    tiene que servir, dos pedidos a la vez emiten una sola nota, y la nota sale con la fecha de hoy y asociada a su
    comprobante. Lo propio de este producto, que pasa **en la misma transacción** (ADR-028):

    - la cuenta corriente del cliente recibe el abono por el importe de la nota, con la fecha de la nota;
    - si el comprobante queda acreditado **por completo**, queda `anulado` y sus **órdenes vuelven a pendientes**
      (se pueden refacturar). Con saldo, las órdenes no se tocan.

    ⚠️ **Si ARCA rechaza, no queda nada**: ni la nota, ni el original anulado, ni el abono. Contra
    homologación se corre todo y se revierte (ver `facturar`): una prueba no mueve la cuenta del cliente.
    """
    # `FOR UPDATE`: un segundo pedido espera a que éste termine en vez de leer el original a medio cerrar.
    original = sesion.get(Comprobante, id_, with_for_update=True)
    if original is None:
        raise HTTPException(404, f"no existe el comprobante {id_}")
    if original.anulado:
        raise HTTPException(409, f"el comprobante {id_} ya esta anulado")
    if not original.cae:
        raise HTTPException(
            409,
            "este comprobante no tiene CAE: ARCA no lo conoce, asi que no hay nada que acreditar. "
            "Se anula desde aca (DELETE) como siempre",
        )
    # Ni la FCE ni las notas tienen guarda propia: qué se puede acreditar y por cuánto lo decide el motor.

    hoy = tiempo.hoy()
    try:
        nota, cfg = asyncio.run(notas_de_credito.emitir(
            sesion, original, motivo=datos.motivo, hoy=hoy, importe=datos.importe))
    except NotaNoPermitida as e:
        sesion.rollback()
        raise HTTPException(_STATUS_DE_NOTA.get(e.codigo, 409), str(e)) from None
    except emision_arca.ArcaNoConfigurado as e:
        sesion.rollback()
        raise HTTPException(409, str(e)) from None
    except emision_arca.ArcaAmbiguo as e:
        sesion.rollback()
        raise HTTPException(409, str(e)) from None
    except emision_arca.ArcaRechazo as e:
        sesion.rollback()
        raise HTTPException(502, f"ARCA rechazo la nota de credito: {e}") from None
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None

    if emision_arca.es_ensayo(cfg):
        # Se corrió todo contra homologación y no se guarda nada (ver `facturar`). La respuesta se arma antes
        # del rollback: después `nota` queda expirada.
        respuesta = _respuesta_de_ensayo(nota, cfg)
        sesion.rollback()
        return respuesta

    notas_de_credito.avisar_autorizada(nota, original)
    antes = auditoria.instantanea(original)
    notas_de_credito.cerrar_lo_propio(sesion, original, nota)
    auditoria.registrar(sesion, actual, "comprobante", nota.id, AccionAuditoria.ALTA, despues=nota)
    auditoria.registrar(sesion, actual, "comprobante", original.id, AccionAuditoria.MODIFICACION,
                        antes=antes, despues=original)
    try:
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    # La nota ya está autorizada y guardada: su PDF va después, y si no sale queda igual (ver `guardar_pdf`).
    comprobantes.guardar_pdf(sesion, nota)
    sesion.refresh(nota)
    return nota


@router.post("/{id_}/nota-de-debito", response_model=ComprobanteOut, status_code=201)
# `def` y no `async def`, por lo mismo que `facturar`.
def nota_de_debito(id_: int, datos: NotaDeDebitoIn, sesion: Session = Depends(obtener_sesion),
                   actual: dict = Depends(get_current_user)):
    """Le suma un importe a una factura emitida por ARCA con una **nota de débito** autorizada por ARCA (ADR-048).

    La lógica es la del motor (`libracore.notas_de_debito`): la letra y la FCE se heredan (2/7/12; 202/207/212), el
    original tiene que tener CAE, el CUIT del receptor tiene que servir, dos pedidos a la vez emiten una sola nota y la
    nota sale con la fecha de hoy y asociada a su factura. **A diferencia de la de crédito va siempre por un importe
    (con IVA) y no tiene tope**: agrega plata (intereses, un gasto, una diferencia). Lo propio de este producto, que
    pasa **en la misma transacción**: la cuenta corriente del cliente recibe el **cargo** por el importe, con la fecha
    de la nota. No libera órdenes ni anula el original.

    ⚠️ **Si ARCA rechaza, no queda nada**: ni la nota ni el cargo. Contra homologación se corre todo y se revierte (ver
    `facturar`): una prueba no mueve la cuenta del cliente.
    """
    # Sin `FOR UPDATE`, a diferencia de la nota de crédito: la de débito no modifica el original, y bloquearlo haría
    # que un doble clic esperara al primer pedido y emitiera una segunda nota. Lo que lo frena es el candado del motor
    # (`conn=sesion`): el segundo pedido recibe un 409 «en curso» en vez de esperar.
    original = _traer(sesion, id_)
    if original.anulado:
        raise HTTPException(409, f"el comprobante {id_} ya esta anulado")
    if not original.cae:
        raise HTTPException(
            409,
            "este comprobante no tiene CAE: ARCA no lo conoce, asi que no hay nada a lo que asociar una nota de debito",
        )

    hoy = tiempo.hoy()
    try:
        nota, cfg = asyncio.run(notas_de_debito.emitir(
            sesion, original, motivo=datos.motivo, hoy=hoy, importe=datos.importe))
    except NotaNoPermitida as e:
        sesion.rollback()
        raise HTTPException(_STATUS_DE_NOTA.get(e.codigo, 409), str(e)) from None
    except (emision_arca.ArcaNoConfigurado, emision_arca.ArcaAmbiguo) as e:
        sesion.rollback()
        raise HTTPException(409, str(e)) from None
    except emision_arca.ArcaRechazo as e:
        sesion.rollback()
        raise HTTPException(502, f"ARCA rechazo la nota de debito: {e}") from None
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None

    if emision_arca.es_ensayo(cfg):
        # Se corrió todo contra homologación y no se guarda nada (ver `facturar`). La respuesta se arma antes
        # del rollback: después `nota` queda expirada.
        respuesta = _respuesta_de_ensayo(nota, cfg)
        sesion.rollback()
        return respuesta

    notas_de_credito.avisar_autorizada(nota, original)
    notas_de_debito.cerrar_lo_propio(sesion, original, nota)
    auditoria.registrar(sesion, actual, "comprobante", nota.id, AccionAuditoria.ALTA, despues=nota)
    try:
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    # La nota ya está autorizada y guardada: su PDF va después, y si no sale queda igual (ver `guardar_pdf`).
    comprobantes.guardar_pdf(sesion, nota)
    sesion.refresh(nota)
    return nota
