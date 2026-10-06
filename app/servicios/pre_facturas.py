"""La pre factura de LibraCargo: qué órdenes lleva, y cómo se factura (ADR-032).

**El documento es del motor, y lo propio es de acá.** La pre factura es una fila de
`comprobantes_pendientes` con número interno (`PF-0001`), ciclo (pendiente, enviada, aceptada,
facturada, anulada), PDF y correo: todo eso lo hace `libracore.pre_facturas` (ADR-030 de LibraCore). Lo
que sólo sabe este producto vive en dos tablas:

- `pre_facturas_cargo`: la razón social que facturaría y el tercero. Con el mismo id que la pre factura.
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
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import tiempo
from app.models.configuracion import ConfiguracionEmpresa
from app.models.enums import (
    CODIGO_ARCA,
    TIPO_DE_CODIGO,
    AccionAuditoria,
    CondicionIVA,
    EstadoOrden,
    RolCuenta,
    TipoComprobante,
)
from app.models.maestros import RazonSocial, Tercero
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

#: Cómo se lee la condición de IVA de la razón social en el encabezado del PDF.
_CONDICION_IVA = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: "Responsable Inscripto",
    CondicionIVA.MONOTRIBUTO: "Monotributista",
    CondicionIVA.EXENTO: "Exento",
    CondicionIVA.CONSUMIDOR_FINAL: "Consumidor Final",
    CondicionIVA.NO_CATEGORIZADO: "",
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


def cargar_ordenes(sesion: Session, *, cliente_id: int, razon_social_id: int, orden_ids: list[int],
                   pre_factura_id: int | None = None) -> list[OrdenCarga]:
    """Las órdenes de la pre factura, en orden de fecha, validadas.

    Las mismas reglas que tenía facturar directo: existen, son del cliente, están pendientes y su razón
    social es la elegida (o no tiene). Además **no están reservadas en otra pre factura**: la de
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
        if orden.razon_social_id is not None and orden.razon_social_id != razon_social_id:
            # No se pisa en silencio: la razón social de la orden es la que después suma del lado de
            # las órdenes en el gate de totales, y cambiarla sin decirlo movería plata de una razón
            # social a otra.
            raise Rechazo(
                422, f"la orden {orden.id} tiene otra razon social: "
                     "cambiarla primero, o facturar con la suya")
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


def _emisor_id(sesion: Session, razon_social_id: int) -> int | None:
    try:
        return comprobantes.emisor_de(sesion, razon_social_id)
    except emision_arca.ArcaAmbiguo as e:
        raise Rechazo(409, str(e)) from None


def _domicilio(cliente: Tercero) -> str:
    partes = [cliente.direccion, cliente.localidad, cliente.provincia]
    return ", ".join(p.strip() for p in partes if p and p.strip())


def _campos_del_motor(sesion: Session, tipo: TipoComprobante, razon_social_id: int, fecha: date,
                      vencimiento: date | None, observaciones: str, ordenes: list[OrdenCarga]) -> dict:
    """Lo que la pre factura del motor guarda y que sale de lo que eligió el operador."""
    return {
        "items": items_de_pre_factura(ordenes, tipo),
        "emisor_id": _emisor_id(sesion, razon_social_id),
        "tipo_comprobante": CODIGO_ARCA[tipo],
        "fecha_sugerida": fecha.isoformat(),
        "fecha_vencimiento_pago": vencimiento.isoformat() if vencimiento else "",
        "observaciones": observaciones,
    }


def _razon(sesion: Session, razon_social_id: int) -> RazonSocial:
    razon = sesion.get(RazonSocial, razon_social_id)
    if razon is None:
        raise Rechazo(404, f"no existe la razon social {razon_social_id}")
    return razon


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


