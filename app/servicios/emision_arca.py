"""Emitir el comprobante ante ARCA y traerle el CAE.

Cierra F8. Hasta acá este producto **registraba**: el número lo tipeaba una
persona y no había nada fiscal de por medio.

## Qué se reusa del motor y qué no

Del motor sale la capa de protocolo —`arca_wsaa` y `arca_wsfe`— y, desde el
2026-09-02, también **dónde viven las credenciales**: `arca_config` y
`CERTS_DIR`, las mismas que usan los otros productos de la familia. Lo que
sigue siendo de acá es el documento: `libracore.arca_facturacion` está atado a
**su** esquema de `facturas`, y en este producto el comprobante además mueve
cuenta corriente y cierra órdenes de carga. Eso es la etapa siguiente.

El par ya no se pasa en bytes: se pasan los **paths** que resuelve
`arca_credenciales.paths_en_disco()`, que es la única función de la familia que
sabe encadenar "de qué ambiente es el par" con "dónde está ese archivo
realmente". Encadenarlo a mano es cómo una instancia de homologación termina
firmando con el certificado real del cliente.

## 🔑 El número lo da ARCA, no la persona

Es el cambio de fondo, y no admite convivencia dentro de un mismo comprobante:
ARCA numera correlativamente por punto de venta y tipo, y rechaza cualquier
número que no sea `FECompUltimoAutorizado + 1`. Un número tipeado a mano que
coincida es casualidad; uno que no, es un rechazo.

⚠️ **El alta manual no desaparece de golpe.** Sigue siendo el camino de la razón
social que **todavía no tiene ARCA configurado** — que hoy son todas, porque
`arca_config` está vacía en las tres instancias. Aplicar el cambio de forma
literal dejaría a la instancia del cliente sin poder facturar, que es una
regresión sobre un sistema vivo. En cuanto se carga el par y la razón social es
la del CUIT del certificado, su alta pasa a emitir y el número deja de pedirse.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

from libracore import arca_credenciales, arca_wsaa, arca_wsfe
from libracore.db import arca_config as db_arca_config
from sqlalchemy.orm import Session

from app.models.enums import TipoComprobante
from app.models.maestros import RazonSocial, Tercero
from app.models.operacion import Comprobante

#: El slug con el que esta instancia da de alta su fila en `arca_config`.
#:
#: Se define una vez y `app/main.py` lo importa para su `empresa_por_defecto`.
#: **No es que la emisión lo lea** —`configuracion_de_la_instancia()` resuelve
#: la fila activa, a propósito—: es que dos literales distintos hacen que el
#: `PUT` de la pantalla y el upload creen **dos filas**, y ahí ya no hay con qué
#: elegir. El router compartido no las unifica: `guardar()` usa el slug del
#: payload derecho y sólo cae en la fila activa cuando llega vacío. Hay un test
#: que fija las dos mitades de esto.
#:
#: (En los cuatro productos que sí leen por slug fijo, el desacuerdo es la falla
#: muda que documenta `build_arca_router`: pantalla que dice "Guardado" y
#: facturación que dice "ARCA no está configurado". Acá no puede pasar.)
EMPRESA_ARCA = "agencia"

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
    """La razón social no tiene el par cargado, o el par no es de su CUIT."""


class ArcaAmbiguo(RuntimeError):
    """Hay más de una configuración de ARCA y no se puede elegir sola.

    🔴 **Existe para NO caer en la primera.** `libracore.arca_facturacion` hace
    `arca_cfg[0]` porque los productos que lo usan son de instancia única con
    una sola empresa; este modela N razones sociales. Con dos filas, elegir por
    índice factura con el CUIT equivocado **sin fallar** — el comprobante sale,
    lo firma otro contribuyente, y se descubre en el libro IVA de un tercero.

    Que sea imposible configurar la segunda es la guarda de la pantalla; ésta es
    la del camino de emisión, que es el que hace daño. Las dos existen porque la
    fila se puede crear por fuera de la pantalla — un script, un `curl`, un
    restore de otra instancia.
    """


class ArcaRechazo(RuntimeError):
    """ARCA contestó, y dijo que no. El mensaje va tal cual a la pantalla."""


def _solo_digitos(cuit: str | None) -> str:
    """El CUIT comparable.

    `razones_sociales.cuit` es `String(13)` porque admite la forma con guiones
    (`20-12345678-9`), y en `arca_config` se carga como lo tipea quien configura
    la pantalla compartida. Comparar los textos crudos haría que el mismo CUIT
    escrito de las dos formas **no** matchee, y el síntoma sería el peor de los
    dos posibles: la razón social correcta deja de emitir y vuelve al alta
    manual, en silencio.
    """
    return "".join(c for c in (cuit or "") if c.isdigit())


def configuracion_de_la_instancia() -> dict | None:
    """La fila de `arca_config`, o `None` si esta instancia todavía no facturó.

    Se resuelve **igual que el `GET` de la pantalla** —la fila activa, no el
    slug— para que configurar y emitir no puedan leer filas distintas. El slug
    de `EMPRESA_ARCA` es con el que se **crea**; una vez creada, mandan los
    datos.
    """
    configs = db_arca_config.obtener_todas_arca_configs()
    if not configs:
        return None
    if len(configs) > 1:
        raise ArcaAmbiguo(
            "hay {} configuraciones de ARCA activas ({}) y este producto no "
            "sabe cuál usar: el motor elige por índice y eso factura con el "
            "CUIT equivocado sin fallar. Dejá una sola.".format(
                len(configs), ", ".join(c["empresa"] for c in configs))
        )
    return configs[0]


def _par_completo(cfg: dict) -> bool:
    """Si el par del ambiente **del selector** está los dos archivos en disco.

    Un par a medias no factura, y no hace falta que lo descubra ARCA: la mitad
    que falta se ve acá.
    """
    cert, clave = arca_credenciales.paths_en_disco(cfg)
    return bool(cert) and bool(clave) and os.path.exists(cert) and os.path.exists(clave)


def configuracion_activa(sesion: Session, razon_social_id: int) -> dict | None:
    """La configuración de ARCA **si esta razón social puede emitir con ella**.

    🔑 **El CUIT es la guarda, y no una bandera.** El certificado de ARCA es de
    un CUIT; `arca_config.cuit` dice de cuál. Una razón social con otro CUIT no
    puede emitir con ese par —ARCA lo rechazaría— así que sigue registrando a
    mano, que es exactamente el comportamiento que tenía antes con
    `habilitado=False`.

    Expresarlo con los datos y no con un flag es lo que hace que la regla
    degrade sola el día que el motor sepa llevar un par por empresa: ahí deja de
    haber una sola fila y esta función busca la del CUIT, sin que nadie tenga
    que acordarse de apagar una bandera.
    """
    cfg = configuracion_de_la_instancia()
    if cfg is None:
        return None
    razon = sesion.get(RazonSocial, razon_social_id)
    if razon is None or not _solo_digitos(razon.cuit):
        return None
    if _solo_digitos(razon.cuit) != _solo_digitos(cfg.get("cuit")):
        return None
    return cfg if _par_completo(cfg) else None


def emite_por_arca(sesion: Session, razon_social_id: int) -> bool:
    """Si el alta de esta razón social tiene que emitir en vez de registrar."""
    return configuracion_activa(sesion, razon_social_id) is not None


def es_ensayo(cfg: dict | None) -> bool:
    """Si lo que se va a emitir con esta configuración **no es del cliente**.

    Un comprobante contra homologación trae CAE y numeración del WSFE de
    homologación: no es un comprobante, es la prueba de que el camino funciona.
    En este producto además no es inocuo guardarlo — el comprobante mueve la
    cuenta corriente y cierra las órdenes de carga—, así que el alta se corre
    entera y se **revierte**. Ver `facturar` en `app/routers/comprobantes.py`.

    🔑 **Sale del `ambiente` de la MISMA config con la que se pidió el número**,
    no de una lectura nueva. Dos lecturas dejarían la decisión de guardar o no
    apoyada en un selector que pudo moverse en el medio — y las dos direcciones
    duelen: revertir un comprobante real, o guardar uno de prueba.
    """
    return (cfg or {}).get("ambiente") == "homologacion"


async def numero_que_sigue(
    sesion: Session, razon_social_id: int, tipo: TipoComprobante
) -> tuple[int, dict, dict, RazonSocial]:
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
            "y la clave en Configuracion, con el CUIT de esta razon social"
        )
    razon = sesion.get(RazonSocial, razon_social_id)
    if razon is None or not razon.cuit:
        raise ArcaNoConfigurado(
            "la razon social no tiene CUIT cargado, y ARCA factura contra un CUIT"
        )

    ambiente = cfg["ambiente"]
    # 🔑 Una sola llamada y no el baile de dos pasos —"de qué ambiente es el
    # par" y "dónde está ese archivo"—: separados, el segundo deshace al
    # primero. El rescate cae a un nombre fijo, así que sin saber el ambiente
    # cae al de **producción** y repone las credenciales reales que el primer
    # paso justamente no quería entregar.
    cert_path, clave_path = arca_credenciales.paths_en_disco(cfg)
    try:
        ta = await arca_wsaa.autenticar(cert_path, clave_path, ambiente)
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
    cfg: dict, razon: RazonSocial,
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
            factura, razon.cuit, ta["token"], ta["sign"], cfg["ambiente"],
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
