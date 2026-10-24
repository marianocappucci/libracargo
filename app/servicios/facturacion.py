"""Facturar directo por ARCA: desde las órdenes pendientes, o con conceptos libres (ADR-048).

Hasta ADR-048 todo comprobante salía de una **pre factura** (ADR-032): un documento intermedio que se mandaba al
cliente y se facturaba después. El humano decidió el 2026-10-13 sacarla: ahora se factura **directo por ARCA**, con
CAE en el momento, por dos caminos que comparten la misma emisión (`_emitir`):

- `facturar_ordenes`: «Facturar pendientes». Las órdenes de un cliente; los ítems y los importes **salen de las
  órdenes**, nunca del pedido. Las órdenes pasan a facturadas.
- `facturar_directa`: «Nueva factura». Conceptos libres (descripción, cantidad, precio, alícuota de IVA), sin órdenes
  ni remitos. Los importes los calcula este módulo desde los conceptos, y el comprobante queda marcado `sin_ordenes`.

## Una sola transacción, y nada que sobreviva a un rechazo

Todo lo que escribe este módulo —el comprobante, las órdenes y la cuenta corriente— pasa por la `Session` del pedido.
El motor escribe por la **misma conexión** (`_conexion_del_motor`, ADR-025 de LibraCore), así que o entra todo o no
entra nada. El número lo da ARCA (`FECompUltimoAutorizado + 1`), el punto de venta es el de la configuración de ARCA,
y el pedido de CAE va **adentro** de la transacción: si ARCA rechaza, no queda ni comprobante, ni órdenes facturadas,
ni asiento, ni número tomado. Sin certificado de producción (o con el CUIT de otra persona) es un 409 que dice cuál es
el problema y no toca nada. Contra homologación se corre todo y se revierte (`Ensayo`).

## Lo que ya no hace la pre factura: el candado

La pre factura reservaba las órdenes (una orden en una sola pre factura abierta) y eso evitaba facturar dos veces lo
mismo. Ahora lo evitan, **en la base**: las órdenes se leen con `FOR UPDATE` (el segundo pedido espera al primero y las
encuentra ya facturadas), y la emisión toma un candado por cliente (`libracore.candados`, el mismo de la nota de
crédito) para que un doble clic en «Nueva factura» —que no tiene órdenes que lo frenen— no emita dos facturas.

## Qué es de este producto y qué es del motor

El protocolo con ARCA, el CUIT del receptor, la FCE, la numeración y la cuenta corriente son del motor y se reusan
(`emision_arca`, `comprobantes`, `cuentas`). Aquí sólo viven la **aritmética de los conceptos** y qué letra puede
emitir cada empresa a cada cliente, que se apoya en las tablas del propio motor (`facturas_router.TIPOS_POR_CONDICION`,
`arca_facturacion.RECEPTORES_DE_FACTURA_A`) sin copiarlas.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from libracore import tipos_comprobante as tipos_cbte
from libracore.arca_facturacion import RECEPTORES_DE_FACTURA_A
from libracore.candados import candado_de_base
from libracore.cuit import solo_digitos
from libracore.db import arca_config
from libracore.facturas_router import TIPOS_FCE_POR_CONDICION, TIPOS_POR_CONDICION
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tiempo
from app.models.enums import (
    TIPO_DE_CODIGO,
    AccionAuditoria,
    CondicionIVA,
    EstadoOrden,
    RolCuenta,
    TipoComprobante,
)
from app.models.maestros import Tercero
from app.models.operacion import Comprobante, OrdenCarga
from app.schemas.comprobantes import NOMBRES_DE_TIPO, TIPOS_FACTURA, TIPOS_FCE, ConceptoIn
from app.servicios import auditoria, comprobantes, cuentas, emision_arca
from app.servicios.comprobantes import etiqueta, sumar_ordenes

log = logging.getLogger(__name__)

CERO = Decimal("0.00")
CENTAVO = Decimal("0.01")

#: La condición de IVA de este producto con el texto que usan las tablas del motor (`IVA_CODES`, `TIPOS_POR_CONDICION`).
#: Una condición que no está acá (consumidor final, no categorizado) no es la de un emisor, y como receptor no se opina.
CONDICION_DEL_MOTOR = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: "Responsable Inscripto",
    CondicionIVA.MONOTRIBUTO: "Monotributista",
    CondicionIVA.EXENTO: "IVA Exento",
    CondicionIVA.CONSUMIDOR_FINAL: "Consumidor Final",
}


class Rechazo(Exception):
    """Un pedido que no se puede cumplir, con el código HTTP que le corresponde.

    El router lo traduce a `HTTPException`. Vive acá y no es una `HTTPException` para que el servicio no
    dependa de la capa web.
    """

    def __init__(self, status: int, detalle: str):
        super().__init__(detalle)
        self.status = status
        self.detalle = detalle


class Ensayo(Exception):
    """Se emitió contra homologación: se corrió todo y se revirtió. `respuesta` es lo que contestó ARCA."""

    def __init__(self, respuesta: dict):
        super().__init__("ensayo contra homologación")
        self.respuesta = respuesta


# ── Qué letra puede emitir esta empresa a este cliente ─────────────────────


def tipos_permitidos(emisor: CondicionIVA | None, receptor: CondicionIVA | None) -> list[TipoComprobante]:
    """Las clases de comprobante que ARCA acepta para este emisor y este receptor, factura común y FCE.

    - **El emisor manda**: un monotributista emite **C**, un inscripto **A o B**, un exento **B** (las tablas del motor,
      `TIPOS_POR_CONDICION` y `TIPOS_FCE_POR_CONDICION`). Una empresa sin condición cargada, o con una que no emite
      (consumidor final), **no tiene tipos**: no se adivina.
    - **Después el receptor**: a un inscripto o monotributista le corresponde **A** y no B
      (`RECEPTORES_DE_FACTURA_A`, medido contra homologación: una B a un inscripto se rechaza con `10243`); a todos
      los demás, B. Si la condición del receptor no se sabe (`no_categorizado`) no se opina y se ofrecen las dos.
    """
    texto = CONDICION_DEL_MOTOR.get(emisor) if emisor else None
    if texto not in TIPOS_POR_CONDICION:
        return []
    codigos = [t["value"] for t in TIPOS_POR_CONDICION[texto]] + TIPOS_FCE_POR_CONDICION.get(texto, [])
    receptor_texto = CONDICION_DEL_MOTOR.get(receptor) if receptor else None
    if receptor_texto is not None:
        pide_a = receptor_texto in RECEPTORES_DE_FACTURA_A
        codigos = [c for c in codigos if tipos_cbte.LETRA[c] == "C" or (tipos_cbte.LETRA[c] == "A") == pide_a]
    return [TIPO_DE_CODIGO[c] for c in codigos]


def exigir_tipo_valido(sesion: Session, tipo: TipoComprobante, cliente: Tercero) -> None:
    """422 con el motivo si la empresa no puede emitir esta clase a este cliente.

    Se dice antes de pedirle el número a ARCA: si no, vuelve como un rechazo del WSFE con el comprobante ya numerado.
    """
    empresa = emision_arca.empresa_de(sesion)
    emisor = empresa.condicion_iva if empresa else None
    if CONDICION_DEL_MOTOR.get(emisor) not in TIPOS_POR_CONDICION:
        raise Rechazo(
            422, "la empresa no tiene cargada una condicion de IVA que emita comprobantes "
                 "(responsable inscripto, monotributo o exento): cargala en Configuración → Datos de la empresa")
    permitidos = tipos_permitidos(emisor, cliente.condicion_iva)
    if tipo in permitidos:
        return
    receptor = CONDICION_DEL_MOTOR.get(cliente.condicion_iva)
    nombres = ", ".join(NOMBRES_DE_TIPO[t] for t in permitidos)
    raise Rechazo(
        422, f"la empresa ({CONDICION_DEL_MOTOR[emisor]}) no puede emitir {NOMBRES_DE_TIPO[tipo]}"
             + (f" a un cliente «{receptor}»" if receptor else "") + f": le corresponde {nombres}")


def opciones_de_tipo(sesion: Session, cliente: Tercero | None) -> dict:
    """Lo que la pantalla de «Nueva factura» necesita para ofrecer los tipos: los permitidos y el sugerido.

    `sugerido` es la factura común (A, B o C) que le corresponde; `fce` dice si la empresa ya puede emitir FCE (tiene
    CBU y modalidad en la configuración de ARCA) y el cliente es una empresa con CUIT de 11 dígitos. `problema` es el
    motivo por el que no se puede emitir ninguna, o `None`.
    """
    empresa = emision_arca.empresa_de(sesion)
    emisor = empresa.condicion_iva if empresa else None
    if CONDICION_DEL_MOTOR.get(emisor) not in TIPOS_POR_CONDICION:
        return {"tipos": [], "sugerido": None, "fce_habilitada": False,
                "problema": "La empresa no tiene cargada la condición de IVA: cargala en Datos de la empresa."}
    permitidos = tipos_permitidos(emisor, cliente.condicion_iva if cliente else None)
    try:
        cfg = emision_arca.configuracion_activa(sesion)
    except emision_arca.ArcaAmbiguo:
        cfg = None
    fce_habilitada = bool(cfg and arca_config.cbu_para_fce(cfg, None) and cfg.get("fce_transmision"))
    if cliente is None or len(solo_digitos(cliente.cuit)) != 11:
        fce_habilitada = False
    comunes = [t for t in permitidos if t in TIPOS_FACTURA and t not in TIPOS_FCE]
    return {
        "tipos": [t.value for t in permitidos if t not in TIPOS_FCE or fce_habilitada],
        "sugerido": comunes[0].value if len(comunes) == 1 else None,
        "fce_habilitada": fce_habilitada,
        "problema": None,
    }


# ── Las validaciones de lo que va a salir ──────────────────────────────────


def validar_tipo_y_fechas(tipo: TipoComprobante, fecha: date, vencimiento: date | None,
                          cliente: Tercero) -> None:
    """Lo que ARCA rechazaría de la FCE, dicho antes de pedirle el número."""
    if tipo not in TIPOS_FACTURA:
        raise Rechazo(
            422, "una nota no se factura desde aca: la de credito y la de debito salen de un comprobante "
                 "con CAE (Comprobantes → Nota de credito / Nota de debito)")
    if tipo in TIPOS_FCE:
        if vencimiento is None:
            raise Rechazo(422, "la factura de credito electronica exige la fecha de vencimiento de pago")
        if vencimiento < fecha:
            raise Rechazo(
                422, "el vencimiento de pago no puede ser anterior a la fecha del comprobante")
        # ARCA lo compara además contra **hoy** (10164, «posterior o igual a la fecha de emisión o a la
        # fecha de presentación, la que sea posterior»).
        if vencimiento < tiempo.hoy():
            raise Rechazo(422, "el vencimiento de pago no puede ser anterior a hoy")
        if len(solo_digitos(cliente.cuit)) != 11:
            # Una FCE se emite a una empresa, y ARCA rechaza el receptor sin CUIT (10015). Se exigen los
            # 11 dígitos y no «algún dígito»: un CUIT a medio cargar llegaría a ARCA y volvería como un
            # 502. Se dice acá, y dice qué hacer.
            raise Rechazo(
                422, "la factura de credito electronica se emite a un receptor con CUIT de 11 "
                     "digitos: cargalo en la ficha del cliente")
    elif vencimiento is not None:
        raise Rechazo(
            422, "solo la factura de credito electronica lleva fecha de vencimiento de pago")


def _tercero(sesion: Session, cliente_id: int) -> Tercero:
    cliente = sesion.get(Tercero, cliente_id)
    if cliente is None:
        raise Rechazo(404, f"no existe el tercero {cliente_id}")
    return cliente


def cargar_ordenes(sesion: Session, *, cliente_id: int, orden_ids: list[int]) -> list[OrdenCarga]:
    """Las órdenes a facturar, en orden de fecha, **bloqueadas** y validadas.

    Existen, son del cliente y están pendientes. `FOR UPDATE`: un segundo pedido por las mismas órdenes espera a que
    éste termine y las encuentra ya facturadas (409), en vez de emitir dos comprobantes por lo mismo.
    """
    ordenes = list(sesion.scalars(
        select(OrdenCarga).where(OrdenCarga.id.in_(orden_ids)).order_by(OrdenCarga.id).with_for_update()))
    faltan = sorted(set(orden_ids) - {o.id for o in ordenes})
    if faltan:
        raise Rechazo(404, f"no existen las ordenes {faltan}")
    for orden in ordenes:
        if orden.cliente_id != cliente_id:
            raise Rechazo(
                422, f"la orden {orden.id} es de otro cliente: una factura es de un solo cliente")
        if orden.estado is not EstadoOrden.PENDIENTE or orden.comprobante_id is not None:
            raise Rechazo(
                409, f"la orden {orden.id} no esta pendiente (esta {orden.estado.value})")
    if sumar_ordenes(ordenes).total <= 0:
        # Sin esto el rechazo llega igual, pero de la base: la contrapartida en la cuenta corriente
        # tiene un CHECK que exige que el asiento mueva el debe o el haber, y un total en cero no
        # mueve ninguno. Saldría como un 409 con el nombre de una restricción, que no explica nada.
        raise Rechazo(422, "las ordenes elegidas suman cero: no hay nada que facturar")
    return sorted(ordenes, key=lambda o: (o.fecha, o.id))


# ── La aritmética de los conceptos ─────────────────────────────────────────


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def totales_de_conceptos(conceptos: Sequence[ConceptoIn], tipo: TipoComprobante) -> dict:
    """`{neto, iva, total, items, alicuota}` de los conceptos, en `Decimal` de punta a punta.

    - Cada renglón es `cantidad × precio`, redondeado al centavo; el **neto** es la suma de los renglones.
    - 🔑 **El IVA se calcula una vez, sobre el neto** y no renglón por renglón: el WSFE del motor arma un solo bloque
      de alícuota por comprobante (`BaseImp` e `Importe`), así que el IVA tiene que ser exactamente `neto × alícuota`
      redondeado, y no la suma de IVA redondeados que puede diferir en un centavo.
    - **Una sola alícuota por comprobante**: mezclar daría un IVA que ARCA no cierra con un solo bloque (el motor no
      arma varios). Se dice con el motivo, y se resuelve con dos facturas.
    - **Una clase C no discrimina IVA**: el precio es el total y la alícuota sale en cero (lo único que admite ARCA).
    """
    es_c = tipo in emision_arca.TIPOS_C
    alicuotas = {c.alicuota_iva for c in conceptos}
    if not es_c and len(alicuotas) > 1:
        raise Rechazo(
            422, "todos los conceptos de una factura llevan la misma alicuota de IVA ("
                 + ", ".join(f"{a.normalize():f}%" for a in sorted(alicuotas))
                 + "): ARCA recibe un solo bloque de IVA por comprobante. Emiti una factura por alicuota")
    alicuota = Decimal(0) if es_c else alicuotas.pop()
    items, neto = [], CERO
    for c in conceptos:
        subtotal = _centavos(c.cantidad * c.precio_unitario)
        neto += subtotal
        items.append({
            "description": c.descripcion, "detalle": "",
            "qty": float(c.cantidad), "unit_price": float(c.precio_unitario), "subtotal": float(subtotal),
            "iva_pct": float(alicuota),
        })
    iva = _centavos(neto * alicuota / 100)
    return {"neto": neto, "iva": iva, "total": neto + iva, "items": items, "alicuota": alicuota}


# ── Emitir ─────────────────────────────────────────────────────────────────


def _concepto_resumen(conceptos: Sequence[ConceptoIn]) -> str:
    primero = conceptos[0].descripcion
    mas = len(conceptos) - 1
    return primero if not mas else f"{primero} y {mas} concepto{'s' if mas > 1 else ''} mas"


def exigir_que_se_pueda_emitir(sesion: Session, cliente: Tercero, tipo: TipoComprobante, fecha: date,
                               vencimiento: date | None) -> None:
    """Lo que se dice **antes** de tocar nada, y con el motivo: sin CUIT en la empresa, sin certificado, con un CUIT de
    ARCA que no es el de la empresa, una FCE sin vencimiento o un CUIT del cliente que no sirve. Levanta `Rechazo`.

    Lo corre `_emitir` y lo corre también el router del nodo antes de dejar un pedido en la cola (ADR-056): un
    pedido que ya se sabe inválido no tiene por qué esperar a que vuelva la conexión para fallar.
    """
    # 🔴 Envuelto también el `ArcaAmbiguo`: con dos configuraciones de ARCA activas no hay forma de saber con qué CUIT
    # firmar, y elegir una es facturar por otro contribuyente sin fallar.
    try:
        problema = emision_arca.problema_de_emision(sesion)
    except emision_arca.ArcaAmbiguo as e:
        raise Rechazo(409, str(e)) from None
    if problema:
        raise Rechazo(409, f"{problema}. No se emitió nada")
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)

    # Antes de pedirle el número a ARCA: un CUIT que no sirve se dice acá, con el nombre del cliente y
    # qué hacer, en vez de volver como un 502 de ARCA.
    problema = emision_arca.problema_del_cuit_del_cliente(cliente, tipo)
    if problema:
        raise Rechazo(422, problema)


def _emitir(sesion: Session, actual: dict, *, cliente: Tercero, tipo: TipoComprobante, fecha: date,
            vencimiento: date | None, cuenta: str | None, neto: Decimal, iva: Decimal, total: Decimal,
            items: list[dict], ordenes: list[OrdenCarga], descripcion: str, observaciones: str = "",
            numerar=None) -> Comprobante:
    """La emisión, igual para los dos caminos: ARCA da el número, el comprobante entra con su CAE, las órdenes se
    cierran y la cuenta corriente del cliente suma la deuda. **Una sola transacción**; no hace `commit`.

    Ver el docstring del módulo: si ARCA rechaza no queda nada, sin certificado es un 409 y no se toca nada, y contra
    homologación se corre todo y se revierte (`Ensayo`).

    `numerar` es de la **cola del nodo** (ADR-056): el `ctx.numerar` con el que se pide el número a ARCA con el ticket
    prestado del central. Fuera de un nodo no se usa.
    """
    # ── ¿Puede emitir la empresa? ──────────────────────────────────────────
    exigir_que_se_pueda_emitir(sesion, cliente, tipo, fecha, vencimiento)
    es_fce = tipo in TIPOS_FCE

    # 🔴 Un doble clic emite dos facturas: sin órdenes que lo frenen (la factura directa) nada lo impediría. El candado
    # es de la base, no del proceso, y dura hasta el `commit` o el `rollback` de esta transacción.
    with candado_de_base(sesion, f"libracargo-facturar:{cliente.id}") as obtenido:
        if not obtenido:
            raise Rechazo(
                409, f"ya hay una factura en curso para {cliente.razon_social}: esperá a que termine "
                     "antes de emitir otra")

        try:
            # 🔑 `asyncio.run` en este hilo, y no un `await` en el loop de uvicorn: la corrutina es `async`
            # sólo en los bordes —la red—, y entre medio lee la base y firma con `openssl`, todo sincrónico.
            # Acá eso bloquea a este hilo y a nadie más (el router es `def`, no `async def`).
            numero, ta, cfg_arca, emisor = asyncio.run(
                emision_arca.numero_que_sigue(sesion, tipo, numerar=numerar))
        except emision_arca.ArcaNoConfigurado as e:
            raise Rechazo(409, str(e)) from None
        except emision_arca.ArcaRechazo as e:
            raise Rechazo(502, f"ARCA no pudo dar el numero: {e}") from None
        punto_venta = emisor.punto_venta
        # En qué cuenta se cobra la FCE: la elegida o, si no, la predeterminada de la configuración con que se
        # numeró. Una que no está cargada en la configuración se dice acá, antes de pedirle el CAE.
        try:
            cuenta_de_cobro = arca_config.cbu_para_fce(cfg_arca, cuenta) if es_fce else ""
        except ValueError as e:
            raise Rechazo(422, str(e)) from None

        # Lo crea el motor en `facturas`, en esta misma transacción (ADR-030): hace falta el id para las
        # órdenes y para el movimiento de cuenta, pero no hay `commit` hasta el final. Con uno acá, un fallo
        # más abajo dejaría el comprobante grabado sin órdenes.
        try:
            comprobante = comprobantes.crear(
                sesion, tipo=tipo,
                punto_venta=punto_venta, numero=numero, fecha=fecha,
                cliente_id=cliente.id, neto=neto, iva=iva, total=total, items=items,
                # En el ambiente de la configuración con la que se numeró.
                ambiente=cfg_arca["ambiente"],
                fch_vto_pago=vencimiento,
                # La FCE sale con la cuenta elegida (o la predeterminada de hoy) y la modalidad de la configuración,
                # y quedan en el comprobante aunque la configuración cambie.
                fce_cbu=cuenta_de_cobro or None,
                fce_transmision=((cfg_arca.get("fce_transmision") or "").upper() or None) if es_fce else None,
                motivo=observaciones or None, sin_ordenes=not ordenes,
            )
        except (comprobantes.NumeroRepetido, emision_arca.ArcaAmbiguo) as e:
            sesion.rollback()
            raise Rechazo(409, str(e)) from None
        for orden in ordenes:
            orden.comprobante_id = comprobante.id
            orden.estado = EstadoOrden.FACTURADA
        cuentas.asentar(
            sesion,
            fecha=fecha, tercero_id=cliente.id, rol=RolCuenta.CLIENTE,
            # El número REAL, el que dio ARCA: la cuenta corriente no puede nombrar un comprobante inexistente.
            concepto=etiqueta(tipo, punto_venta, numero), descripcion=descripcion,
            debe=total, haber=CERO, comprobante_id=comprobante.id,
        )

        # Adentro de la transacción a propósito: si ARCA rechaza, el `commit` NUNCA ocurre y el comprobante
        # no existe —las órdenes siguen pendientes—. No queda un número tomado de este lado y libre del otro.
        #
        # ⚠️ La garantía es esa, no el `rollback` de abajo: `obtener_sesion` cierra la sesión en su `finally`
        # y SQLAlchemy descarta la transacción abierta al cerrar. Se deja igual porque hace explícita la
        # intención y no depende de la semántica de `close()`.
        try:
            # Mismo criterio que el número: loop propio de este hilo. La transacción no se mueve —la `sesion` es la
            # misma y el hilo también—, así que un rechazo sigue sin dejar comprobante.
            asyncio.run(emision_arca.pedir_cae(sesion, comprobante, ta, cfg_arca, emisor))
        except emision_arca.ArcaRechazo as e:
            sesion.rollback()
            raise Rechazo(502, f"ARCA rechazo el comprobante: {e}") from None

        # ── El ensayo: se corrió todo, y no se guarda nada ─────────────────
        #
        # 🔑 Contra homologación el CAE y el número son del WSFE de prueba. Acá **el comprobante no es sólo un papel
        # fiscal**: mueve la cuenta corriente del cliente y cierra las órdenes de carga. Filtrar eso es frágil —la
        # cuenta corriente es un libro con saldos acumulados— y dejarlo entrar es peor.
        #
        # Se revierte **acá y no antes** a propósito: el valor del ensayo es justamente haber recorrido el camino
        # entero contra ARCA —número correlativo, armado del pedido, CAE— y no una simulación local.
        #
        # La respuesta se arma ANTES del rollback: después, `comprobante` queda expirado y leerle un atributo
        # dispararía un SELECT sobre una transacción que ya no existe.
        if emision_arca.es_ensayo(cfg_arca):
            respuesta = {
                "ensayo": True, "ambiente": cfg_arca["ambiente"], "tipo": comprobante.tipo.value,
                "punto_venta": comprobante.punto_venta, "numero": comprobante.numero,
                "total": str(comprobante.total), "cae": comprobante.cae,
                "cae_vencimiento": comprobante.cae_vencimiento.isoformat() if comprobante.cae_vencimiento else None,
            }
            sesion.rollback()
            raise Ensayo(respuesta)
        # Antes del `commit`: si falla después de que ARCA autorizó, el comprobante existe allá y no acá, y este
        # renglón es lo que permite reconstruirlo (mismo criterio que `notas_de_credito.avisar_autorizada`).
        log.warning("comprobante autorizado por ARCA: %s cae=%s (cliente %s)",
                    etiqueta(tipo, punto_venta, numero), comprobante.cae, cliente.id)
        # 🔑 El asiento de auditoría NO se escribe para un ensayo: registrar un alta que se revirtió sería un log que
        # miente en la dirección más cara.
        auditoria.registrar(sesion, actual, "comprobante", comprobante.id, AccionAuditoria.ALTA, despues=comprobante)
        return comprobante


def facturar_ordenes(sesion: Session, actual: dict, *, cliente_id: int, orden_ids: list[int],
                     tipo: TipoComprobante, fecha: date, vencimiento: date | None = None,
                     cuenta: str | None = None, observaciones: str = "", numerar=None) -> Comprobante:
    """«Facturar pendientes»: emite por ARCA el comprobante de las órdenes elegidas. No hace `commit`.

    Los ítems y los importes salen de las órdenes (`comprobantes.items_de`, `sumar_ordenes`): el neto es la suma de las
    tarifas y el IVA la suma de los IVA de cada orden, que ya vienen redondeados.
    """
    cliente = _tercero(sesion, cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    ordenes = cargar_ordenes(sesion, cliente_id=cliente_id, orden_ids=orden_ids)
    suma = sumar_ordenes(ordenes)
    return _emitir(
        sesion, actual, cliente=cliente, tipo=tipo, fecha=fecha, vencimiento=vencimiento, cuenta=cuenta,
        neto=suma.neto, iva=suma.iva, total=suma.total, items=comprobantes.items_de(ordenes), ordenes=ordenes,
        descripcion="Ordenes " + ", ".join(str(o.id) for o in ordenes), observaciones=observaciones,
        numerar=numerar)


def facturar_directa(sesion: Session, actual: dict, *, cliente_id: int, conceptos: Sequence[ConceptoIn],
                     tipo: TipoComprobante, fecha: date, vencimiento: date | None = None,
                     cuenta: str | None = None, observaciones: str = "", numerar=None) -> Comprobante:
    """«Nueva factura»: emite por ARCA un comprobante de conceptos libres, sin órdenes ni remitos. No hace `commit`.

    El comprobante queda marcado `sin_ordenes`: el gate de F5 lo cuenta aparte. Además de las reglas de toda
    emisión, la clase tiene que ser la que corresponde a la empresa y al cliente (`exigir_tipo_valido`).
    """
    cliente = _tercero(sesion, cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    exigir_tipo_valido(sesion, tipo, cliente)
    calculo = totales_de_conceptos(conceptos, tipo)
    if calculo["total"] <= 0:
        raise Rechazo(422, "los conceptos suman cero: no hay nada que facturar")
    return _emitir(
        sesion, actual, cliente=cliente, tipo=tipo, fecha=fecha, vencimiento=vencimiento, cuenta=cuenta,
        neto=calculo["neto"], iva=calculo["iva"], total=calculo["total"], items=calculo["items"], ordenes=[],
        descripcion="Factura directa: " + _concepto_resumen(conceptos), observaciones=observaciones,
        numerar=numerar)


# ── Antes de dejar un pedido en la cola del nodo ───────────────────────────


def validar_de_ordenes(sesion: Session, *, cliente_id: int, orden_ids: list[int], tipo: TipoComprobante, fecha: date,
                       vencimiento: date | None = None) -> None:
    """Todo lo que `facturar_ordenes` dice antes de pedirle el número a ARCA, **sin emitir ni dejar nada**: para que el
    nodo (ADR-056) no encole un pedido que ya se sabe inválido. Levanta `Rechazo`. El `FOR UPDATE` de las órdenes se
    suelta con el `rollback` de quien llama."""
    cliente = _tercero(sesion, cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    cargar_ordenes(sesion, cliente_id=cliente_id, orden_ids=orden_ids)
    exigir_que_se_pueda_emitir(sesion, cliente, tipo, fecha, vencimiento)


def validar_directa(sesion: Session, *, cliente_id: int, conceptos: Sequence[ConceptoIn], tipo: TipoComprobante,
                    fecha: date, vencimiento: date | None = None) -> None:
    """Lo mismo para «Nueva factura»: lo que `facturar_directa` dice antes de ir a ARCA."""
    cliente = _tercero(sesion, cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    exigir_tipo_valido(sesion, tipo, cliente)
    if totales_de_conceptos(conceptos, tipo)["total"] <= 0:
        raise Rechazo(422, "los conceptos suman cero: no hay nada que facturar")
    exigir_que_se_pueda_emitir(sesion, cliente, tipo, fecha, vencimiento)