def crear(sesion: Session, actual: dict, *, cliente_id: int, razon_social_id: int, tipo: TipoComprobante,
          fecha: date, vencimiento: date | None, orden_ids: list[int], observaciones: str = "") -> dict:
    """Genera la pre factura de las órdenes y las reserva. No hace `commit`."""
    _razon(sesion, razon_social_id)
    cliente = _tercero(sesion, cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    ordenes = cargar_ordenes(sesion, cliente_id=cliente_id, razon_social_id=razon_social_id,
                             orden_ids=orden_ids)
    try:
        pf = dominio.crear(
            origen_producto=ORIGEN_PRODUCTO, origen_instancia=ORIGEN_INSTANCIA,
            cliente_razon=cliente.razon_social,
            # 🔴 Sin `cliente_id`: en la bandeja del motor es una FK a `clients`, y los clientes de este
            # producto son `terceros`. El tercero va en `pre_facturas_cargo`.
            cliente_cuit=cliente.cuit or "", cliente_domicilio=_domicilio(cliente),
            conn=_conexion_del_motor(sesion),
            **_campos_del_motor(sesion, tipo, razon_social_id, fecha, vencimiento, observaciones, ordenes))
    except ValueError as e:  # incluye `EmisorDesconocido`
        sesion.rollback()
        raise Rechazo(422, str(e)) from None
    sesion.add(PreFacturaCargo(
        pre_factura_id=pf["id"], razon_social_id=razon_social_id, cliente_id=cliente.id))
    sesion.flush()
    _reservar(sesion, pf["id"], [o.id for o in ordenes])
    auditoria.registrar(sesion, actual, "pre_factura", pf["id"], AccionAuditoria.ALTA, despues=pf)
    return pf


def editar(sesion: Session, actual: dict, pre_factura_id: int, *, razon_social_id: int,
           tipo: TipoComprobante, fecha: date, vencimiento: date | None, orden_ids: list[int],
           observaciones: str = "") -> dict:
    """Reemplaza las órdenes y cambia razón social, tipo y fechas de una pre factura abierta.

    Si estaba enviada o aceptada vuelve a pendiente (el cliente aceptó **otros** datos), salvo que no haya
    cambiado nada (ver `libracore.pre_facturas.editar`). El cliente no se cambia: otro cliente es otra pre
    factura. No hace `commit`.
    """
    conn = _conexion_del_motor(sesion)
    antes = pre_factura_de(sesion, pre_factura_id)
    cargo = sesion.get(PreFacturaCargo, pre_factura_id)
    if cargo is None:
        raise Rechazo(404, f"la pre factura {antes['numero_interno']} no es de LibraCargo")
    _razon(sesion, razon_social_id)
    cliente = _tercero(sesion, cargo.cliente_id)
    validar_tipo_y_fechas(tipo, fecha, vencimiento, cliente)
    ordenes = cargar_ordenes(sesion, cliente_id=cargo.cliente_id, razon_social_id=razon_social_id,
                             orden_ids=orden_ids, pre_factura_id=pre_factura_id)
    try:
        pf = dominio.editar(
            pre_factura_id, conn=conn,
            # El cliente va como foto: al editar se refresca, así lo que se vuelve a mandar es lo de hoy.
            cliente_razon=cliente.razon_social, cliente_cuit=cliente.cuit or "",
            cliente_domicilio=_domicilio(cliente),
            **_campos_del_motor(sesion, tipo, razon_social_id, fecha, vencimiento, observaciones, ordenes))
    except dominio.TransicionInvalida as e:
        sesion.rollback()
        raise Rechazo(409, str(e)) from None
    except ValueError as e:
        sesion.rollback()
        raise Rechazo(422, str(e)) from None
    cargo.razon_social_id = razon_social_id
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


def sin_certificado(razon: RazonSocial) -> Rechazo:
    return Rechazo(
        409,
        f"La razon social {razon.nombre} no tiene configurado el certificado de ARCA: la pre factura "
        "queda lista para facturar cuando este (Configuracion -> ARCA, con el CUIT de esta razon social)")


def facturar(sesion: Session, actual: dict, pre_factura_id: int, *, fecha: date | None = None) -> Comprobante:
    """Emite por ARCA el comprobante de la pre factura y la cierra, **en una sola transacción**.

    Es el camino de emisión de siempre (`facturar` de los comprobantes hasta ADR-032), con los datos de la
    pre factura en vez de los que se tipeaban:

    - **El número lo da ARCA** (`FECompUltimoAutorizado + 1`) y el punto de venta sale de la razón social.
    - **Si ARCA rechaza, no queda nada**: ni comprobante, ni órdenes facturadas, ni asiento, ni la pre
      factura cerrada. El pedido de CAE va adentro de la misma transacción.
    - Sin certificado de ARCA para la razón social no se toca nada (409, y dice cuál).
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
    razon = _razon(sesion, cargo.razon_social_id)
    cliente = _tercero(sesion, cargo.cliente_id)

    if (pf["cliente_razon"], pf["cliente_cuit"] or "") != (cliente.razon_social, cliente.cuit or ""):
        # El comprobante sale con los datos del cliente de hoy: si cambiaron, el cliente vio otros.
        raise Rechazo(
            409, f"los datos del cliente cambiaron desde que se genero la pre factura {pf['numero_interno']}: "
                 "editala para actualizarla y volve a enviarla antes de facturar")

    # ── ¿Emite esta razón social? ──────────────────────────────────────────
    # 🔴 Envuelto porque `emite_por_arca` puede **negarse a decidir**: con dos configuraciones de ARCA
    # activas no hay forma de saber con qué CUIT firmar, y elegir una es facturar por otro contribuyente
    # sin fallar. Sin este `except` sale como un 500 sin texto.
    try:
        emite = emision_arca.emite_por_arca(sesion, razon.id)
    except emision_arca.ArcaAmbiguo as e:
        raise Rechazo(409, str(e)) from None
    if not emite:
        raise sin_certificado(razon)

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
    ordenes = cargar_ordenes(sesion, cliente_id=cliente.id, razon_social_id=razon.id,
                             orden_ids=reservadas, pre_factura_id=pre_factura_id)
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
        numero, ta, cfg_arca, razon_emisora = asyncio.run(
            emision_arca.numero_que_sigue(sesion, razon.id, tipo))
    except emision_arca.ArcaNoConfigurado:
        raise sin_certificado(razon) from None
    except emision_arca.ArcaRechazo as e:
        raise Rechazo(502, f"ARCA no pudo dar el numero: {e}") from None
    punto_venta = razon_emisora.punto_venta

    # Lo crea el motor en `facturas`, en esta misma transacción (ADR-030): hace falta el id para las
    # órdenes y para el movimiento de cuenta, pero no hay `commit` hasta el final. Con uno acá, un fallo
    # más abajo dejaría el comprobante grabado sin órdenes.
    try:
        comprobante = comprobantes.crear(
            sesion, razon_social_id=razon.id, tipo=tipo,
            punto_venta=punto_venta, numero=numero, fecha=fecha,
            cliente_id=cliente.id, neto=suma.neto, iva=suma.iva, total=suma.total,
            items=comprobantes.items_de(ordenes),
            # En el ambiente de la configuración con la que se numeró.
            ambiente=cfg_arca["ambiente"],
            fch_vto_pago=vencimiento,
            # La FCE sale con el CBU y la modalidad de la configuración de hoy, y quedan en el
            # comprobante aunque la configuración cambie después.
            fce_cbu=(cfg_arca.get("fce_cbu") or None) if es_fce else None,
            fce_transmision=((cfg_arca.get("fce_transmision") or "").upper() or None) if es_fce else None,
        )
    except (comprobantes.NumeroRepetido, emision_arca.ArcaAmbiguo) as e:
        sesion.rollback()
        raise Rechazo(409, str(e)) from None
    for orden in ordenes:
        orden.comprobante_id = comprobante.id
        orden.estado = EstadoOrden.FACTURADA
        # Las órdenes sin razón social heredan la del comprobante; las que ya tenían una, la
        # conservan: `cargar_ordenes` garantiza que es la misma.
        orden.razon_social_id = razon.id
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
        asyncio.run(emision_arca.pedir_cae(sesion, comprobante, ta, cfg_arca, razon_emisora))
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


def emisor_del_pdf(sesion: Session, pre_factura: dict) -> dict | None:
    """Los datos del emisor para el PDF: la razón social de la pre factura, con el domicilio de la empresa.

    El nombre, el CUIT y la condición de IVA son de la razón social (una instancia puede tener más de una).
    El domicilio, los ingresos brutos y el inicio de actividades salen de los datos de la empresa de la
    instancia, **sólo si son de esa razón social** (mismo CUIT, o la empresa no cargó CUIT): los de otra
    razón social saldrían con el domicilio equivocado.
    """
    cargo = sesion.get(PreFacturaCargo, pre_factura["id"])
    razon = sesion.get(RazonSocial, cargo.razon_social_id) if cargo else None
    if razon is None:
        return None
    emisor = {
        "nombre": razon.nombre, "cuit": razon.cuit or "",
        "iva_condition": _CONDICION_IVA[razon.condicion_iva],
    }
    empresa = sesion.get(ConfiguracionEmpresa, 1)
    if empresa is not None and (not _digitos(empresa.cuit) or _digitos(empresa.cuit) == _digitos(razon.cuit)):
        partes = [empresa.domicilio, empresa.localidad, empresa.provincia]
        emisor["direccion"] = ", ".join(p.strip() for p in partes if p and p.strip())
        emisor["iibb"] = empresa.ingresos_brutos or ""
        emisor["inicio_actividades"] = empresa.inicio_actividades or ""
        emisor["telefono"] = empresa.telefono or ""
        emisor["email"] = empresa.email or ""
    return emisor


def enriquecer(sesion: Session, filas: list[dict]) -> list[dict]:
    """Suma a cada pre factura del motor lo propio: la razón social, el cliente y las órdenes.

    - `cliente_id`: el tercero. `razon_social_id` y `razon_social`: la que facturaría.
    - `orden_ids`: las que lleva, que salen de los ítems (valen también para una cerrada).
    - `total` como texto con dos decimales, como los importes del resto de la API.
    """
    ids = [f["id"] for f in filas]
    cargos = {c.pre_factura_id: c for c in sesion.scalars(
        select(PreFacturaCargo).where(PreFacturaCargo.pre_factura_id.in_(ids)))} if ids else {}
    razones = {r.id: r.nombre for r in sesion.scalars(select(RazonSocial))}
    salida = []
    for f in filas:
        cargo = cargos.get(f["id"])
        salida.append(f | {
            # Sobre-escribe el `cliente_id` de la bandeja (siempre vacío acá) con el tercero.
            "cliente_id": cargo.cliente_id if cargo else None,
            "razon_social_id": cargo.razon_social_id if cargo else None,
            "razon_social": razones.get(cargo.razon_social_id, "") if cargo else "",
            "orden_ids": [i["orden_id"] for i in f["items"] if i.get("orden_id") is not None],
            "total": f"{Decimal(str(f['total'])):.2f}",
        })
    return salida

