"""Totales de comprobantes, contados por los dos lados a propósito.

El criterio de F5 en el ROADMAP es que **los totales por razón social sean
reproducibles**. Reproducible quiere decir que el mismo número salga de dos
lugares distintos: de los encabezados de los comprobantes, y de las órdenes que
esos comprobantes agrupan.

Es el mismo criterio de F4 aplicado a otra cosa. Si los dos lados coinciden, el
total no depende de dónde se lo miró; si difieren, hay un importe que está en
una razón social por un lado y en otra por el otro —o un encabezado que dice
algo que sus órdenes no dicen—. En el legado esa comparación no se podía hacer:
`orden_carga.carga_razonsocial` y `facturas.factura_razonsocial` son dos enteros
sin tabla ni clave foránea que los ate.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

from libracore import pdf_generator
from libracore.db import arca_config as db_arca_config
from libracore.db import facturas as db_facturas
from libracore.db.migraciones import conexion_libracore
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.models.enums import CODIGO_ARCA, TipoComprobante
from app.models.maestros import RazonSocial, Tercero
from app.models.operacion import Comprobante, ComprobanteCargo, OrdenCarga
from app.schemas.comprobantes import (
    NOMBRES_DE_TIPO,
    SumaDeOrdenes,
    TotalDeRazonSocial,
)
from app.servicios.emision_arca import CODIGO_IVA_DE_LA_FAMILIA, ArcaAmbiguo

log = logging.getLogger(__name__)

CERO = Decimal("0.00")

#: Las notas de crédito (de factura y de FCE). No **suman** a lo facturado: lo **restan**, y sólo
#: mientras su original sigue vigente (ver `acreditado_por_notas`).
TIPOS_NOTA = frozenset({
    TipoComprobante.NOTA_CREDITO_A,
    TipoComprobante.NOTA_CREDITO_B,
    TipoComprobante.NOTA_CREDITO_C,
    TipoComprobante.NOTA_CREDITO_FCE_A,
    TipoComprobante.NOTA_CREDITO_FCE_B,
    TipoComprobante.NOTA_CREDITO_FCE_C,
})


#: Las facturas FCE, que exigen vencimiento de pago.
TIPOS_FCE_FACTURA = frozenset({TipoComprobante.FCE_A, TipoComprobante.FCE_B, TipoComprobante.FCE_C})


def solo_facturas(consulta):
    """Saca las notas de crédito de una suma de lo facturado: las notas se **restan** aparte.

    Sumarlas haría subir lo facturado en vez de bajarlo. Lo que restan lo da `acreditado_por_notas`.
    """
    return consulta.where(Comprobante.tipo.notin_(TIPOS_NOTA))


def acreditado_por_notas(
    agrupar_por, desde: date | None = None, hasta: date | None = None, filtros=(),
) -> Select:
    """Lo que acreditan las notas de crédito **cuyo original sigue vigente**, agrupado por `agrupar_por`.

    Devuelve `(clave, cantidad, neto, iva, total)` por grupo; es lo que se **resta** de lo facturado (ADR-028).

    - 🔑 **Sólo cuentan las notas de un original no anulado.** Una nota total anula su original, y cuando las
      parciales suman el comprobante entero también (`cerrar_lo_propio`): ese original ya salió de los totales en
      todo el rango, y restar además sus notas lo descontaría dos veces. Así la nota total no suma ni resta, y no
      hace falta distinguirla de una parcial.
    - **El rango es el de la fecha de la nota**, no la del original: es un hecho fechado de ARCA, y es la fecha con la
      que entra al libro de ventas y a la cuenta corriente.
    - `agrupar_por` es una columna de la **nota** (`Comprobante.razon_social_id`, `Comprobante.cliente_id`…), y
      `filtros` pares `(columna, valor)` sobre ella; un valor `None` no filtra.
    """
    original = aliased(Comprobante)
    consulta = (
        select(
            agrupar_por,
            func.count(Comprobante.id),
            func.coalesce(func.sum(Comprobante.neto), 0),
            func.coalesce(func.sum(Comprobante.iva), 0),
            func.coalesce(func.sum(Comprobante.total), 0),
        )
        .select_from(Comprobante)
        # Toda nota tiene asociado y nada más lo tiene (`ck_comprobantes_nota_con_asociado`): el `join` ya las elige.
        .join(original, Comprobante.comprobante_asociado_id == original.id)
        .where(Comprobante.anulado.is_(False), original.anulado.is_(False))
        .group_by(agrupar_por)
    )
    for columna, valor in filtros:
        if valor is not None:
            consulta = consulta.where(columna == valor)
    return _acotar(consulta, desde, hasta)


def etiqueta(tipo: TipoComprobante, punto_venta: int, numero: int) -> str:
    """`Factura A 0001-00000123` — como se lee en un papel argentino.

    Se usa como concepto del movimiento de cuenta corriente: quien mira la
    cuenta tiene que poder encontrar el comprobante sin cruzar ids a mano.
    """
    return f"{NOMBRES_DE_TIPO[tipo]} {punto_venta:04d}-{numero:08d}"


def sumar_ordenes(ordenes: Iterable[OrdenCarga]) -> SumaDeOrdenes:
    """La suma de las órdenes, en `Decimal` de punta a punta.

    El neto de un comprobante es la suma de las **tarifas**, y el IVA la suma de
    los IVA de cada orden — no el IVA recalculado sobre el neto total. No es lo
    mismo: cada orden redondea su IVA a dos decimales, y aplicar la alícuota
    sobre la suma puede dar un centavo distinto. Sumando lo que ya está guardado,
    el total del comprobante es exactamente el de sus órdenes, y además admite
    órdenes con alícuotas distintas en la misma factura.
    """
    cantidad, neto, iva, total = 0, CERO, CERO, CERO
    for orden in ordenes:
        cantidad += 1
        neto += orden.tarifa
        iva += orden.iva
        total += orden.total
    return SumaDeOrdenes(cantidad=cantidad, neto=neto.quantize(CERO),
                         iva=iva.quantize(CERO), total=total.quantize(CERO))


def _acotar(consulta: Select, desde: date | None, hasta: date | None) -> Select:
    """El rango se aplica **siempre sobre la fecha del comprobante**.

    En los dos lados, aunque uno agregue órdenes: si el lado de las órdenes
    filtrara por la fecha de la orden, los dos conjuntos no serían el mismo y la
    diferencia diría "no coinciden" por el recorte, no por los datos.
    """
    if desde is not None:
        consulta = consulta.where(Comprobante.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(Comprobante.fecha <= hasta)
    return consulta


def totales_por_razon_social(
    sesion: Session, desde: date | None = None, hasta: date | None = None
) -> list[TotalDeRazonSocial]:
    """Los totales de cada razón social, por comprobantes y por órdenes.

    Los anulados quedan afuera de los dos lados: un comprobante anulado devuelve
    sus órdenes a pendientes, así que contarlo de un lado y no del otro
    reportaría una diferencia que no existe.

    🔑 **Las notas parciales se restan de los dos lados, por lo mismo** (ADR-028): acreditan plata sin tocar las
    órdenes, así que del lado de los comprobantes lo facturado baja y del lado de las órdenes también tiene que
    bajar —si no, cada nota parcial aparecería como una diferencia—. Los dos restan **el mismo** conjunto
    (`acreditado_por_notas`), así que la comparación sigue siendo la de los encabezados contra sus órdenes.
    `cantidad_comprobantes` cuenta facturas, no notas.
    """
    por_comprobante = _acotar(
        select(
            Comprobante.razon_social_id,
            func.count(Comprobante.id),
            func.coalesce(func.sum(Comprobante.neto), 0),
            func.coalesce(func.sum(Comprobante.iva), 0),
            func.coalesce(func.sum(Comprobante.total), 0),
        ).where(Comprobante.anulado.is_(False)).group_by(Comprobante.razon_social_id),
        desde, hasta,
    )
    por_comprobante = solo_facturas(por_comprobante)
    por_orden = _acotar(
        select(
            OrdenCarga.razon_social_id,
            func.count(OrdenCarga.id),
            func.coalesce(func.sum(OrdenCarga.tarifa), 0),
            func.coalesce(func.sum(OrdenCarga.iva), 0),
            func.coalesce(func.sum(OrdenCarga.total), 0),
        )
        .join(Comprobante, OrdenCarga.comprobante_id == Comprobante.id)
        .where(Comprobante.anulado.is_(False))
        .group_by(OrdenCarga.razon_social_id),
        desde, hasta,
    )

    lado_a = {fila[0]: fila[1:] for fila in sesion.execute(por_comprobante)}
    lado_b = {fila[0]: fila[1:] for fila in sesion.execute(por_orden)}
    notas = {fila[0]: fila[2:] for fila in sesion.execute(
        acreditado_por_notas(Comprobante.razon_social_id, desde, hasta))}

    salida = []
    # La unión de las dos claves, no la intersección: una razón social que
    # aparece de un solo lado es justamente el caso que hay que ver. Con un
    # `join` entre los dos agregados, esa fila desaparecería y la pantalla
    # mostraría todo en orden.
    for clave in sorted(set(lado_a) | set(lado_b) | set(notas), key=lambda k: (k is None, k or 0)):
        cant_c, neto_c, iva_c, total_c = lado_a.get(clave, (0, 0, 0, 0))
        cant_o, neto_o, iva_o, total_o = lado_b.get(clave, (0, 0, 0, 0))
        neto_n, iva_n, total_n = (Decimal(x) for x in notas.get(clave, (0, 0, 0)))
        neto_c, iva_c, total_c = (
            (Decimal(x) - n).quantize(CERO) for x, n in ((neto_c, neto_n), (iva_c, iva_n), (total_c, total_n)))
        neto_o, iva_o, total_o = (
            (Decimal(x) - n).quantize(CERO) for x, n in ((neto_o, neto_n), (iva_o, iva_n), (total_o, total_n)))
        salida.append(TotalDeRazonSocial(
            razon_social_id=clave,
            cantidad_comprobantes=cant_c,
            neto_comprobantes=neto_c, iva_comprobantes=iva_c, total_comprobantes=total_c,
            cantidad_ordenes=cant_o,
            neto_ordenes=neto_o, iva_ordenes=iva_o, total_ordenes=total_o,
            # Los tres importes, no sólo el total: un neto de más compensado por
            # un IVA de menos da el mismo total y es un error igual.
            coinciden=(neto_c, iva_c, total_c) == (neto_o, iva_o, total_o),
        ))
    return salida


# ── Escribir el comprobante: lo hace el motor ───────────────────────────────
#
# Desde la revisión `0016` el comprobante es una fila de `facturas` (ADR-030).
# Este producto no la escribe con su ORM: la crea, le guarda el CAE y la anula
# **el motor**, con las funciones que aceptan `conn=` (ADR-025 de LibraCore). Se
# les pasa la conexión de la sesión, así que todo pasa **en la transacción de
# acá**: el comprobante, las órdenes y la cuenta corriente siguen entrando o no
# entrando juntos (ADR-024). Lo único que escribe el ORM es `comprobantes_cargo`.


class NumeroRepetido(Exception):
    """El número ya está registrado para ese emisor, tipo y punto de venta."""


def _conexion_del_motor(sesion: Session):
    """La conexión de la sesión, como la espera `libracore.db`. Antes, lo pendiente a la base:
    el motor lee y escribe por SQL y no ve lo que el ORM todavía no mandó."""
    sesion.flush()
    return conexion_libracore(sesion.connection())


def emisor_de(sesion: Session, razon_social_id: int) -> int | None:
    """El emisor del motor (`arca_config.id`) de esta razón social, o `None` (el emisor único).

    Es la fila de ARCA de **su CUIT** (`config_por_cuit`), la misma guarda que decide si
    emite (`emision_arca.configuracion_activa`). Sin CUIT, o sin fila de ese CUIT, el
    comprobante es del emisor único de la instancia, que es lo que hay hoy en Suitrans.
    """
    razon = sesion.get(RazonSocial, razon_social_id)
    if razon is None:
        return None
    try:
        cfg = db_arca_config.config_por_cuit(razon.cuit)
    except db_arca_config.ArcaAmbiguo as e:
        raise ArcaAmbiguo(str(e)) from None
    return cfg["id"] if cfg else None


def _cliente(sesion: Session, cliente_id: int) -> dict:
    """Los datos fiscales del receptor, copiados al comprobante como hace el motor al emitir."""
    tercero = sesion.get(Tercero, cliente_id)
    if tercero is None:
        return {"cliente_cuit": "", "cliente_razon": "", "cliente_iva_cond": 0}
    return {
        "cliente_cuit": tercero.cuit or "",
        "cliente_razon": tercero.razon_social,
        "cliente_iva_cond": CODIGO_IVA_DE_LA_FAMILIA.get(tercero.condicion_iva, 0),
    }


def items_de(ordenes: Iterable[OrdenCarga]) -> list[dict]:
    """Un ítem por orden, con la forma de ítem de la familia (la que lee el PDF del motor)."""
    return [{
        "description": "Flete",
        "detalle": f"Orden {o.id} del {o.fecha:%d/%m/%Y}" + (f", remito {o.remito}" if o.remito else ""),
        "qty": 1, "unit_price": float(o.tarifa), "subtotal": float(o.tarifa),
        "iva_pct": float(o.alicuota_iva),
    } for o in ordenes]


def crear(
    sesion: Session, *, razon_social_id: int, tipo: TipoComprobante, punto_venta: int,
    numero: int, fecha: date, cliente_id: int, neto: Decimal, iva: Decimal, total: Decimal,
    items: list[dict], ambiente: str | None = None, fch_vto_pago: date | None = None,
    fce_cbu: str | None = None, fce_transmision: str | None = None,
    asociado: Comprobante | None = None, motivo: str | None = None,
) -> Comprobante:
    """Crea el comprobante en `facturas` y su fila de `comprobantes_cargo`. No hace `commit`.

    - **Sin `ambiente`, se registra**: el número lo tipeó una persona y el motor no lo
      cambia (`registrar_comprobante`, ADR-024). Si ya está, `NumeroRepetido`.
    - **Con `ambiente`, se emite**: el número es el que dio ARCA. El motor lo crea en ese
      ambiente (`create_factura`). Si ese número ya estaba tomado acá, el motor elegiría
      otro, y ARCA rechazaría el CAE de un número que no es el suyo: se dice antes,
      con `NumeroRepetido`.
    """
    # Las reglas que la tabla vieja tenía como CHECK y `facturas` no tiene: se dicen acá,
    # que es la única puerta de entrada de un comprobante de este producto.
    if tipo in TIPOS_FCE_FACTURA and fch_vto_pago is None:
        raise ValueError("una FCE sin fecha de vencimiento de pago no existe: ARCA la rechaza (10163)")
    if (tipo in TIPOS_NOTA) != (asociado is not None):
        raise ValueError("toda nota de credito acredita a un comprobante, y nada mas lo hace")
    if min(neto, iva, total) < 0:
        raise ValueError("los importes de un comprobante no son negativos: el tipo dice el signo")
    conn = _conexion_del_motor(sesion)
    codigo = CODIGO_ARCA[tipo]
    campos = {
        **_cliente(sesion, cliente_id),
        "items": items, "subtotal": neto, "iva_amount": iva, "total": total,
    }
    opcionales = {
        "observaciones": motivo or "",
        "fch_vto_pago": fch_vto_pago.isoformat() if fch_vto_pago else "",
        "fce_cbu": fce_cbu or "", "fce_transmision": fce_transmision or "",
    }
    if asociado is not None:
        opcionales.update({
            "cbte_asoc_tipo": CODIGO_ARCA[asociado.tipo], "cbte_asoc_pv": asociado.punto_venta,
            "cbte_asoc_nro": asociado.numero, "cbte_asoc_fecha": asociado.fecha.strftime("%Y%m%d"),
        })
    emisor = emisor_de(sesion, razon_social_id)
    if ambiente is None:
        try:
            factura_id = db_facturas.registrar_comprobante(
                codigo, punto_venta, numero, fecha.isoformat(), **campos,
                emisor_id=emisor, conn=conn, **opcionales)
        except db_facturas.NumeroYaRegistrado:
            raise NumeroRepetido(
                f"ya hay un {etiqueta(tipo, punto_venta, numero)} registrado") from None
    else:
        factura_id = db_facturas.create_factura(
            codigo, punto_venta, numero, fecha.isoformat(), campos["cliente_cuit"],
            campos["cliente_razon"], campos["cliente_iva_cond"], items, neto, iva, total,
            ambiente=ambiente, emisor_id=emisor, conn=conn, **opcionales)
        if db_facturas.get_factura(factura_id, conn=conn)["numero"] != numero:
            raise NumeroRepetido(
                f"ARCA dio el {etiqueta(tipo, punto_venta, numero)}, y ese número ya está "
                "registrado acá: revisá los comprobantes cargados a mano")
    sesion.add(ComprobanteCargo(
        factura_id=factura_id, razon_social_id=razon_social_id, cliente_id=cliente_id,
        anulado=False, comprobante_asociado_id=asociado.id if asociado is not None else None,
    ))
    sesion.flush()
    return sesion.get(Comprobante, factura_id)


def guardar_cae(sesion: Session, comprobante: Comprobante, cae: str, cae_vto: str | None) -> Comprobante:
    """Guarda el CAE que dio ARCA (`cae_vto` como lo devuelve ARCA, `AAAAMMDD`). No hace `commit`."""
    conn = _conexion_del_motor(sesion)
    db_facturas.update_factura_cae(comprobante.id, cae, cae_vto or "", conn=conn)
    comprobante.cae_solicitado_en = datetime.now(UTC)
    sesion.flush()
    sesion.expire(comprobante)
    return comprobante


def anular(sesion: Session, comprobante: Comprobante, usuario_id: int | None,
           motivo: str = "") -> Comprobante:
    """Anula un comprobante **sin CAE**: queda con su número, fuera de los libros y de los totales.

    El rastro (cuándo, quién y por qué) lo deja el motor (`anular_factura`, ADR-022 de
    LibraCore), que además lo saca del libro IVA. Lo propio —las órdenes y la cuenta
    corriente— lo hace quien llama. No hace `commit`.
    """
    conn = _conexion_del_motor(sesion)
    db_facturas.anular_factura(comprobante.id, usuario_id, motivo, conn=conn)
    comprobante.anulado = True
    sesion.flush()
    sesion.expire(comprobante)
    return comprobante


def guardar_pdf(sesion: Session, comprobante: Comprobante) -> str | None:
    """Genera el PDF del comprobante y guarda su ruta en `facturas.pdf_path`. Devuelve la ruta, o `None` si falló.

    🔑 **Se llama DESPUÉS del `commit` de la emisión, y un fallo no la deshace.** Cuando esto corre, ARCA ya
    autorizó el comprobante y la transacción ya lo guardó: revertirlo por un PDF que no salió dejaría a ARCA con
    una factura que acá no existe. Es el criterio del motor, que en su propio router genera el PDF recién
    después de guardar el CAE (y si el PDF falla, el comprobante queda con CAE). Acá además no corta la
    respuesta: el error se loguea, `pdf_path` queda vacío y el PDF se arma al vuelo la primera vez que se pide
    (`build_comprobantes_pdf_router`), con el emisor de ese día.

    Lo que se guarda es **lo que salió**: con el emisor y el logo del momento de emitir. El endpoint no lo
    regenera mientras el archivo esté en disco, aunque después cambie el logo o el domicilio de la empresa.

    El emisor lo resuelve el resolvedor registrado (`servicios.emisor_del_pdf`), que lee la base en su propia
    sesión: por eso tiene que correr con la emisión ya commiteada.
    """
    try:
        conn = _conexion_del_motor(sesion)
        factura = db_facturas.get_factura(comprobante.id, conn=conn)
        ruta = pdf_generator.generate_pdf_factura(factura)
        db_facturas.update_factura_pdf_path(comprobante.id, ruta, conn=conn)
        sesion.commit()
        return ruta
    except Exception:
        sesion.rollback()
        log.exception("no se pudo generar el PDF del comprobante %s; se arma al pedirlo", comprobante.id)
        return None
