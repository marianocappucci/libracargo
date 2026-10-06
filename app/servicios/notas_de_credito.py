"""La nota de crédito de LibraCargo: **las costuras** de `libracore.notas_de_credito`.

La nota de crédito no es de este producto: sale del motor y es la misma para los siete que emiten por ARCA
(ADR-014 de `libracore`, ADR-027 de acá). Qué nota corresponde, las guardas —una factura se acredita una vez,
el CUIT del receptor, un solo pedido a la vez—, el armado con el comprobante asociado y el orden *numerar →
registrar → pedir CAE* viven allá. **Este módulo no repite nada de eso.** Lo único que aporta es lo que depende
del modelo de acá:

- cómo se carga el comprobante a acreditar y sus notas previas (`comprobantes`);
- dónde se guarda la nota (una fila más de `comprobantes`, en positivo, con `comprobante_asociado_id`);
- qué pasa con lo propio cuando se acredita: la **cuenta corriente** del cliente recibe el abono de cada nota, y
  cuando el comprobante queda acreditado **por completo** —con una nota total o con parciales que suman su total—
  **las órdenes vuelven a pendientes** (ADR-028).

Si falta una guarda o una regla de la nota, se agrega en el motor y llega a todos por el bump de pin; no se escribe
acá (`reglas/producto.md` del wiki: el arreglo de fondo vive siempre en el motor).
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from libracore import notas_de_credito as motor
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cuentas import MovimientoCuenta
from app.models.enums import CODIGO_ARCA, TIPO_DE_CODIGO, EstadoOrden, RolCuenta
from app.models.maestros import Tercero
from app.models.operacion import Comprobante, OrdenCarga
from app.servicios import comprobantes, emision_arca
from app.servicios.comprobantes import etiqueta

log = logging.getLogger(__name__)



def _en_forma_del_motor(sesion: Session, comprobante: Comprobante) -> dict:
    """El comprobante con las claves que usa toda la familia (`tipo`, `punto_venta`, `cliente_cuit`…)."""
    tercero = sesion.get(Tercero, comprobante.cliente_id)
    neto, iva = Decimal(comprobante.neto), Decimal(comprobante.iva)
    es_c = comprobante.tipo in emision_arca.TIPOS_C
    return {
        "tipo": CODIGO_ARCA[comprobante.tipo],
        "punto_venta": comprobante.punto_venta,
        "numero": comprobante.numero,
        "fecha": comprobante.fecha.isoformat(),
        "cliente_cuit": (tercero.cuit or "") if tercero else "",
        "cliente_razon": tercero.razon_social if tercero else "",
        "cliente_iva_cond": emision_arca._iva_cond_del_cliente(sesion, comprobante.cliente_id),
        # Los tipos C no discriminan IVA: todo va como neto (igual que `pedir_cae`).
        "subtotal": float(neto + iva) if es_c else float(neto),
        "iva_amount": 0.0 if es_c else float(iva),
        "total": float(comprobante.total),
        "cae": comprobante.cae,
    }


def _previas(sesion: Session, original_id: int) -> list[dict]:
    """Las notas que ya cuelgan del comprobante, **cualquiera sea su estado**.

    Cuenta también la que quedó sin CAE: esa ya tiene número, y lo que corresponde es resolverla, no pedir
    otra encima (la regla es del motor; acá sólo se las trae).
    """
    notas = sesion.scalars(
        select(Comprobante).where(Comprobante.comprobante_asociado_id == original_id)
    )
    # Con su `total`: es lo que el motor suma para el tope acumulado. Sin él contaría cada previa como el
    # comprobante entero, que es el comportamiento de la fase 1 (cualquier nota bloqueaba a la siguiente).
    return [{"tipo": CODIGO_ARCA[n.tipo], "punto_venta": n.punto_venta,
             "numero": n.numero, "cae": n.cae, "total": str(n.total)} for n in notas]


def notas_de(sesion: Session, original_id: int) -> list[Comprobante]:
    """Las notas de crédito que cuelgan de un comprobante, en el orden en que se emitieron."""
    return list(sesion.scalars(
        select(Comprobante).where(Comprobante.comprobante_asociado_id == original_id)
        .order_by(Comprobante.fecha, Comprobante.id)
    ))


def saldo(sesion: Session, original: Comprobante) -> tuple[Decimal, Decimal]:
    """`(acreditado, saldo_acreditable)` del comprobante. **La cuenta es del motor**; acá sólo se le pasa el modelo."""
    forma, previas = _en_forma_del_motor(sesion, original), _previas(sesion, original.id)
    return motor.acreditado(forma, previas), motor.saldo_acreditable(forma, previas)


async def emitir(
    sesion: Session, original: Comprobante, *, motivo: str, hoy: date, importe: Decimal | None = None,
) -> tuple[Comprobante, dict]:
    """Emite la nota de crédito de `original`: **total** sin `importe`, **parcial** con él (con IVA). Devuelve
    `(nota, cfg_de_arca)`. Lo propio lo cierra `cerrar_lo_propio`, después.

    **No hace `commit`**: lo hace quien llama, igual que `facturar`. Si ARCA rechaza (o cualquier paso falla),
    levanta y no queda nada; el `rollback` también es de quien llama.

    Levanta `NotaNoPermitida` (del motor) si la nota no corresponde, `ArcaNoConfigurado` si la razón social ya
    no puede emitir, y `ArcaRechazo` si ARCA dijo que no.
    """
    estado: dict = {}

    async def numerar(tipo_nota: int, _punto_venta: int):
        # El punto de venta de la nota es el de la razón social (`numero_que_sigue` lo lee de ahí), como
        # en `facturar`; el que viene del original es el mismo salvo que se haya cambiado después.
        numero, ta, cfg, razon = await emision_arca.numero_que_sigue(
            sesion, original.razon_social_id, TIPO_DE_CODIGO[tipo_nota])
        estado["cfg"] = cfg
        return numero, (ta, cfg, razon)

    def registrar(nota: dict, contexto) -> Comprobante:
        _ta, cfg, razon = contexto
        importes = _importes(original, nota)
        # La crea el motor en `facturas`, en el ambiente con el que se numeró y asociada a su
        # comprobante (ADR-030). Los importes son **los que armó el motor**: la nota total copia
        # los del original y la parcial reparte el importe con su alícuota (`repartir_importe`;
        # en una C todo es neto). Son los que van a ARCA, porque `pedir_cae` arma el pedido
        # desde esta fila.
        return comprobantes.crear(
            sesion, razon_social_id=original.razon_social_id, tipo=TIPO_DE_CODIGO[nota["tipo"]],
            # El punto de venta con el que se numeró, no el que traía el original.
            punto_venta=razon.punto_venta, numero=nota["numero"], fecha=hoy,
            cliente_id=original.cliente_id, **importes,
            items=[{"description": motivo or "Nota de credito", "qty": 1,
                    "unit_price": float(importes["neto"]), "subtotal": float(importes["neto"])}],
            ambiente=cfg["ambiente"], asociado=original, motivo=motivo,
        )

    async def pedir_cae(registro: Comprobante, nota: dict, contexto) -> Comprobante:
        ta, cfg, razon = contexto
        return await emision_arca.pedir_cae(sesion, registro, ta, cfg, razon, nota=nota)

    emitida = await motor.emitir_nota_de_credito(
        _en_forma_del_motor(sesion, original),
        clave=("comprobantes", original.id),
        cargar_previas=lambda: _previas(sesion, original.id),
        numerar=numerar, registrar=registrar, pedir_cae=pedir_cae,
        hoy=hoy, motivo=motivo, importe=importe,
    )
    return emitida.registro, estado["cfg"]


def _importes(original: Comprobante, nota: dict) -> dict:
    """`neto`, `iva` y `total` de la fila de la nota, a partir de lo que armó el motor.

    Si el motor copió el original (nota total) se guardan **los del original tal cual**: su `subtotal` de una C es
    `neto + iva`, y releerlo así cambiaría cómo está partida la fila. Si no, la nota es parcial y manda el motor.
    """
    total = Decimal(str(nota["total"])).quantize(Decimal("0.01"))
    if total == Decimal(original.total):
        return {"neto": original.neto, "iva": original.iva, "total": original.total}
    return {"neto": Decimal(str(nota["subtotal"])).quantize(Decimal("0.01")),
            "iva": Decimal(str(nota["iva_amount"])).quantize(Decimal("0.01")), "total": total}


def cerrar_lo_propio(sesion: Session, original: Comprobante, nota: Comprobante) -> list[OrdenCarga]:
    """Lo que pasa en este producto cuando se emite una nota. Devuelve las órdenes liberadas (vacío si no se liberó).

    - La **cuenta corriente** recibe siempre el abono **por el importe de la nota**, **con la fecha de la nota**:
      es un hecho fechado de ARCA. (Distinto de `anular`, que reversa un comprobante sin CAE con la fecha del
      original.)
    - 🔑 **Si con esta nota el comprobante queda acreditado por completo** —es una nota total, o las parciales ya
      suman su total— el original queda `anulado` (mismo significado que siempre, sin efecto contable; las notas lo
      referencian) y sus **órdenes vuelven a pendientes**, para refacturarlas: ARCA ya tiene la factura *y* notas por
      todo su importe, así que no hay dos facturas vigentes por lo mismo (decisión del humano, 2026-10-05).
    - Si queda saldo, las órdenes no se tocan: la nota acredita plata, no viajes (diferencia de kilos, bonificación).

    El saldo lo calcula el motor (`saldo_acreditable`) con la nota ya guardada.
    """
    _acreditado, queda = saldo(sesion, original)
    ordenes: list[OrdenCarga] = []
    if queda == 0:
        ordenes = list(sesion.scalars(
            select(OrdenCarga).where(OrdenCarga.comprobante_id == original.id)
            .order_by(OrdenCarga.fecha, OrdenCarga.id)
        ))
        for orden in ordenes:
            orden.comprobante_id = None
            orden.estado = EstadoOrden.PENDIENTE
        original.anulado = True
    sesion.add(MovimientoCuenta(
        fecha=nota.fecha, tercero_id=nota.cliente_id, rol=RolCuenta.CLIENTE,
        concepto=f"{etiqueta(nota.tipo, nota.punto_venta, nota.numero)} s/ "
                 f"{etiqueta(original.tipo, original.punto_venta, original.numero)}",
        descripcion=("Ordenes " + ", ".join(str(o.id) for o in ordenes)) if ordenes
                    else (nota.motivo or "Nota de credito parcial"),
        debe=0, haber=nota.total, comprobante_id=nota.id,
    ))
    return ordenes


def avisar_autorizada(nota: Comprobante, original: Comprobante) -> None:
    """Deja en el log lo que ARCA autorizó, **antes** del `commit`.

    Si el `commit` falla después de que ARCA autorizó, la nota existe allá y no acá. Este renglón es lo que
    permite reconstruirla; no reemplaza a una herramienta de conciliación (riesgo R1 del diseño).
    """
    log.warning(
        "nota de credito autorizada por ARCA: %s cae=%s sobre %s (comprobante %s)",
        etiqueta(nota.tipo, nota.punto_venta, nota.numero), nota.cae,
        etiqueta(original.tipo, original.punto_venta, original.numero), original.id,
    )
