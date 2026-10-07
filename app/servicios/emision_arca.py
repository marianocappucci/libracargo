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

## 🔑 Quién emite: la empresa, y sólo ella (ADR-035)

El emisor es **«Datos de la empresa»** (`configuracion_empresa`): su CUIT, su condición de IVA y su razón
social son los de todo comprobante. La configuración de ARCA (`arca_config`) es sólo lo técnico —certificado,
clave, **punto de venta** y ambiente—, y se emite únicamente si **su CUIT es el de la empresa**. Si no, se
dice cuál es el problema (`problema_de_emision`) y no se toca nada: facturar con el certificado de un CUIT
a nombre de otro es lo que esta guarda existe para impedir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from libracore import arca_credenciales, arca_wsaa, arca_wsfe
from libracore.db import arca_config as db_arca_config
from sqlalchemy.orm import Session

from app.models.configuracion import ConfiguracionEmpresa
from app.models.enums import CODIGO_ARCA, CondicionIVA, TipoComprobante
from app.models.maestros import Tercero
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

#: Los tipos C no llevan IVA discriminado: todo el importe va como neto y el
#: bloque de alícuotas **no se manda**. Lo exige ARCA, no es una simplificación.
TIPOS_C = {TipoComprobante.FACTURA_C, TipoComprobante.NOTA_CREDITO_C, TipoComprobante.FCE_C,
           TipoComprobante.NOTA_CREDITO_FCE_C}

#: La **factura** FCE lleva además el vencimiento de pago, el CBU del emisor y la modalidad
#: de transmisión. Los dos últimos salen de la configuración de ARCA de la instancia. Sus
#: notas no: llevan la marca de anulación, que arma el motor (`armar_nota`).
TIPOS_FCE = {TipoComprobante.FCE_A, TipoComprobante.FCE_B, TipoComprobante.FCE_C}


#: La condición de IVA del cliente, con el **código con que la familia la guarda**
#: en `cliente_iva_cond` (el `IVA_CODES` de `libracore`: 1 inscripto, 6
#: monotributista, 4 exento, 5 consumidor final). Desde la RG 5616 ARCA rechaza el
#: comprobante sin la condición del receptor, y es `libracore.arca_wsfe` quien la
#: traduce al id de ARCA a partir de este código.
#:
#: 🔑 **`0` es «no sé», y es a propósito.** Los clientes migrados de Suitrans traen
#: todos la misma condición (ver `migracion/transformar.py`) y los que no la
#: tenían quedaron como `no_categorizado`. Mandar `0` deja que el motor decida —o
#: falle con un mensaje que dice qué cargar— en lugar de inventar un dato fiscal.
CODIGO_IVA_DE_LA_FAMILIA = {
    CondicionIVA.RESPONSABLE_INSCRIPTO: 1,
    CondicionIVA.MONOTRIBUTO: 6,
    CondicionIVA.EXENTO: 4,
    CondicionIVA.CONSUMIDOR_FINAL: 5,
    CondicionIVA.NO_CATEGORIZADO: 0,
}


class ArcaNoConfigurado(RuntimeError):
    """La instancia no puede emitir: la empresa no tiene CUIT, falta el par de ARCA o es de otro CUIT.

    El mensaje (`problema_de_emision`) dice cuál de las tres y qué cargar, y va tal cual a la pantalla.
    """


