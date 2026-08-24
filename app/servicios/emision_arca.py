"""Emitir el comprobante ante ARCA y traerle el CAE.

Cierra F8. Hasta acá este producto **registraba**: el número lo tipeaba una
persona y no había nada fiscal de por medio.

## Qué se reusa del motor y qué no

Del motor sale **la capa de protocolo** —`arca_wsaa` y `arca_wsfe`— y nada más.
`libracore.arca_facturacion` no sirve acá: está atado a **su** esquema de
`facturas` y `arca_config`, y este producto tiene el suyo, con la configuración
colgando de la razón social y el par guardado en la base. Lo dice ADR-020 y
sigue siendo cierto.

El par se pasa **en bytes**: `arca_wsaa.autenticar_con_bytes` existe para esto.

## 🔑 El número lo da ARCA, no la persona

Es el cambio de fondo, y no admite convivencia dentro de un mismo comprobante:
ARCA numera correlativamente por punto de venta y tipo, y rechaza cualquier
número que no sea `FECompUltimoAutorizado + 1`. Un número tipeado a mano que
coincida es casualidad; uno que no, es un rechazo.

⚠️ **El alta manual no desaparece de golpe.** Sigue siendo el camino de la razón
social que **todavía no tiene ARCA habilitado** — que hoy son todas, porque
`configuracion_arca` está vacía. Aplicar el cambio de forma literal dejaría a la
instancia del cliente sin poder facturar, que es una regresión sobre un sistema
vivo. En cuanto una razón social carga su par y lo habilita, su alta pasa a
emitir y el número deja de pedirse.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from libracore import arca_wsaa, arca_wsfe
from sqlalchemy.orm import Session

from app.models.configuracion_arca import ConfiguracionArca
from app.models.enums import TipoComprobante
from app.models.maestros import RazonSocial, Tercero
from app.models.operacion import Comprobante

#: El código que ARCA le da a cada tipo. No es un detalle de presentación: va
#: en `CbteTipo` del pedido de CAE, y equivocarlo emite otra cosa.
CODIGO_ARCA = {
    TipoComprobante.FACTURA_A: 1,
    TipoComprobante.FACTURA_B: 6,
    TipoComprobante.FACTURA_C: 11,
    TipoComprobante.NOTA_CREDITO_A: 3,
    TipoComprobante.NOTA_CREDITO_B: 8,
    TipoComprobante.NOTA_CREDITO_C: 13,
}

#: Los tipos C no llevan IVA discriminado: todo el importe va como neto y el
#: bloque de alícuotas **no se manda**. Lo exige ARCA, no es una simplificación.
TIPOS_C = {TipoComprobante.FACTURA_C, TipoComprobante.NOTA_CREDITO_C}


class ArcaNoConfigurado(RuntimeError):
    """La razón social no tiene el par cargado y habilitado."""


class ArcaRechazo(RuntimeError):
    """ARCA contestó, y dijo que no. El mensaje va tal cual a la pantalla."""


def configuracion_activa(sesion: Session, razon_social_id: int) -> ConfiguracionArca | None:
    """La configuración de esa razón social, **sólo si puede emitir**.

    `habilitado` no es lo mismo que "tiene los archivos": el `CHECK` de la tabla
    ya garantiza que no se pueda habilitar sin las dos mitades, pero cargarlas y
    no habilitar es un estado legítimo — el cliente subió el par y todavía no
    quiere emitir.
    """
    cfg = sesion.query(ConfiguracionArca).filter_by(
        razon_social_id=razon_social_id
    ).one_or_none()
    if cfg is None or not cfg.habilitado:
        return None
    return cfg


def emite_por_arca(sesion: Session, razon_social_id: int) -> bool:
    """Si el alta de esta razón social tiene que emitir en vez de registrar."""
    return configuracion_activa(sesion, razon_social_id) is not None


async def numero_que_sigue(
    sesion: Session, razon_social_id: int, tipo: TipoComprobante
) -> tuple[int, dict, ConfiguracionArca, RazonSocial]:
    """Le pregunta a ARCA cuál es el próximo número, y de paso autentica.

    Devuelve `(numero, ta, cfg, razon)` para que el llamador no tenga que
    autenticar dos veces: el ticket de acceso sirve para el pedido de CAE que
    viene después.

    ⚠️ **No hay fallback a numeración local.** Contalibra sí lo tiene, porque
    allá una factura sin CAE es un borrador que se reintenta. Acá el número
    **es** el de ARCA: inventar uno local y pedir el CAE después con ese número
    da un rechazo garantizado.
    """
    cfg = configuracion_activa(sesion, razon_social_id)
    if cfg is None:
        raise ArcaNoConfigurado(
            "esta razon social no tiene ARCA habilitado: cargá el certificado "
            "y la clave en Configuracion y activalo"
        )
    razon = sesion.get(RazonSocial, razon_social_id)
    if razon is None or not razon.cuit:
        raise ArcaNoConfigurado(
            "la razon social no tiene CUIT cargado, y ARCA factura contra un CUIT"
        )

    ambiente = cfg.ambiente.value
    try:
        ta = await arca_wsaa.autenticar_con_bytes(cfg.certificado, cfg.clave, ambiente)
        ultimo = await arca_wsfe.ultimo_numero_autorizado(
            razon.punto_venta, CODIGO_ARCA[tipo], razon.cuit,
            ta["token"], ta["sign"], ambiente,
        )
    except Exception as e:
        # El texto de ARCA va tal cual: distingue "el certificado no esta
        # habilitado para wsfe" de "la hora del servidor esta corrida", y las
        # dos se arreglan en lugares distintos.
        raise ArcaRechazo(str(e)) from None
    return ultimo + 1, ta, cfg, razon


async def pedir_cae(
    sesion: Session, comprobante: Comprobante, ta: dict,
    cfg: ConfiguracionArca, razon: RazonSocial,
) -> Comprobante:
    """Pide el CAE del comprobante ya creado y lo guarda.

    Se llama **con el ticket que ya se usó para numerar**: pedir uno nuevo entre
    el número y el CAE abre la ventana para que otro comprobante se meta en el
    medio y el número quede tomado.
    """
    neto = Decimal(comprobante.neto)
    iva = Decimal(comprobante.iva)
    es_c = comprobante.tipo in TIPOS_C

    factura = {
        "tipo": CODIGO_ARCA[comprobante.tipo],
        "punto_venta": comprobante.punto_venta,
        "numero": comprobante.numero,
        "fecha": comprobante.fecha.isoformat(),
        # Concepto 1 = Productos. Un flete es un servicio prestado y cerrado en
        # el momento; el concepto 2 obligaria a mandar fechas de servicio que
        # este producto no tiene.
        "concepto": 1,
        # Por id y no por relacion: `Comprobante` guarda `cliente_id` y no tiene
        # un `relationship` --- este modelo evita las relaciones cargadas para
        # que un listado no dispare un N+1 sin que nadie lo pida.
        "cliente_cuit": _cuit_del_cliente(sesion, comprobante.cliente_id),
        "subtotal": float(neto + iva) if es_c else float(neto),
        "iva_amount": 0.0 if es_c else float(iva),
        "total": float(comprobante.total),
    }
    try:
        datos = await arca_wsfe.solicitar_cae(
            factura, razon.cuit, ta["token"], ta["sign"], cfg.ambiente.value,
        )
    except Exception as e:
        raise ArcaRechazo(str(e)) from None

    comprobante.cae = datos["cae"]
    comprobante.cae_vencimiento = _fecha_de(datos.get("cae_vto"))
    comprobante.cae_solicitado_en = datetime.now(UTC)
    sesion.flush()
    return comprobante


def _cuit_del_cliente(sesion: Session, cliente_id: int) -> str:
    """El CUIT del receptor, o vacío.

    Vacío es legítimo: un consumidor final no tiene CUIT y ARCA lo acepta en
    una factura B o C. Lo que no sería legítimo es inventarlo.
    """
    tercero = sesion.get(Tercero, cliente_id)
    return (tercero.cuit or "") if tercero else ""


def _fecha_de(crudo: str | None) -> date | None:
    """ARCA devuelve el vencimiento del CAE como `AAAAMMDD`, sin separadores."""
    if not crudo or len(crudo) != 8:
        return None
    try:
        return date(int(crudo[:4]), int(crudo[4:6]), int(crudo[6:]))
    except ValueError:
        return None
