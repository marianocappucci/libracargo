"""El asiento que una orden deja en la cuenta corriente del fletero.

🔴 **Esto faltaba.** En el legado, dar de alta una orden inserta en
`fleteroctacte` con la **comisión** como importe — por eso es la tabla más
movida del sistema, 12.995 filas contra 6.267 de la de clientes. LibraCargo
leía `comision` sólo para los reportes y **nunca escribía en la cuenta del
fletero**: medido sobre la instancia del cliente, de los 8.674 movimientos que
apuntan a una orden, **cero** son posteriores a la migración.

El efecto no se veía porque la instancia todavía no tiene órdenes nuevas, y
habría aparecido recién después del corte: la cuenta de un fletero mostrando
**pagos sin cargos**, con el saldo corriendo para un solo lado.

## Qué columna

`debe`, igual que el legado. Las tres cuentas comparten convención —el cargo va
a `debe`, el pago a `haber`— y el saldo se lee `debe − haber` en los dos
sistemas. Para un fletero eso significa que el saldo positivo es **lo que la
agencia le debe**.

## Por qué se actualiza en el lugar y no con un ajuste

Corregir la comisión de una orden pendiente deja **una** línea en la cuenta, no
dos. Es lo que hace `modifica_carga.php` (un `UPDATE` sobre la fila del fletero)
y es lo que el cliente espera ver. Una orden facturada no se puede editar, así
que un asiento ya conciliado nunca se toca por esta vía; y quién cambió qué
queda en el log de actividad, que es donde se mira eso.

En cambio **anular sí deja las dos líneas**: ahí se revierte con un asiento
nuevo, con la fecha de la orden, igual que la anulación de un comprobante.

## Lo que NO hace: el lado del cliente

El legado también inserta en `clientectacte` al dar de alta la orden. Acá no:
el cliente debe cuando se le factura, y ese asiento lo hace el comprobante. Es
una diferencia deliberada — duplicarla acá contaría el importe dos veces.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCuenta
from app.models.enums import EstadoOrden, RolCuenta
from app.models.maestros import Localidad, TipoCarga
from app.models.operacion import OrdenCarga

CERO = Decimal("0.00")


def _nombre(sesion: Session, modelo, id_: int | None) -> str | None:
    if id_ is None:
        return None
    return sesion.scalar(select(modelo.nombre).where(modelo.id == id_))


def describir(sesion: Session, orden: OrdenCarga) -> str:
    """El detalle del viaje, para que la línea de la cuenta se entienda sola.

    Mismo contenido que el `fletectacte_tipo_mov` del legado —origen, destino,
    cantidad, tipo y remito— pero en `descripcion`, que es `Text`. En el legado
    esa columna era `varchar(50)` y **MySQL la truncaba en silencio**: hay 551
    filas cortadas en la base del cliente, y el final de la cadena no está en
    ningún lado.
    """
    origen = _nombre(sesion, Localidad, orden.origen_id) or "?"
    destino = _nombre(sesion, Localidad, orden.destino_id) or "?"
    partes = [f"{origen} → {destino}"]
    if orden.cantidad is not None:
        cantidad = f"{orden.cantidad.normalize():f}"
        partes.append(f"{cantidad} {orden.unidad}" if orden.unidad else cantidad)
    elif orden.cantidad_legado:
        partes.append(orden.cantidad_legado)
    tipo = _nombre(sesion, TipoCarga, orden.tipo_carga_id)
    if tipo:
        partes.append(tipo)
    if orden.remito:
        partes.append(f"remito {orden.remito}")
    return " · ".join(partes)


def cargo_de(sesion: Session, orden: OrdenCarga) -> MovimientoCuenta | None:
    """El cargo vigente de esta orden en la cuenta de un fletero, si existe.

    Se filtra por rol **y** por `debe > 0`: del mismo `orden_id` pueden colgar
    el asiento del cliente —en las órdenes migradas— y el contraasiento de una
    anulación, y ninguno de los dos es el cargo.
    """
    return sesion.scalar(
        select(MovimientoCuenta)
        .where(MovimientoCuenta.orden_id == orden.id,
               MovimientoCuenta.rol == RolCuenta.FLETERO,
               MovimientoCuenta.debe > CERO)
        .order_by(MovimientoCuenta.id)
    )


def sincronizar_comision(sesion: Session, orden: OrdenCarga) -> None:
    """Deja la cuenta del fletero diciendo lo que la orden dice ahora.

    Crea el asiento, lo corrige o lo saca. **No hace `commit`**: la llama quien
    ya tiene la transacción abierta, para que el asiento y la orden entren
    juntos o no entre ninguno — el defecto del legado era justamente que eran
    `INSERT` sueltos, y si el segundo fallaba el primero ya estaba grabado.

    El asiento sigue a la orden también cuando la orden vino de la migración.
    La alternativa —no tocar lo migrado— deja la orden diciendo un importe y la
    cuenta otro, sin nada que lo delate; y editar una orden puntual es una
    decisión explícita de una persona, que además queda en el log.
    """
    existente = cargo_de(sesion, orden)
    corresponde = (
        orden.fletero_id is not None
        and orden.comision > CERO
        and orden.estado is not EstadoOrden.ANULADA
    )

    if not corresponde:
        if existente is not None:
            # Se borra y no se pone en cero: el CHECK `ck_cuenta_debe_o_haber`
            # rechaza un asiento con las dos columnas en cero, y con razón —
            # una línea de $0 en una cuenta corriente no significa nada.
            sesion.delete(existente)
        return

    if existente is None:
        sesion.add(MovimientoCuenta(
            fecha=orden.fecha,
            tercero_id=orden.fletero_id,
            rol=RolCuenta.FLETERO,
            concepto=f"Flete orden {orden.id}",
            descripcion=describir(sesion, orden),
            debe=orden.comision,
            haber=CERO,
            orden_id=orden.id,
        ))
        return

    existente.fecha = orden.fecha
    existente.tercero_id = orden.fletero_id
    existente.descripcion = describir(sesion, orden)
    existente.debe = orden.comision


def revertir_comision(sesion: Session, orden: OrdenCarga) -> None:
    """Contraasiento por anulación, con la fecha de la orden.

    La fecha es la de la orden y no la de hoy por lo mismo que en la anulación
    de un comprobante: con la fecha de hoy, la cuenta mostraría entre el cargo y
    su reversión una deuda que ningún total del período reconoce.
    """
    existente = cargo_de(sesion, orden)
    if existente is None or existente.debe <= CERO:
        return
    sesion.add(MovimientoCuenta(
        fecha=orden.fecha,
        tercero_id=existente.tercero_id,
        rol=RolCuenta.FLETERO,
        concepto=f"Anulación orden {orden.id}",
        descripcion=existente.descripcion,
        debe=CERO,
        haber=existente.debe,
        orden_id=orden.id,
    ))