class ArcaAmbiguo(RuntimeError):
    """Hay más de una configuración de ARCA y no se puede elegir sola.

    🔴 **Existe para NO caer en la primera.** `libracore.arca_facturacion` hace
    `arca_cfg[0]` porque los productos que lo usan son de instancia única con
    una sola empresa; este producto antes modelaba N razones sociales. Con dos filas, elegir por
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

    `configuracion_empresa.cuit` es `String(13)` porque admite la forma con guiones
    (`20-12345678-9`), y en `arca_config` se carga como lo tipea quien configura
    la pantalla compartida. Comparar los textos crudos haría que el mismo CUIT
    escrito de las dos formas **no** matchee, y la empresa correcta dejaría de
    poder emitir con un mensaje que dice que los CUIT difieren cuando son el mismo.
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


@dataclass(frozen=True)
class Emisor:
    """Con qué CUIT y en qué punto de venta se emite: el de la empresa y el de `arca_config`."""

    cuit: str
    punto_venta: int


def empresa_de(sesion: Session) -> ConfiguracionEmpresa | None:
    """«Datos de la empresa», la única fuente del emisor (ADR-035), o `None` si todavía no se cargó."""
    return sesion.get(ConfiguracionEmpresa, 1)


def _problema(sesion: Session, cfg: dict | None) -> str | None:
    """Por qué **esta configuración** no sirve para emitir con la empresa de la instancia, o `None`."""
    empresa = empresa_de(sesion)
    if empresa is None or not _solo_digitos(empresa.cuit):
        return ("la empresa no tiene CUIT cargado, y ARCA factura contra un CUIT: "
                "cargá el CUIT en Configuración → Datos de la empresa")
    if cfg is None:
        return (f"ARCA no está configurado: cargá el certificado y la clave en Configuración → ARCA, "
                f"con el CUIT de la empresa ({empresa.cuit})")
    if _solo_digitos(cfg.get("cuit")) != _solo_digitos(empresa.cuit):
        # 🔑 El CUIT de `arca_config` es el que FACTURA (el de la empresa), aunque el certificado esté a
        # nombre de otra persona que la representa (delegación). Nunca se compara contra el sujeto del
        # certificado: sólo contra lo que dice la configuración.
        return (f"el CUIT de la configuración de ARCA es {cfg.get('cuit') or '(vacío)'} y la empresa tiene "
                f"{empresa.cuit}: la configuración de ARCA lleva el CUIT que factura (el de la empresa), "
                "aunque el certificado esté a nombre de otra persona que la representa. "
                "Corregí uno de los dos en Configuración → ARCA o Datos de la empresa")
    if not _par_completo(cfg):
        return ("falta el certificado o la clave de ARCA del ambiente elegido: "
                "cargalos en Configuración → ARCA")
    return None


def problema_de_emision(sesion: Session) -> str | None:
    """Por qué esta instancia no puede emitir por ARCA, o `None` si puede (ADR-035).

    🔑 **El CUIT de la empresa es la guarda, y no una bandera.** Se emite sólo si hay una `arca_config` con
    el par completo y **su CUIT es el de «Datos de la empresa»**. Levanta `ArcaAmbiguo` con dos
    configuraciones: no se adivina con cuál firmar.
    """
    return _problema(sesion, configuracion_de_la_instancia())


def configuracion_activa(sesion: Session) -> dict | None:
    """La configuración de ARCA **si la empresa puede emitir con ella**, o `None`."""
    cfg = configuracion_de_la_instancia()
    return cfg if _problema(sesion, cfg) is None else None


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
    sesion: Session, tipo: TipoComprobante
) -> tuple[int, dict, dict, Emisor]:
    """Le pregunta a ARCA cuál es el próximo número, y de paso autentica.

    Devuelve `(numero, ta, cfg, emisor)` para que el llamador no tenga que
    autenticar dos veces: el ticket de acceso sirve para el pedido de CAE que
    viene después. El punto de venta es el de `arca_config`.

    Levanta `ArcaNoConfigurado` (con el motivo) si la empresa no puede emitir.

    ⚠️ **No hay fallback a numeración local.** Contalibra sí lo tiene, porque
    allá una factura sin CAE es un borrador que se reintenta. Acá el número
    **es** el de ARCA: inventar uno local y pedir el CAE después con ese número
    da un rechazo garantizado.
    """
    cfg = configuracion_de_la_instancia()
    problema = _problema(sesion, cfg)
    if problema is not None:
        raise ArcaNoConfigurado(problema)
    emisor = Emisor(cuit=empresa_de(sesion).cuit, punto_venta=int(cfg["punto_venta"]))

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
            emisor.punto_venta, CODIGO_ARCA[tipo], emisor.cuit,
            ta["token"], ta["sign"], ambiente,
        )
    except Exception as e:
        # El texto de ARCA va tal cual: distingue "el certificado no esta
        # habilitado para wsfe" de "la hora del servidor esta corrida", y las
        # dos se arreglan en lugares distintos.
        raise ArcaRechazo(str(e)) from None
    return ultimo + 1, ta, cfg, emisor


async def pedir_cae(
    sesion: Session, comprobante: Comprobante, ta: dict,
    cfg: dict, emisor: Emisor, nota: dict | None = None,
) -> Comprobante:
    """Pide el CAE del comprobante ya creado y lo guarda.

    Se llama **con el ticket que ya se usó para numerar**: pedir uno nuevo entre
    el número y el CAE abre la ventana para que otro comprobante se meta en el
    medio y el número quede tomado.

    `nota` es el diccionario que arma `libracore.notas_de_credito.armar_nota` cuando el
    comprobante es una nota de crédito: de ahí salen lo que la ata a su factura ante ARCA
    (`cbte_asoc_*`), la marca de anulación de una FCE y la leyenda. El resto del pedido se
    arma igual que el de una factura, desde el comprobante.
    """
    neto = Decimal(comprobante.neto)
    iva = Decimal(comprobante.iva)
    es_c = comprobante.tipo in TIPOS_C
    tercero = sesion.get(Tercero, comprobante.cliente_id)

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
        # El CUIT va **tal cual está cargado**: el motor lo normaliza a dígitos y valida
        # al receptor (`arca_wsfe.problema_del_receptor`); este producto no repite esa
        # lógica. La razón social viaja para que el mensaje del motor nombre al cliente.
        "cliente_cuit": (tercero.cuit or "") if tercero else "",
        "cliente_razon": tercero.razon_social if tercero else "",
        "cliente_iva_cond": _iva_cond_del_cliente(sesion, comprobante.cliente_id),
        "subtotal": float(neto + iva) if es_c else float(neto),
        "iva_amount": 0.0 if es_c else float(iva),
        "total": float(comprobante.total),
    }
    es_fce = comprobante.tipo in TIPOS_FCE
    if es_fce:
        # Del motor: el vencimiento viaja en el comprobante y el CBU y la modalidad
        # en la configuración. Si falta alguno, `arca_wsfe` falla con un mensaje que
        # dice qué cargar, y llega a la pantalla tal cual.
        factura.update({
            "fch_vto_pago": comprobante.fch_vto_pago.isoformat(),
            "fce_cbu": cfg.get("fce_cbu") or "",
            "fce_transmision": cfg.get("fce_transmision") or "",
        })
    if nota is not None:
        # Lo arma el motor, igual para todos los productos: acá no se reescribe.
        factura.update({k: v for k, v in nota.items()
                        if k.startswith("cbte_asoc_") or k == "fce_anulacion"})
    try:
        datos = await arca_wsfe.solicitar_cae(
            factura, emisor.cuit, ta["token"], ta["sign"], cfg["ambiente"],
        )
    except Exception as e:
        raise ArcaRechazo(str(e)) from None

    # El CAE lo guarda el motor, en la transacción de la sesión: el comprobante es una
    # fila de su `facturas` (ADR-030). El vencimiento va como lo devolvió ARCA.
    # (Import acá adentro: `servicios.comprobantes` importa este módulo.)
    from app.servicios.comprobantes import guardar_cae

    return guardar_cae(sesion, comprobante, datos["cae"], datos.get("cae_vto"))


def problema_del_cuit_del_cliente(tercero: Tercero, tipo: TipoComprobante) -> str | None:
    """Por qué el CUIT del cliente no sirve para emitir este comprobante por ARCA, o `None`.

    **Esta función no decide nada: delega en el motor** (`arca_wsfe.problema_del_receptor`), que
    es donde vive la guarda del CUIT de la familia (regla del 2026-10-03: el arreglo de fondo vive
    siempre en el motor). Lo único propio del producto es traducir su tipo de comprobante al código
    de ARCA y existir para que `facturar` conteste con un 422 **antes de pedir el número**, en
    lugar de dejar que el mismo mensaje llegue después como un rechazo de ARCA.
    """
    return arca_wsfe.problema_del_receptor({
        "tipo": CODIGO_ARCA[tipo],
        "cliente_cuit": tercero.cuit or "",
        "cliente_razon": tercero.razon_social,
    })


def _iva_cond_del_cliente(sesion: Session, cliente_id: int) -> int:
    """El código de la condición de IVA del receptor, o `0` si no se sabe."""
    tercero = sesion.get(Tercero, cliente_id)
    if tercero is None:
        return 0
    return CODIGO_IVA_DE_LA_FAMILIA.get(tercero.condicion_iva, 0)
