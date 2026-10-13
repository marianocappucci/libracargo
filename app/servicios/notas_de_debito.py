"""La nota de débito de LibraCargo: **las costuras** de `libracore.notas_de_debito` (ADR-048).

Como la de crédito (`notas_de_credito.py`), la nota de débito no es de este producto: sale del motor y es la misma para
todos (ADR-049 de `libracore`). Qué nota corresponde (la letra y si es FCE se heredan: 2/7/12, 202/207/212), las
guardas —el original con CAE, el receptor, una previa sin CAE, un solo pedido a la vez— y el orden *numerar → registrar
→ pedir CAE* viven allá. **Este módulo no repite nada de eso.** Lo único que aporta es lo que depende del modelo de acá:

- dónde se guarda la nota (una fila más de `comprobantes`, en positivo, con `comprobante_asociado_id`);
- cuáles son las notas de débito previas del comprobante (`cargar_previas`);
- qué pasa con lo propio: la **cuenta corriente** del cliente recibe el **cargo** por el importe de la nota, con la
  fecha de la nota.

Qué la distingue de la de crédito, para este producto:

- **Suma, no resta**: la nota de débito agrega plata (intereses, un gasto, una diferencia de precio) y por eso no
  libera órdenes ni anula el original. Entra en lo facturado, pero no agrupa órdenes (`sin_ordenes`): el gate de F5
  no la cuenta.
- **No tiene tope ni saldo**: una factura admite todas las notas de débito que hagan falta.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from libracore import notas_de_debito as motor
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CODIGO_ARCA, TIPO_DE_CODIGO, RolCuenta
from app.models.operacion import Comprobante
from app.servicios import comprobantes, cuentas, emision_arca
from app.servicios.comprobantes import etiqueta
from app.servicios.notas_de_credito import _en_forma_del_motor

_CENTAVO = Decimal("0.01")


def notas_de(sesion: Session, original_id: int) -> list[Comprobante]:
    """Las notas de débito que cuelgan de un comprobante, en el orden en que se emitieron."""
    return list(sesion.scalars(
        select(Comprobante).where(Comprobante.comprobante_asociado_id == original_id,
                                  Comprobante.tipo.in_(comprobantes.TIPOS_DEBITO))
        .order_by(Comprobante.fecha, Comprobante.id)
    ))


def _previas(sesion: Session, original_id: int) -> list[dict]:
    """Las notas de débito del comprobante, **cualquiera sea su estado**: una sin CAE frena a la siguiente (ya tiene
    número, y lo que corresponde es resolverla; la regla es del motor)."""
    return [{"tipo": CODIGO_ARCA[n.tipo], "punto_venta": n.punto_venta, "numero": n.numero, "cae": n.cae,
             "total": str(n.total)} for n in notas_de(sesion, original_id)]


async def emitir(
    sesion: Session, original: Comprobante, *, motivo: str, hoy: date, importe: Decimal,
) -> tuple[Comprobante, dict]:
    """Emite la nota de débito de `original` por `importe` (con IVA). Devuelve `(nota, cfg_de_arca)`; lo propio lo
    cierra `cerrar_lo_propio`, después.

    **No hace `commit`**: lo hace quien llama, igual que `facturar`. Si ARCA rechaza (o cualquier paso falla), levanta y
    no queda nada; el `rollback` también es de quien llama.

    Levanta `NotaNoPermitida` (del motor) si la nota no corresponde, `ArcaNoConfigurado` si la empresa ya no puede
    emitir, y `ArcaRechazo` si ARCA dijo que no.
    """
    estado: dict = {}

    async def numerar(tipo_nota: int, _punto_venta: int):
        # El punto de venta de la nota es el de la configuración de ARCA (`numero_que_sigue` lo lee de ahí), como en
        # la factura y en la nota de crédito.
        numero, ta, cfg, emisor = await emision_arca.numero_que_sigue(sesion, TIPO_DE_CODIGO[tipo_nota])
        estado["cfg"] = cfg
        return numero, (ta, cfg, emisor)

    def registrar(nota: dict, contexto) -> Comprobante:
        _ta, cfg, emisor = contexto
        # Los importes son **los que armó el motor** (el IVA con la alícuota de la factura; en una C todo es neto): son
        # los que van a ARCA, porque `pedir_cae` arma el pedido desde esta fila.
        neto = Decimal(str(nota["subtotal"])).quantize(_CENTAVO)
        iva = Decimal(str(nota["iva_amount"])).quantize(_CENTAVO)
        total = Decimal(str(nota["total"])).quantize(_CENTAVO)
        return comprobantes.crear(
            sesion, tipo=TIPO_DE_CODIGO[nota["tipo"]],
            punto_venta=emisor.punto_venta, numero=nota["numero"], fecha=hoy,
            cliente_id=original.cliente_id, neto=neto, iva=iva, total=total,
            items=nota["items"], ambiente=cfg["ambiente"], asociado=original, motivo=motivo,
        )

    async def pedir_cae(registro: Comprobante, nota: dict, contexto) -> Comprobante:
        ta, cfg, emisor = contexto
        return await emision_arca.pedir_cae(sesion, registro, ta, cfg, emisor, nota=nota)

    emitida = await motor.emitir_nota_de_debito(
        _en_forma_del_motor(sesion, original),
        # Distinta de la clave de la nota de crédito del mismo comprobante: una en camino no frena a la otra.
        clave=("comprobantes-debito", original.id),
        importe=importe, motivo=motivo, hoy=hoy,
        cargar_previas=lambda: _previas(sesion, original.id),
        numerar=numerar, registrar=registrar, pedir_cae=pedir_cae,
        # 🔴 `conn=sesion`: el candado de la base dura hasta que ESTA transacción termina, así que nada de lo de arriba
        # hace `commit` ni `rollback` de la sesión mientras dura la emisión (mismo criterio que la nota de crédito).
        conn=sesion,
    )
    return emitida.registro, estado["cfg"]


def cerrar_lo_propio(sesion: Session, original: Comprobante, nota: Comprobante) -> None:
    """Lo que pasa en este producto cuando se emite una nota de débito: la **cuenta corriente** del cliente recibe el
    cargo por el importe de la nota, **con la fecha de la nota** (es un hecho fechado de ARCA).

    No toca las órdenes ni el original: la nota agrega plata, no cambia lo que se facturó.
    """
    cuentas.asentar(
        sesion,
        fecha=nota.fecha, tercero_id=nota.cliente_id, rol=RolCuenta.CLIENTE,
        concepto=f"{etiqueta(nota.tipo, nota.punto_venta, nota.numero)} s/ "
                 f"{etiqueta(original.tipo, original.punto_venta, original.numero)}",
        descripcion=nota.motivo or "Nota de debito",
        debe=nota.total, haber=Decimal(0), comprobante_id=nota.id,
    )
