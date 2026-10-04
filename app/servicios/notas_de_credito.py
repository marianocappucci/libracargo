"""La nota de crédito de LibraCargo: **las costuras** de `libracore.notas_de_credito`.

La nota de crédito no es de este producto: sale del motor y es la misma para los siete que emiten por ARCA
(ADR-014 de `libracore`, ADR-027 de acá). Qué nota corresponde, las guardas —una factura se acredita una vez,
el CUIT del receptor, un solo pedido a la vez—, el armado con el comprobante asociado y el orden *numerar →
registrar → pedir CAE* viven allá. **Este módulo no repite nada de eso.** Lo único que aporta es lo que depende
del modelo de acá:

- cómo se carga el comprobante a acreditar y sus notas previas (`comprobantes`);
- dónde se guarda la nota (una fila más de `comprobantes`, en positivo, con `comprobante_asociado_id`);
- qué pasa con lo propio cuando se acredita: **las órdenes vuelven a pendientes** y la **cuenta corriente** del
  cliente recibe el abono.

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
from app.models.enums import EstadoOrden, RolCuenta
from app.models.maestros import Tercero
from app.models.operacion import Comprobante, OrdenCarga
from app.servicios import emision_arca
from app.servicios.comprobantes import etiqueta

log = logging.getLogger(__name__)

#: Del código de ARCA al tipo de este producto (lo inverso de `CODIGO_ARCA`).
_TIPO_DE_CODIGO = {codigo: tipo for tipo, codigo in emision_arca.CODIGO_ARCA.items()}


def _en_forma_del_motor(sesion: Session, comprobante: Comprobante) -> dict:
    """El comprobante con las claves que usa toda la familia (`tipo`, `punto_venta`, `cliente_cuit`…)."""
    tercero = sesion.get(Tercero, comprobante.cliente_id)
    neto, iva = Decimal(comprobante.neto), Decimal(comprobante.iva)
    es_c = comprobante.tipo in emision_arca.TIPOS_C
    return {
        "tipo": emision_arca.CODIGO_ARCA[comprobante.tipo],
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
    return [{"tipo": emision_arca.CODIGO_ARCA[n.tipo], "punto_venta": n.punto_venta,
             "numero": n.numero, "cae": n.cae} for n in notas]


async def emitir(
    sesion: Session, original: Comprobante, *, motivo: str, hoy: date,
) -> tuple[Comprobante, dict]:
    """Emite la nota de crédito **total** de `original` y cierra lo propio. Devuelve `(nota, cfg_de_arca)`.

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
            sesion, original.razon_social_id, _TIPO_DE_CODIGO[tipo_nota])
        estado["cfg"] = cfg
        return numero, (ta, cfg, razon)

    def registrar(nota: dict, contexto) -> Comprobante:
        _ta, _cfg, razon = contexto
        registro = Comprobante(
            razon_social_id=original.razon_social_id, tipo=_TIPO_DE_CODIGO[nota["tipo"]],
            # El punto de venta con el que se numeró, no el que traía el original.
            punto_venta=razon.punto_venta, numero=nota["numero"], fecha=hoy,
            cliente_id=original.cliente_id,
            # Los importes del original, tal cual: una nota que anula dice lo mismo que anula.
            neto=original.neto, iva=original.iva, total=original.total,
            comprobante_asociado_id=original.id, motivo=motivo,
        )
        sesion.add(registro)
        sesion.flush()
        return registro

    async def pedir_cae(registro: Comprobante, nota: dict, contexto) -> Comprobante:
        ta, cfg, razon = contexto
        return await emision_arca.pedir_cae(sesion, registro, ta, cfg, razon, nota=nota)

    emitida = await motor.emitir_nota_de_credito(
        _en_forma_del_motor(sesion, original),
        clave=("comprobantes", original.id),
        cargar_previas=lambda: _previas(sesion, original.id),
        numerar=numerar, registrar=registrar, pedir_cae=pedir_cae,
        hoy=hoy, motivo=motivo,
    )
    return emitida.registro, estado["cfg"]


def cerrar_lo_propio(sesion: Session, original: Comprobante, nota: Comprobante) -> list[OrdenCarga]:
    """Lo que pasa en este producto cuando una factura queda acreditada. Devuelve las órdenes liberadas.

    - El original queda `anulado`: mismo significado que siempre, sin efecto contable; la nota lo referencia.
    - Sus **órdenes vuelven a pendientes** y se pueden refacturar: ARCA ya tiene la factura *y* su nota, así
      que no hay dos facturas vigentes por lo mismo.
    - La **cuenta corriente** recibe el abono por el importe de la nota, **con la fecha de la nota**: es un hecho
      fechado de ARCA. (Distinto de `anular`, que reversa un comprobante sin CAE con la fecha del original.)
    """
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
        descripcion="Ordenes " + ", ".join(str(o.id) for o in ordenes),
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
