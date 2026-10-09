"""La pre factura de LibraCargo: qué órdenes lleva, y cómo se factura (ADR-032).

**El documento es del motor, y lo propio es de acá.** La pre factura es una fila de
`comprobantes_pendientes` con número interno (`PF-0001`), ciclo (pendiente, enviada, aceptada,
facturada, anulada), PDF y correo: todo eso lo hace `libracore.pre_facturas` (ADR-030 de LibraCore). Lo
que sólo sabe este producto vive en dos tablas:

- `pre_facturas_cargo`: el tercero. Con el mismo id que la pre factura.
- `pre_factura_ordenes`: la **reserva** de cada orden. `orden_id` es la clave primaria: una orden está en
  a lo sumo una pre factura abierta. Anular o facturar la pre factura libera la reserva.

## Una sola transacción

Todo lo que escribe este módulo —la pre factura del motor, la reserva, el comprobante, las órdenes y la
cuenta corriente— pasa por la `Session` del pedido. El motor escribe por la **misma conexión**
(`_conexion_del_motor`, ADR-025 de LibraCore), así que o entra todo o no entra nada. Si ARCA rechaza el
CAE, la pre factura sigue como estaba.

## Los ítems salen de las órdenes, igual que los de la factura

`items_de_pre_factura` parte de `comprobantes.items_de`, que es lo que lleva la factura. El cliente nunca
manda ítems ni importes: salen de las órdenes. Y al facturar se vuelven a armar desde las órdenes y se
comparan con los de la pre factura: si una orden cambió en el medio, no se factura algo distinto de lo que
el cliente vio (`LasOrdenesCambiaron`).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from libracore import pre_facturas as dominio
from libracore.db import arca_config
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import tiempo
from app.models.enums import (
    CODIGO_ARCA,
    TIPO_DE_CODIGO,
    AccionAuditoria,
    EstadoOrden,
    RolCuenta,
    TipoComprobante,
)
from app.models.maestros import Tercero
from app.models.operacion import (
    Comprobante,
    OrdenCarga,
    PreFacturaCargo,
    PreFacturaOrden,
)
from app.schemas.comprobantes import TIPOS_FACTURA, TIPOS_FCE
from app.servicios import auditoria, comprobantes, cuentas, emision_arca
from app.servicios.comprobantes import _conexion_del_motor, etiqueta, sumar_ordenes

#: De quién son las pre facturas en el motor. Una instancia de LibraCargo es una base: no hay instancias
#: que distinguir adentro, así que la instancia va vacía (la numeración `PF-0001` es de la base).
ORIGEN_PRODUCTO = "libracargo"
ORIGEN_INSTANCIA = ""


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


# ── Qué órdenes entran ─────────────────────────────────────────────────────


def _digitos(cuit: str | None) -> str:
    return "".join(c for c in (cuit or "") if c.isdigit())


def reservada_en(sesion: Session, orden_id: int) -> int | None:
    """El id de la pre factura abierta que tiene reservada esta orden, o `None`."""
    return sesion.scalar(select(PreFacturaOrden.pre_factura_id).where(PreFacturaOrden.orden_id == orden_id))


def numero_de(pre_factura_id: int, conn=None) -> str:
    """`PF-0003`, para decir de qué pre factura se habla en un mensaje."""
    pf = dominio.get(pre_factura_id, conn=conn)
    return pf["numero_interno"] if pf else f"#{pre_factura_id}"


def exigir_orden_libre(sesion: Session, orden: OrdenCarga) -> None:
    """Una orden en una pre factura abierta no se edita ni se anula: la pre factura quedaría diciendo otra cosa.

    Es lo que usan `PUT` y `DELETE /api/ordenes/{id}`. Se libera quitándola de la pre factura o anulándola.
    """
    pre = reservada_en(sesion, orden.id)
    if pre is not None:
        raise Rechazo(
            409,
            f"la orden {orden.id} esta en la pre factura {numero_de(pre, _conexion_del_motor(sesion))}: "
            "quitala de ahi o anula la pre factura primero")


def cargar_ordenes(sesion: Session, *, cliente_id: int, orden_ids: list[int],
                   pre_factura_id: int | None = None) -> list[OrdenCarga]:
    """Las órdenes de la pre factura, en orden de fecha, validadas.

    Las mismas reglas que tenía facturar directo: existen, son del cliente y están pendientes.
    Además **no están reservadas en otra pre factura**: la de
    `pre_factura_id` (la que se está editando o facturando) no cuenta como «otra».
    """
    ordenes = list(sesion.scalars(select(OrdenCarga).where(OrdenCarga.id.in_(orden_ids))))
    faltan = sorted(set(orden_ids) - {o.id for o in ordenes})
    if faltan:
        raise Rechazo(404, f"no existen las ordenes {faltan}")
    for orden in ordenes:
        if orden.cliente_id != cliente_id:
            raise Rechazo(
                422, f"la orden {orden.id} es de otro cliente: una pre factura es de un solo cliente")
        if orden.estado is not EstadoOrden.PENDIENTE or orden.comprobante_id is not None:
            raise Rechazo(
                409, f"la orden {orden.id} no esta pendiente (esta {orden.estado.value})")
    reservadas = {
        orden_id: pre for orden_id, pre in sesion.execute(
            select(PreFacturaOrden.orden_id, PreFacturaOrden.pre_factura_id)
            .where(PreFacturaOrden.orden_id.in_(orden_ids)))
        if pre != pre_factura_id
    }
    if reservadas:
        conn = _conexion_del_motor(sesion)
        orden_id, pre = sorted(reservadas.items())[0]
        raise Rechazo(
            409, f"la orden {orden_id} ya esta en la pre factura {numero_de(pre, conn)}"
                 + (f" (y {len(reservadas) - 1} mas)" if len(reservadas) > 1 else ""))
    suma = sumar_ordenes(ordenes)
    if suma.total <= 0:
        # Sin esto el rechazo llega igual, pero de la base: la contrapartida en la cuenta corriente
        # tiene un CHECK que exige que el asiento mueva el debe o el haber, y un total en cero no
        # mueve ninguno. Saldría como un 409 con el nombre de una restricción, que no explica nada.
        raise Rechazo(422, "las ordenes elegidas suman cero: no hay nada que facturar")
    return sorted(ordenes, key=lambda o: (o.fecha, o.id))


def items_de_pre_factura(ordenes: list[OrdenCarga], tipo: TipoComprobante) -> list[dict]:
    """Los ítems de la pre factura: los de la factura (`comprobantes.items_de`), con la forma del motor.

    - `unit_price` es la tarifa y `iva_rate` una **fracción** (`0.21`), que es como cuenta el total la
      pre factura del motor: `qty × precio × (1 + iva_rate)`.
    - 🔑 **La alícuota es la que dan los importes de la orden**, `iva / tarifa`, y no la nominal. Cada
      orden redondea su IVA a dos decimales, y la factura suma esos IVA ya redondeados (ver
      `sumar_ordenes`): con la alícuota nominal, el total de la pre factura podía diferir en un centavo
      del de la factura que sale después. Para una tarifa redonda las dos son la misma (`0.21`).
    - Una clase C no discrimina IVA: el precio es el **total** de la orden y la alícuota 0, que es lo
      que sale a ARCA (`pedir_cae`) y lo único que admite el motor.
    - `orden_id` queda en el ítem: es lo que une la pre factura cerrada con sus órdenes.
    """
    es_c = tipo in emision_arca.TIPOS_C
    salida = []
    for orden, base in zip(ordenes, comprobantes.items_de(ordenes), strict=True):
        if es_c:
            precio, tasa = float(orden.total), 0.0
        else:
            precio = base["unit_price"]
            tasa = float(orden.iva / orden.tarifa) if orden.tarifa else float(orden.alicuota_iva) / 100
        salida.append({
            "description": base["description"], "detalle": base["detalle"],
            "qty": base["qty"], "unit_price": precio, "iva_rate": tasa, "orden_id": orden.id,
        })
    return salida


# ── Validaciones del comprobante que va a salir ────────────────────────────


def validar_tipo_y_fechas(tipo: TipoComprobante, fecha: date, vencimiento: date | None,
                          cliente: Tercero) -> None:
    """Lo que ARCA rechazaría de la FCE, dicho mientras la pre factura todavía se puede corregir."""
    if tipo not in TIPOS_FACTURA:
        raise Rechazo(
            422, "una nota de credito no agrupa ordenes pendientes: "
                 "para revertir un comprobante hay que anularlo")
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
        if len(_digitos(cliente.cuit)) != 11:
            # Una FCE se emite a una empresa, y ARCA rechaza el receptor sin CUIT (10015). Se exigen los
            # 11 dígitos y no «algún dígito»: un CUIT a medio cargar llegaría a ARCA y volvería como un
            # 502. Se dice acá, y dice qué hacer.
            raise Rechazo(
                422, "la factura de credito electronica se emite a un receptor con CUIT de 11 "
                     "digitos: cargalo en la ficha del cliente")
    elif vencimiento is not None:
        raise Rechazo(
            422, "solo la factura de credito electronica lleva fecha de vencimiento de pago")


def _emisor_id(sesion: Session) -> int | None:
    try:
        return comprobantes.emisor_de(sesion)
    except emision_arca.ArcaAmbiguo as e:
        raise Rechazo(409, str(e)) from None


def _domicilio(cliente: Tercero) -> str:
    partes = [cliente.direccion, cliente.localidad, cliente.provincia]
    return ", ".join(p.strip() for p in partes if p and p.strip())


def _campos_del_motor(sesion: Session, tipo: TipoComprobante, fecha: date,
                      vencimiento: date | None, observaciones: str, ordenes: list[OrdenCarga]) -> dict:
    """Lo que la pre factura del motor guarda y que sale de lo que eligió el operador."""
    return {
        "items": items_de_pre_factura(ordenes, tipo),
        "emisor_id": _emisor_id(sesion),
        "tipo_comprobante": CODIGO_ARCA[tipo],
        "fecha_sugerida": fecha.isoformat(),
        "fecha_vencimiento_pago": vencimiento.isoformat() if vencimiento else "",
        "observaciones": observaciones,
    }


def _tercero(sesion: Session, cliente_id: int) -> Tercero:
    cliente = sesion.get(Tercero, cliente_id)
    if cliente is None:
        raise Rechazo(404, f"no existe el tercero {cliente_id}")
    return cliente


def _reservar(sesion: Session, pre_factura_id: int, orden_ids: list[int]) -> None:
    sesion.add_all([PreFacturaOrden(orden_id=i, pre_factura_id=pre_factura_id) for i in orden_ids])
    try:
        sesion.flush()
    except IntegrityError:
        # Dos pedidos a la vez por la misma orden: el que llega segundo pierde contra la clave primaria.
        sesion.rollback()
        raise Rechazo(409, "alguna de las ordenes se reservo en otra pre factura mientras tanto") from None


def pre_factura_de(sesion: Session, pre_factura_id: int) -> dict:
    """La pre factura de LibraCargo, o 404 si no existe o es de otro origen."""
    pf = dominio.get(pre_factura_id, conn=_conexion_del_motor(sesion))
    if (pf is None or pf["origen_producto"] != ORIGEN_PRODUCTO
            or pf["origen_instancia"] != ORIGEN_INSTANCIA):
        raise Rechazo(404, f"no existe la pre factura {pre_factura_id}")
    return pf


# ── Crear y editar ─────────────────────────────────────────────────────────


def crear(sesion: Session, actual: dict, *, cliente_id: int, tipo: TipoComprobante,
          fecha: date, vencimiento: date | None, orden_ids: list[int], observaciones: str = "",
          cuenta: str | None = None) -> dict:
    """Genera la pre factura de las órdenes y las reserva. No hace `commit`."""
    cliente = _tercero(sesion, cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    ordenes = cargar_ordenes(sesion, cliente_id=cliente_id, orden_ids=orden_ids)
    try:
        pf = dominio.crear(
            origen_producto=ORIGEN_PRODUCTO, origen_instancia=ORIGEN_INSTANCIA,
            cliente_razon=cliente.razon_social,
            # 🔴 Sin `cliente_id`: en la bandeja del motor es una FK a `clients`, y los clientes de este
            # producto son `terceros`. El tercero va en `pre_facturas_cargo`.
            cliente_cuit=cliente.cuit or "", cliente_domicilio=_domicilio(cliente),
            conn=_conexion_del_motor(sesion),
            # La cuenta de cobro de la FCE la resuelve y la valida el motor (ADR-040 de libracore).
            fce_cbu=cuenta or None,
            **_campos_del_motor(sesion, tipo, fecha, vencimiento, observaciones, ordenes))
    except ValueError as e:  # incluye `EmisorDesconocido` y una cuenta que no está cargada
        sesion.rollback()
        raise Rechazo(422, str(e)) from None
    sesion.add(PreFacturaCargo(
        pre_factura_id=pf["id"], cliente_id=cliente.id))
    sesion.flush()
    _reservar(sesion, pf["id"], [o.id for o in ordenes])
    auditoria.registrar(sesion, actual, "pre_factura", pf["id"], AccionAuditoria.ALTA, despues=pf)
    return pf


def editar(sesion: Session, actual: dict, pre_factura_id: int, *,
           tipo: TipoComprobante, fecha: date, vencimiento: date | None, orden_ids: list[int],
           observaciones: str = "", cuenta: str | None = None) -> dict:
    """Reemplaza las órdenes y cambia tipo y fechas de una pre factura abierta.

    Si estaba enviada o aceptada vuelve a pendiente (el cliente aceptó **otros** datos), salvo que no haya
    cambiado nada (ver `libracore.pre_facturas.editar`). El cliente no se cambia: otro cliente es otra pre
    factura. No hace `commit`.
    """
    conn = _conexion_del_motor(sesion)
    antes = pre_factura_de(sesion, pre_factura_id)
    cargo = sesion.get(PreFacturaCargo, pre_factura_id)
    if cargo is None:
        raise Rechazo(404, f"la pre factura {antes['numero_interno']} no es de LibraCargo")
    cliente = _tercero(sesion, cargo.cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    ordenes = cargar_ordenes(sesion, cliente_id=cargo.cliente_id, orden_ids=orden_ids,
                             pre_factura_id=pre_factura_id)
    try:
        pf = dominio.editar(
            pre_factura_id, conn=conn,
            # El cliente va como foto: al editar se refresca, así lo que se vuelve a mandar es lo de hoy.
            cliente_razon=cliente.razon_social, cliente_cuit=cliente.cuit or "",
            cliente_domicilio=_domicilio(cliente),
            # `None` no toca la cuenta elegida; `""` vuelve a la predeterminada (convención del motor).
            **({"fce_cbu": cuenta} if cuenta is not None else {}),
            **_campos_del_motor(sesion, tipo, fecha, vencimiento, observaciones, ordenes))
    except dominio.TransicionInvalida as e:
        sesion.rollback()
        raise Rechazo(409, str(e)) from None
    except ValueError as e:
        sesion.rollback()
        raise Rechazo(422, str(e)) from None
    nuevas = {o.id for o in ordenes}
    vigentes = set(sesion.scalars(
        select(PreFacturaOrden.orden_id).where(PreFacturaOrden.pre_factura_id == pre_factura_id)))
    if vigentes - nuevas:
        sesion.execute(delete(PreFacturaOrden).where(
            PreFacturaOrden.pre_factura_id == pre_factura_id,
            PreFacturaOrden.orden_id.in_(vigentes - nuevas)))
    _reservar(sesion, pre_factura_id, sorted(nuevas - vigentes))
    auditoria.registrar(sesion, actual, "pre_factura", pre_factura_id, AccionAuditoria.MODIFICACION,
                        antes=antes, despues=pf)
    return pf


def liberar(conn, pre_factura: dict, _datos: dict | None = None) -> None:
    """Gancho de `al_anular` del router del motor: suelta las órdenes de la pre factura anulada.

    Corre en la transacción de la anulación (con la conexión del motor), así que la pre factura anulada
    y las órdenes libres entran juntas.
    """
    conn.execute("DELETE FROM pre_factura_ordenes WHERE pre_factura_id = ?", (pre_factura["id"],))


# ── Facturar ───────────────────────────────────────────────────────────────


def facturar(sesion: Session, actual: dict, pre_factura_id: int, *, fecha: date | None = None) -> Comprobante:
    """Emite por ARCA el comprobante de la pre factura y la cierra, **en una sola transacción**.

    Es el camino de emisión de siempre (`facturar` de los comprobantes hasta ADR-032), con los datos de la
    pre factura en vez de los que se tipeaban:

    - **El número lo da ARCA** (`FECompUltimoAutorizado + 1`) y el punto de venta sale de la configuración de ARCA.
    - **Si ARCA rechaza, no queda nada**: ni comprobante, ni órdenes facturadas, ni asiento, ni la pre
      factura cerrada. El pedido de CAE va adentro de la misma transacción.
    - Si la empresa no puede emitir (sin CUIT, sin certificado, o el CUIT de ARCA no es el de la empresa) no se
      toca nada: 409, y dice cuál es el problema (ADR-035).
    - Contra homologación se corre todo y se revierte: levanta `Ensayo`.

    `fecha` es la del comprobante (la de la pre factura si no se pasa): a los días de generarla, ARCA
    puede no aceptar la vieja. No hace `commit`; lo hace quien llama, cuando no hubo ensayo.
    """
    conn = _conexion_del_motor(sesion)
    pf = pre_factura_de(sesion, pre_factura_id)
    if pf["estado"] not in dominio.ESTADOS_ABIERTOS:
        raise Rechazo(409, f"la pre factura {pf['numero_interno']} esta "
                           f"{'facturada' if pf['estado'] == 'facturado' else 'anulada'}: no se factura")
    cargo = sesion.get(PreFacturaCargo, pre_factura_id)
    if cargo is None:
        raise Rechazo(404, f"la pre factura {pf['numero_interno']} no es de LibraCargo")
    cliente = _tercero(sesion, cargo.cliente_id)

    if (pf["cliente_razon"], pf["cliente_cuit"] or "") != (cliente.razon_social, cliente.cuit or ""):
        # El comprobante sale con los datos del cliente de hoy: si cambiaron, el cliente vio otros.
        raise Rechazo(
            409, f"los datos del cliente cambiaron desde que se genero la pre factura {pf['numero_interno']}: "
                 "editala para actualizarla y volve a enviarla antes de facturar")

    # ── ¿Puede emitir la empresa? ──────────────────────────────────────────
    # Se dice **antes** de tocar nada, y con el motivo: sin CUIT en la empresa, sin certificado, o con un
    # CUIT de ARCA que no es el de la empresa. 🔴 Envuelto también el `ArcaAmbiguo`: con dos configuraciones
    # de ARCA activas no hay forma de saber con qué CUIT firmar, y elegir una es facturar por otro
    # contribuyente sin fallar. Sin este `except` sale como un 500 sin texto.
    try:
        problema = emision_arca.problema_de_emision(sesion)
    except emision_arca.ArcaAmbiguo as e:
        raise Rechazo(409, str(e)) from None
    if problema:
        raise Rechazo(409, f"{problema}. La pre factura queda lista para facturar cuando esté resuelto")

    tipo = TIPO_DE_CODIGO[pf["tipo_comprobante"]]
    es_fce = tipo in TIPOS_FCE
    fecha = fecha or date.fromisoformat(pf["fecha_sugerida"][:10])
    vencimiento = date.fromisoformat(pf["fecha_vencimiento_pago"][:10]) if pf["fecha_vencimiento_pago"] else None
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)

    # ── Las órdenes: las reservadas, y tal como las vio el cliente ─────────
    reservadas = sorted(sesion.scalars(
        select(PreFacturaOrden.orden_id).where(PreFacturaOrden.pre_factura_id == pre_factura_id)))
    if not reservadas:
        raise Rechazo(409, f"la pre factura {pf['numero_interno']} no tiene ordenes reservadas")
    ordenes = cargar_ordenes(sesion, cliente_id=cliente.id, orden_ids=reservadas,
                             pre_factura_id=pre_factura_id)
    if items_de_pre_factura(ordenes, tipo) != pf["items"]:
        raise Rechazo(
            409, f"las ordenes de la pre factura {pf['numero_interno']} cambiaron desde que se genero: "
                 "editala para actualizarla y volve a enviarla antes de facturar")
    suma = sumar_ordenes(ordenes)

    # Antes de pedirle el número a ARCA: un CUIT que no sirve se dice acá, con el nombre del cliente y
    # qué hacer, en vez de volver como un 502 de ARCA.
    problema = emision_arca.problema_del_cuit_del_cliente(cliente, tipo)
    if problema:
        raise Rechazo(422, problema)

    try:
        # 🔑 `asyncio.run` en este hilo, y no un `await` en el loop de uvicorn: la corrutina es `async`
        # sólo en los bordes —la red—, y entre medio lee la base y firma con `openssl`, todo sincrónico.
        # Acá eso bloquea a este hilo y a nadie más (el router es `def`, no `async def`).
        numero, ta, cfg_arca, emisor = asyncio.run(
            emision_arca.numero_que_sigue(sesion, tipo))
    except emision_arca.ArcaNoConfigurado as e:
        raise Rechazo(409, str(e)) from None
    except emision_arca.ArcaRechazo as e:
        raise Rechazo(502, f"ARCA no pudo dar el numero: {e}") from None
    punto_venta = emisor.punto_venta
    # En qué cuenta se cobra la FCE: la que se eligió en la pre factura o, si no, la predeterminada de la
    # configuración con que se numeró. Una que se sacó de la configuración después de elegirla se dice acá,
    # antes de pedirle el CAE.
    try:
        cuenta_de_cobro = arca_config.cbu_para_fce(cfg_arca, pf.get("fce_cbu")) if es_fce else ""
    except ValueError as e:
        raise Rechazo(422, f"{e} Editá la pre factura y elegí otra cuenta.") from None

    # Lo crea el motor en `facturas`, en esta misma transacción (ADR-030): hace falta el id para las
    # órdenes y para el movimiento de cuenta, pero no hay `commit` hasta el final. Con uno acá, un fallo
    # más abajo dejaría el comprobante grabado sin órdenes.
    try:
        comprobante = comprobantes.crear(
            sesion, tipo=tipo,
            punto_venta=punto_venta, numero=numero, fecha=fecha,
            cliente_id=cliente.id, neto=suma.neto, iva=suma.iva, total=suma.total,
            items=comprobantes.items_de(ordenes),
            # En el ambiente de la configuración con la que se numeró.
            ambiente=cfg_arca["ambiente"],
            fch_vto_pago=vencimiento,
            # La FCE sale con la cuenta elegida en la pre factura (o la predeterminada de hoy) y la
            # modalidad de la configuración, y quedan en el comprobante aunque la configuración cambie.
            fce_cbu=cuenta_de_cobro or None,
            fce_transmision=((cfg_arca.get("fce_transmision") or "").upper() or None) if es_fce else None,
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
        # El número REAL, el que dio ARCA: la cuenta corriente no puede nombrar un comprobante
        # inexistente.
        concepto=etiqueta(tipo, punto_venta, numero),
        descripcion="Ordenes " + ", ".join(str(o.id) for o in ordenes),
        debe=suma.total, haber=Decimal(0), comprobante_id=comprobante.id,
    )
    # La pre factura queda cerrada con su factura, y las órdenes ya no están reservadas: ahora las
    # tiene el comprobante.
    sesion.execute(delete(PreFacturaOrden).where(PreFacturaOrden.pre_factura_id == pre_factura_id))
    dominio.marcar_facturada(pre_factura_id, comprobante.id, actual.get("username") or "", conn=conn)

    # Adentro de la transacción a propósito: si ARCA rechaza, el `commit` NUNCA ocurre y el comprobante
    # no existe —las órdenes siguen pendientes y la pre factura abierta—. No queda un número tomado de
    # este lado y libre del otro.
    #
    # ⚠️ La garantía es esa, no el `rollback` de abajo: `obtener_sesion` cierra la sesión en su `finally`
    # y SQLAlchemy descarta la transacción abierta al cerrar. Se deja igual porque hace explícita la
    # intención y no depende de la semántica de `close()`.
    try:
        # Mismo criterio que el número: loop propio de este hilo. La transacción no se mueve —la
        # `sesion` es la misma y el hilo también—, así que un rechazo sigue sin dejar comprobante.
        asyncio.run(emision_arca.pedir_cae(sesion, comprobante, ta, cfg_arca, emisor))
    except emision_arca.ArcaRechazo as e:
        sesion.rollback()
        raise Rechazo(502, f"ARCA rechazo el comprobante: {e}") from None

    # ── El ensayo: se corrió todo, y no se guarda nada ─────────────────────
    #
    # 🔑 Contra homologación el CAE y el número son del WSFE de prueba. Acá **el comprobante no es sólo
    # un papel fiscal**: mueve la cuenta corriente del cliente, cierra las órdenes de carga y cierra la
    # pre factura, que después no se pueden volver a facturar. Filtrar eso es frágil —la cuenta corriente
    # es un libro con saldos acumulados— y dejarlo entrar es peor.
    #
    # Se revierte **acá y no antes** a propósito: el valor del ensayo es justamente haber recorrido el
    # camino entero contra ARCA —número correlativo, armado del pedido, CAE— y no una simulación local.
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
    # 🔑 El asiento de auditoría NO se escribe para un ensayo: registrar un alta que se revirtió sería un
    # log que miente en la dirección más cara.
    auditoria.registrar(sesion, actual, "comprobante", comprobante.id,
                        AccionAuditoria.ALTA, despues=comprobante)
    auditoria.registrar(sesion, actual, "pre_factura", pre_factura_id, AccionAuditoria.MODIFICACION,
                        antes=pf, despues=dominio.get(pre_factura_id, conn=conn))
    return comprobante


# ── Lo que lee la pantalla ─────────────────────────────────────────────────


def enriquecer(sesion: Session, filas: list[dict]) -> list[dict]:
    """Suma a cada pre factura del motor lo propio: el cliente y las órdenes.

    - `cliente_id`: el tercero.
    - `orden_ids`: las que lleva, que salen de los ítems (valen también para una cerrada).
    - `total` como texto con dos decimales, como los importes del resto de la API.
    """
    ids = [f["id"] for f in filas]
    conn = _conexion_del_motor(sesion)
    cargos = {c.pre_factura_id: c for c in sesion.scalars(
        select(PreFacturaCargo).where(PreFacturaCargo.pre_factura_id.in_(ids)))} if ids else {}
    salida = []
    for f in filas:
        cargo = cargos.get(f["id"])
        salida.append(f | {
            # Sobre-escribe el `cliente_id` de la bandeja (siempre vacío acá) con el tercero.
            "cliente_id": cargo.cliente_id if cargo else None,
            "orden_ids": [i["orden_id"] for i in f["items"] if i.get("orden_id") is not None],
            "total": f"{Decimal(str(f['total'])):.2f}",
            # Dónde se cobra una FCE: la elegida o la predeterminada (`fce_cbu` en `None` dice que no se eligió).
            "fce_cuenta": arca_config.cuenta_de_cobro(f, conn=conn),
        })
    return salida

