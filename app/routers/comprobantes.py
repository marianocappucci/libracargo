"""Comprobantes: registrar la factura de un grupo de órdenes pendientes.

**"Facturar pendientes" es una operación sola, no tres pasos.** En el legado el
alta de una orden insertaba en `orden_carga`, después en `facturas` y después en
la cuenta corriente, con `INSERT` sueltos y sin transacción: si el segundo
fallaba, el primero ya estaba grabado. Acá el comprobante, el estado de las
órdenes y el movimiento de la cuenta del cliente entran o no entran juntos.
"""

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from libracore.notas_de_credito import NotaNoPermitida
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import tiempo
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
    TIPOS_FCE,
    ComprobanteConOrdenes,
    ComprobanteOut,
    FacturarIn,
    NotaDeCreditoIn,
    TotalDeRazonSocial,
)
from app.servicios import auditoria, comprobantes, emision_arca, notas_de_credito
from app.servicios.comprobantes import (
    TIPOS_NOTA,
    etiqueta,
    sumar_ordenes,
    totales_por_razon_social,
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
    if comprobante.anulado or comprobante.tipo in TIPOS_NOTA:
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
    if comprobante.cae and not comprobante.anulado and comprobante.tipo not in TIPOS_NOTA:
        # Lo que la pantalla necesita para ofrecer la nota: cuánto se acreditó y cuánto queda. Lo cuenta el motor.
        acreditado, saldo = notas_de_credito.saldo(sesion, comprobante)
    return ComprobanteConOrdenes(
        comprobante=comprobante, ordenes=ordenes, suma_de_ordenes=suma,
        coinciden=coinciden, notas=notas_de_credito.notas_de(sesion, id_),
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


@router.post("", response_model=ComprobanteOut, status_code=201)
# 🔴 **`def` y no `async def`, a propósito.** Casi todo lo que hace esta ruta
# es sincrónico —la `Session`, y adentro de la emisión `openssl` por
# subproceso para firmar el TRA— y uvicorn corre con **un solo proceso**:
# como `async def`, cada consulta frenaba el loop entero, y mientras se
# facturaba la instancia no le contestaba a nadie, `/health` incluido. Como
# `def`, FastAPI la corre en el threadpool. Lo único asincrónico de verdad
# —WSAA y WSFE— va con `asyncio.run` en un loop propio de este hilo.
def facturar(datos: FacturarIn, sesion: Session = Depends(obtener_sesion),
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
    es_fce = datos.tipo in TIPOS_FCE
    if es_fce and len("".join(c for c in (cliente.cuit or "") if c.isdigit())) != 11:
        # Una FCE se emite a una empresa, y ARCA rechaza el receptor sin CUIT (10015).
        # Se exigen los 11 dígitos y no «algún dígito»: un CUIT a medio cargar llegaría
        # a ARCA y volvería como un 502. Se dice acá, y dice qué hacer.
        raise HTTPException(
            422,
            "la factura de credito electronica se emite a un receptor con CUIT de 11 "
            "digitos: cargalo en la ficha del cliente",
        )

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
    if es_fce and not emite:
        # Una FCE sin CAE no tiene sentido: es el documento que ARCA registra y que
        # el comprador acepta o rechaza. No hay camino de «registrar a mano».
        raise HTTPException(
            422,
            "la factura de credito electronica solo se emite por ARCA: esta razon "
            "social no lo tiene habilitado (cargá el certificado y la clave en "
            "Configuracion, con el CUIT de esta razon social)",
        )
    if emite:
        # Antes de pedirle el número a ARCA: un CUIT que no sirve se dice acá, con
        # el nombre del cliente y qué hacer, en vez de volver como un 502 de ARCA.
        problema = emision_arca.problema_del_cuit_del_cliente(cliente, datos.tipo)
        if problema:
            raise HTTPException(422, problema)
    ta = cfg_arca = razon = None
    if emite:
        try:
            # 🔑 `asyncio.run` en este hilo, y no un `await` en el loop de
            # uvicorn: la corrutina es `async` sólo en los bordes —la red—, y
            # entre medio lee la base y firma con `openssl`, todo sincrónico.
            # Acá eso bloquea a este hilo y a nadie más. La firma de
            # `emision_arca` no cambia: el arreglo va del lado de quien llama.
            numero, ta, cfg_arca, razon = asyncio.run(emision_arca.numero_que_sigue(
                sesion, datos.razon_social_id, datos.tipo,
            ))
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

    try:
        # Lo crea el motor en `facturas`, en esta misma transacción (ADR-030): hace
        # falta el id para las órdenes y para el movimiento de cuenta, pero no hay
        # `commit` hasta el final. Con uno acá, un fallo más abajo dejaría el
        # comprobante grabado sin órdenes.
        try:
            comprobante = comprobantes.crear(
                sesion, razon_social_id=datos.razon_social_id, tipo=datos.tipo,
                punto_venta=punto_venta, numero=numero, fecha=datos.fecha,
                cliente_id=datos.cliente_id, neto=suma.neto, iva=suma.iva, total=suma.total,
                items=comprobantes.items_de(ordenes),
                # Si emite, en el ambiente de la configuración con la que se numeró.
                ambiente=cfg_arca["ambiente"] if emite else None,
                fch_vto_pago=datos.fecha_vencimiento_pago,
                # La FCE sale con el CBU y la modalidad de la configuración de hoy, y
                # quedan en el comprobante aunque la configuración cambie después.
                fce_cbu=(cfg_arca.get("fce_cbu") or None) if es_fce and emite else None,
                fce_transmision=((cfg_arca.get("fce_transmision") or "").upper() or None)
                if es_fce and emite else None,
            )
        except comprobantes.NumeroRepetido as e:
            sesion.rollback()
            raise HTTPException(409, str(e)) from None
        except emision_arca.ArcaAmbiguo as e:
            sesion.rollback()
            raise HTTPException(409, str(e)) from None
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
                # Mismo criterio que el número: loop propio de este hilo. La
                # transacción no se mueve —la `sesion` es la misma y el hilo
                # también—, así que un rechazo sigue sin dejar comprobante.
                asyncio.run(emision_arca.pedir_cae(sesion, comprobante, ta, cfg_arca, razon))
            except emision_arca.ArcaRechazo as e:
                sesion.rollback()
                raise HTTPException(502, f"ARCA rechazo el comprobante: {e}") from None

            # ── El ensayo: se corrió todo, y no se guarda nada ─────────────
            #
            # 🔑 Contra homologación el CAE y el número son del WSFE de prueba.
            # En otro producto alcanzaría con marcar la fila y filtrarla; acá
            # **el comprobante no es sólo un papel fiscal**: mueve la cuenta
            # corriente del cliente y cierra las órdenes de carga, que después
            # no se pueden volver a facturar. Filtrar eso es frágil —la cuenta
            # corriente es un libro con saldos acumulados— y dejarlo entrar es
            # peor.
            #
            # Se revierte **acá y no antes** a propósito: el valor del ensayo es
            # justamente haber recorrido el camino entero contra ARCA —número
            # correlativo, armado del pedido, CAE— y no una simulación local.
            #
            # La respuesta se arma ANTES del rollback: después, `comprobante`
            # queda expirado y leerle un atributo dispararía un SELECT sobre una
            # transacción que ya no existe.
            if emision_arca.es_ensayo(cfg_arca):
                respuesta = _respuesta_de_ensayo(comprobante, cfg_arca)
                sesion.rollback()
                return respuesta
        # 🔑 El asiento de auditoría NO se escribe para un ensayo, y el `return`
        # de arriba es lo que lo evita: registrar un alta que se revirtió sería
        # un log que miente en la dirección más cara — dice que existe un
        # comprobante que nadie va a encontrar.
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
    sesion.refresh(nota)
    return nota
