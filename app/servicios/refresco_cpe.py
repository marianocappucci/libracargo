"""Refrescar solas las Cartas de Porte abiertas (ADR-051).

Una CPE queda **abierta** hasta que ARCA informa los kilos de descarga o la deja en un estado final
(`cartas_porte.abiertas`). Hasta ahora alguien tenía que apretar «Actualizar abiertas»; esto lo hace un cron del host
(`scripts/refrescar_cartas_porte.py`), con las mismas funciones que el botón.

🔴 **Sólo consulta.** Este módulo no emite ni anula nada y no toca `cpe_emision_habilitada`: leer una CPE no tiene
efecto fiscal. Por eso tiene **su propio interruptor** (`cpe_refresco_habilitado`, apagado por omisión) y no el de la
emisión real: atarlo a ese dejaría sin refresco justamente a las instancias que sólo traen cartas de ARCA, como
Suitrans mientras la emisión está apagada.

Cuándo **no corre** (todos devuelven `estado: "omitido"` y nada más):

- en una demo (`DEMO_MODE=1`): no habla con ARCA (ADR-061 de libracore) y no tiene certificado;
- con el interruptor apagado;
- sin certificado de «CTG y Carta de Porte» cargado;
- en el **central de una instancia con un nodo vinculado** (ADR-056): las cartas de porte se escriben sólo en el nodo, y
  refrescarlas acá las dejaría distintas de las del nodo. Corre en el nodo, con el ticket que presta el central.

Y si ya hay otra corrida en curso devuelve `estado: "ocupado"`: con dos procesos (`WEB_CONCURRENCY`, ADR-047) o dos
crones superpuestos, el candado de base (`libracore.candados`) deja pasar a uno solo.

🔑 **Por lote y espaciado**, como pide el plan (mucho volumen en cosecha): cada corrida toma hasta `MAX_POR_CORRIDA`
cartas, las que hace más tiempo que no se consultan, y se saltea las consultadas hace menos de `ESPERA_ENTRE_CONSULTAS`
(un cron que se pisa o un «Actualizar» manual reciente no vuelven a pedir lo mismo). Las vencidas hace más de
`DIAS_VENCIDA` quedan fuera: una CPE que nunca se descargó no se consulta para siempre; sigue actualizable a mano.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from libracore import config_manager
from libracore.candados import candado_de_base
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import offline
from app.models import AccionAuditoria, ConfiguracionEmpresa
from app.models.cartas_porte import CartaPorte
from app.servicios import auditoria
from app.servicios import cartas_porte as cpe_servicio
from app.servicios.cartas_porte import Rechazo

logger = logging.getLogger(__name__)

#: El candado de la corrida. Es el nombre, no una cantidad: dos procesos que pidan este mismo se excluyen.
CANDADO = "libracargo-cpe-refresco"

#: Cuántas cartas toma una corrida. El resto espera a la que sigue (las más viejas primero).
MAX_POR_CORRIDA = 200

#: Una carta consultada hace menos que esto no se vuelve a consultar.
ESPERA_ENTRE_CONSULTAS = timedelta(minutes=15)

#: Pasado este tiempo desde su vencimiento, una carta abierta deja de consultarse sola.
DIAS_VENCIDA = 30

#: Quien figura en la auditoría de lo que cambió el refresco.
USUARIO = {"id": None, "username": "sistema (refresco de CPE)"}


def _config(sesion: Session) -> ConfiguracionEmpresa | None:
    return sesion.get(ConfiguracionEmpresa, 1)


# ── El interruptor ─────────────────────────────────────────────────────────

def estado(sesion: Session) -> dict:
    """Si el refresco está prendido y cuándo corrió por última vez, para la pantalla de Configuración / ARCA."""
    cfg = _config(sesion)
    return {
        "habilitado": bool(cfg and cfg.cpe_refresco_habilitado),
        "ambiente": cpe_servicio.ambiente(),
        "ultima_corrida": cfg.cpe_refresco_ultima_corrida if cfg else None,
        "resumen": cfg.cpe_refresco_resumen if cfg else None,
        "es_demo": config_manager.es_demo(),
    }


def habilitar(sesion: Session, usuario: dict | None, habilitado: bool) -> dict:
    cfg = _config(sesion)
    if cfg is None:
        raise Rechazo(409, "Primero cargá los datos de la empresa en Configuración.")
    antes = auditoria.instantanea(cfg)
    cfg.cpe_refresco_habilitado = habilitado
    auditoria.registrar(sesion, usuario, "configuracion", 1, AccionAuditoria.MODIFICACION, antes=antes, despues=cfg)
    sesion.commit()
    return estado(sesion)


# ── La corrida ─────────────────────────────────────────────────────────────

def a_refrescar(sesion: Session, ahora: datetime | None = None) -> list[CartaPorte]:
    """Las abiertas que toca consultar ahora: las menos recientes primero, hasta `MAX_POR_CORRIDA`."""
    ahora = ahora or datetime.now(UTC)
    return list(sesion.scalars(
        select(CartaPorte)
        .where(CartaPorte.peso_bruto_descarga.is_(None),
               CartaPorte.estado.not_in(cpe_servicio.ESTADOS_CERRADOS),
               CartaPorte.consultada_en < ahora - ESPERA_ENTRE_CONSULTAS,
               or_(CartaPorte.fecha_vencimiento.is_(None),
                   CartaPorte.fecha_vencimiento >= ahora - timedelta(days=DIAS_VENCIDA)))
        .order_by(CartaPorte.consultada_en, CartaPorte.id)
        .limit(MAX_POR_CORRIDA)))


def _omitido(motivo: str) -> dict:
    return {"estado": "omitido", "motivo": motivo, "actualizadas": 0, "errores": []}


def texto_del_resumen(resumen: dict) -> str:
    """El resumen de una corrida para la pantalla y el log: `3 actualizadas, 1 con error`."""
    n, e = resumen["actualizadas"], len(resumen["errores"])
    texto = f"{n} actualizada{'s' if n != 1 else ''}"
    return texto + (f", {e} con error" if e else "")


def correr(sesion: Session) -> dict:
    """Una pasada del refresco programado. Devuelve `{estado, motivo, actualizadas, errores}`.

    `estado` es `omitido` (demo, apagado o sin certificado), `ocupado` (hay otra corrida) o `corrio`. **Nunca emite ni
    anula**: sólo `consultar_cpe`. Un error de ARCA en una carta se anota y sigue con las demás.
    """
    if config_manager.es_demo():
        return _omitido("es una demo: no habla con ARCA")
    if offline.nodo() is None and offline.hay_nodo_vinculado():
        return _omitido("hay un nodo vinculado: las cartas de porte se actualizan en el nodo de la oficina")
    cfg = _config(sesion)
    if not (cfg and cfg.cpe_refresco_habilitado):
        return _omitido("el refresco programado está apagado")
    if cpe_servicio.ambiente() is None:
        return _omitido("no hay certificado de «CTG y Carta de Porte» cargado")
    sesion.rollback()  # no dejar la transacción de la lectura abierta durante las llamadas a ARCA

    # 🔴 El candado vive en una conexión APARTE y en una transacción que se queda abierta toda la corrida: el de la base
    # dura hasta el fin de la transacción de quien lo toma, y la `sesion` commitea carta por carta.
    with sesion.get_bind().connect() as conexion, conexion.begin():
        with candado_de_base(conexion, CANDADO) as lo_tengo:
            if not lo_tengo:
                return {"estado": "ocupado", "motivo": "ya hay otra corrida en curso", "actualizadas": 0,
                        "errores": []}
            filas = a_refrescar(sesion)
            resumen = cpe_servicio.actualizar_abiertas(sesion, USUARIO, filas)
    for e in resumen["errores"]:
        logger.warning("CPE %s: %s", e["ctg"], e["error"])
    _anotar(sesion, resumen)
    return {"estado": "corrio", "motivo": None, **resumen}


def _anotar(sesion: Session, resumen: dict) -> None:
    """Deja en la configuración cuándo corrió y qué pasó, para verlo en la pantalla. Sin auditoría: no decide nada.

    En un nodo no: la configuración baja del central por el espejo y el nodo no la escribe (ADR-056)."""
    cfg = _config(sesion)
    if cfg is None or offline.nodo() is not None:
        return
    cfg.cpe_refresco_ultima_corrida = datetime.now(UTC)
    cfg.cpe_refresco_resumen = texto_del_resumen(resumen)[:200]
    sesion.commit()
