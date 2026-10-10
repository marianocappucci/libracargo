"""Emitir la Carta de Porte Electrónica desde la orden, por delegación de un titular (ADR-043).

El protocolo —el último número, autorizar, la guarda de timeout, el cerrojo— es del motor
(`libracore.arca_wscpe.emitir_cpe`, ADR-035). Acá está lo de este producto:

- **la propuesta**: lo que la orden ya sabe (chofer, dominios, fletero, cliente, kilos de carga, km y tarifa por
  tonelada del tarifario) más lo que se usó la última vez con ese titular (`PlantillaCpe`: origen, grano,
  destino, planta, intervinientes);
- **los códigos de ARCA** de provincia y localidad, que no son los del catálogo censal: se buscan por nombre;
- **la traba**: en producción no se emite nada hasta que un administrador lo habilita, y cada emisión real pide
  una confirmación explícita;
- **guardar** la CPE emitida (`emitida=True`), vinculada a su orden, con su PDF.

🔴 Si ARCA autoriza y después falla guardar acá, la CPE **existe igual**: el error lo dice con su CTG, para
traerla después con «Traer de ARCA». No se reintenta la emisión.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from libracore import arca_wscpe as w
from libracore.geografia import normalizar
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccionAuditoria,
    Chofer,
    ConfiguracionEmpresa,
    Localidad,
    OrdenCarga,
    Tercero,
    Vehiculo,
)
from app.models.cartas_porte import EMITE_NOSOTROS, CartaPorte, PlantillaCpe, TitularCpe
from app.servicios import auditoria
from app.servicios import cartas_porte as cpe_servicio
from app.servicios.cartas_porte import Rechazo, digitos

logger = logging.getLogger(__name__)

#: Los catálogos de ARCA cambian poco: se piden una vez cada tantas horas por ambiente.
_TTL_CATALOGO = 12 * 3600
_CACHE: dict[tuple, tuple[float, object]] = {}

#: Lo que la plantilla del titular recuerda entre emisiones. Lo del viaje (chofer, dominios, pesos, partida) no.
CAMPOS_DE_PLANTILLA = ("sucursal", "origen", "cod_grano", "cosecha", "destino", "cuit_destinatario",
                       "intervinientes", "cuit_remitente_comercial_productor", "mercaderia_fumigada", "km",
                       "observaciones")

#: Los intervinientes opcionales con el nombre del WSDL de ARCA (`IntervinientesSolicitud`). Es la lista que el motor
#: tiene en `_ORDEN_INTERVINIENTES` (privada): un test las compara, para que un interviniente nuevo no se pierda.
INTERVINIENTES = ("cuitRemitenteComercialVentaPrimaria", "cuitRemitenteComercialVentaSecundaria",
                  "cuitRemitenteComercialVentaSecundaria2", "cuitMercadoATermino", "cuitCorredorVentaPrimaria",
                  "cuitCorredorVentaSecundaria", "cuitRepresentanteEntregador", "cuitRepresentanteRecibidor")

#: El enlace al PDF que se le pasa al chofer vence a los 7 días.
VIGENCIA_ENLACE = 7 * 24 * 3600


# ── Estado y traba ─────────────────────────────────────────────────────────

def _config(sesion: Session) -> ConfiguracionEmpresa | None:
    return sesion.get(ConfiguracionEmpresa, 1)


def estado(sesion: Session) -> dict:
    """En qué ambiente se emitiría y si está habilitado. En homologación siempre se puede (no tiene efecto fiscal)."""
    amb = cpe_servicio.ambiente()
    cfg = _config(sesion)
    habilitada = bool(cfg and cfg.cpe_emision_habilitada)
    return {"ambiente": amb, "habilitada": habilitada,
            "puede_emitir": amb == "homologacion" or (amb == "produccion" and habilitada)}


def habilitar(sesion: Session, usuario: dict | None, habilitada: bool) -> dict:
    cfg = _config(sesion)
    if cfg is None:
        raise Rechazo(409, "Primero cargá los datos de la empresa en Configuración.")
    antes = auditoria.instantanea(cfg)
    cfg.cpe_emision_habilitada = habilitada
    auditoria.registrar(sesion, usuario, "configuracion", 1, AccionAuditoria.MODIFICACION, antes=antes, despues=cfg)
    sesion.commit()
    return estado(sesion)


# ── Catálogos de ARCA ──────────────────────────────────────────────────────

def _cacheado(clave: tuple, pedir):
    ahora = time.monotonic()
    guardado = _CACHE.get(clave)
    if guardado and ahora - guardado[0] < _TTL_CATALOGO:
        return guardado[1]
    valor = pedir()
    _CACHE[clave] = (ahora, valor)
    return valor


def _llamar(corrutina):
    try:
        return asyncio.run(corrutina)
    except w.CuitNoRelacionado as e:
        raise Rechazo(409, str(e)) from None
    except w.ErrorWscpe as e:
        raise Rechazo(502, str(e)) from None
    except RuntimeError as e:
        raise Rechazo(502, f"ARCA no contestó: {e}") from None


def _acceso(cuit_titular: str) -> tuple[str, str, dict]:
    cuit = digitos(cuit_titular)
    if len(cuit) != 11:
        raise Rechazo(422, "Elegí a nombre de qué titular se emite (11 dígitos).")
    amb = cpe_servicio._ambiente_o_rechazo()
    return cuit, amb, cpe_servicio._ticket(amb)


def granos(cuit_titular: str) -> dict[int, str]:
    cuit, amb, t = _acceso(cuit_titular)
    return _cacheado((amb, "granos"), lambda: _llamar(w.tipos_grano(cuit, t["token"], t["sign"], amb)))


def provincias_arca(cuit_titular: str) -> dict[int, str]:
    cuit, amb, t = _acceso(cuit_titular)
    return _cacheado((amb, "provincias"), lambda: _llamar(w.provincias(cuit, t["token"], t["sign"], amb)))


def localidades_arca(cuit_titular: str, cod_provincia: int) -> dict[int, str]:
    cuit, amb, t = _acceso(cuit_titular)
    return _cacheado((amb, "localidades", cod_provincia), lambda: _llamar(
        w.localidades(cuit, t["token"], t["sign"], cod_provincia=cod_provincia, ambiente=amb)))


def plantas(cuit_titular: str, cuit_planta: str) -> list[dict]:
    cuit, amb, t = _acceso(cuit_titular)
    lista = _llamar(w.plantas(cuit, t["token"], t["sign"], cuit=digitos(cuit_planta), ambiente=amb))
    return [{"numero": p.numero, "cod_provincia": p.cod_provincia, "cod_localidad": p.cod_localidad} for p in lista]


#: Cómo llama ARCA a CABA: no coincide por nombre con el catálogo censal.
_SINONIMOS_PROVINCIA = {
    normalizar("Ciudad Autónoma de Buenos Aires"): normalizar("CAP.FEDERAL"),
    normalizar("Tierra del Fuego, Antártida e Islas del Atlántico Sur"): normalizar("TIERRA DEL FUEGO"),
}


def codigos_de(cuit_titular: str, localidad: Localidad | None) -> dict | None:
    """Los códigos de ARCA (provincia y localidad) de una localidad del maestro, por nombre; `None` si no hay una
    coincidencia única. Sólo Argentina: un destino de afuera no lleva CPE nacional."""
    if localidad is None or localidad.pais != "AR" or not localidad.provincia:
        return None
    buscada = _SINONIMOS_PROVINCIA.get(normalizar(localidad.provincia), normalizar(localidad.provincia))
    provs = [c for c, n in provincias_arca(cuit_titular).items() if normalizar(n) == buscada]
    if len(provs) != 1:
        return None
    locs = [c for c, n in localidades_arca(cuit_titular, provs[0]).items()
            if normalizar(n) == normalizar(localidad.nombre)]
    if len(locs) != 1:
        return None
    return {"cod_provincia": provs[0], "cod_localidad": locs[0]}


# ── La propuesta ───────────────────────────────────────────────────────────

def _cuit_de(sesion: Session, tercero_id: int | None) -> str | None:
    t = sesion.get(Tercero, tercero_id) if tercero_id else None
    c = digitos(t.cuit) if t else ""
    return c if len(c) == 11 else None


def _tarifa_tonelada(orden: OrdenCarga) -> str | None:
    if orden.tarifa_tonelada is not None:
        return str(orden.tarifa_tonelada.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return None


def propuesta(sesion: Session, orden_id: int, cuit_titular: str) -> dict:
    """Lo que se le propone al operador para emitir la CPE de esa orden a nombre de `cuit_titular`.

    Lo de la orden manda para el viaje; la plantilla del titular completa lo comercial. `faltantes` dice qué no se
    pudo completar y hay que cargar.
    """
    orden = sesion.get(OrdenCarga, orden_id)
    if orden is None:
        raise Rechazo(404, f"no existe la orden {orden_id}")
    cuit = digitos(cuit_titular)
    plantilla = sesion.get(PlantillaCpe, cuit)
    datos = dict(plantilla.datos) if plantilla else {}
    faltantes: list[str] = []

    chofer = sesion.get(Chofer, orden.chofer_id) if orden.chofer_id else None
    vehiculo = sesion.get(Vehiculo, orden.vehiculo_id) if orden.vehiculo_id else None
    fletero_id = orden.fletero_id or (vehiculo.fletero_id if vehiculo else None) or (
        chofer.fletero_id if chofer else None)
    cfg = _config(sesion)

    origen_loc = sesion.get(Localidad, orden.origen_id)
    destino_loc = sesion.get(Localidad, orden.destino_id)
    cod_origen, cod_destino = codigos_de(cuit, origen_loc), codigos_de(cuit, destino_loc)

    origen = dict(datos.get("origen") or {"tipo": "campo"})
    if cod_origen:
        origen.update(cod_origen)
    elif not origen.get("cod_localidad"):
        faltantes.append(f"El origen «{origen_loc.nombre}» no se encontró en el catálogo de ARCA: elegilo.")
    destino = dict(datos.get("destino") or {})
    if cod_destino:
        if destino.get("cod_localidad") != cod_destino["cod_localidad"]:
            destino = {"cuit": None, "planta": None, "es_campo": False}
        destino.update(cod_destino)
    elif not destino.get("cod_localidad"):
        faltantes.append(f"El destino «{destino_loc.nombre}» no se encontró en el catálogo de ARCA: elegilo.")

    transporte = {
        "cuit_transportista": _cuit_de(sesion, fletero_id) or (digitos(cfg.cuit) if cfg and cfg.cuit else None),
        "dominios": [d for d in ((vehiculo.patente_chasis, vehiculo.patente_acoplado) if vehiculo else ()) if d],
        "fecha_hora_partida": None,
        "km": orden.km or datos.get("km"),
        "cuit_chofer": chofer.cuit if chofer and chofer.cuit else None,
        "cuit_pagador_flete": _cuit_de(sesion, orden.cliente_id),
        "tarifa": _tarifa_tonelada(orden),
        "mercaderia_fumigada": bool(datos.get("mercaderia_fumigada", False)),
    }
    if not transporte["cuit_chofer"]:
        faltantes.append("El chofer de la orden no tiene CUIT: cargalo en Transporte → Choferes.")
    if not transporte["dominios"]:
        faltantes.append("La orden no tiene vehículo: hacen falta los dominios.")
    if not transporte["cuit_pagador_flete"]:
        faltantes.append("El cliente de la orden no tiene CUIT: es el pagador del flete.")
    if orden.kg_bruto_carga is None or orden.kg_tara_carga is None:
        faltantes.append("Faltan los kilos de carga (bruto y tara) en la orden.")
    if not datos.get("cod_grano"):
        faltantes.append("Elegí el grano.")

    return {
        "orden_id": orden.id,
        "cuit_titular": cuit,
        "sucursal": datos.get("sucursal", 1),
        "origen": origen,
        "cod_grano": datos.get("cod_grano"),
        "cosecha": datos.get("cosecha"),
        "peso_bruto": orden.kg_bruto_carga,
        "peso_tara": orden.kg_tara_carga,
        "destino": destino,
        "cuit_destinatario": datos.get("cuit_destinatario") or destino.get("cuit"),
        "intervinientes": datos.get("intervinientes") or {},
        "cuit_remitente_comercial_productor": datos.get("cuit_remitente_comercial_productor"),
        "transporte": transporte,
        "observaciones": datos.get("observaciones"),
        "de_plantilla": plantilla is not None,
        "faltantes": faltantes,
    }


# ── Emitir ─────────────────────────────────────────────────────────────────

def _solicitud(d: dict) -> w.SolicitudCpe:
    o, de, t = d["origen"], d["destino"], d["transporte"]
    if o.get("tipo") == "planta":
        origen = w.OrigenPlanta(int(o["cod_provincia"]), int(o["cod_localidad"]), int(o["planta"]))
    else:
        origen = w.OrigenCampo(int(o["cod_provincia"]), int(o["cod_localidad"]), o.get("renspa") or None)
    partida = datetime.fromisoformat(t["fecha_hora_partida"]) if isinstance(t["fecha_hora_partida"], str) \
        else t["fecha_hora_partida"]
    return w.SolicitudCpe(
        cuit_solicitante=d["cuit_titular"], sucursal=int(d.get("sucursal") or 1), origen=origen,
        cod_grano=int(d["cod_grano"]), cosecha=int(d["cosecha"]),
        peso_bruto=int(d["peso_bruto"]), peso_tara=int(d["peso_tara"]),
        destino=w.DestinoSolicitud(cuit=de["cuit"], cod_provincia=int(de["cod_provincia"]),
                                   cod_localidad=int(de["cod_localidad"]),
                                   planta=int(de["planta"]) if de.get("planta") else None,
                                   es_campo=bool(de.get("es_campo"))),
        cuit_destinatario=d["cuit_destinatario"],
        transporte=w.TransporteSolicitud(
            cuit_transportista=t["cuit_transportista"], dominios=tuple(x.upper() for x in t["dominios"]),
            fecha_hora_partida=partida, km=int(t["km"]), cuit_chofer=t["cuit_chofer"],
            cuit_pagador_flete=t["cuit_pagador_flete"], mercaderia_fumigada=bool(t.get("mercaderia_fumigada")),
            tarifa=Decimal(str(t["tarifa"])) if t.get("tarifa") not in (None, "") else None,
            cuit_intermediario_flete=t.get("cuit_intermediario_flete") or None,
            codigo_turno=t.get("codigo_turno") or None),
        cuit_remitente_comercial_productor=d.get("cuit_remitente_comercial_productor") or None,
        intervinientes={k: v for k, v in (d.get("intervinientes") or {}).items() if v} or None,
        observaciones=d.get("observaciones") or None,
    )


def _exigir_que_emitamos_nosotros(sesion: Session, cuit: str) -> None:
    """Un titular **cargado** como «emite él» o dado de baja (ADR-044) no se emite desde acá, aunque ARCA tenga su
    delegación: alguien dijo que no es así, y emitir a su nombre es irreversible. Uno que no está cargado sigue
    pasando: la delegación de ARCA es la autoridad y esta lista, una libreta."""
    titular = sesion.scalar(select(TitularCpe).where(TitularCpe.cuit == cuit))
    if titular is None:
        return
    if titular.emite != EMITE_NOSOTROS:
        raise Rechazo(409, f"«{titular.razon_social}» emite sus propias cartas de porte: está cargado en Titulares "
                           "como «El titular». Si cambió, corregilo ahí.")
    if not titular.activo:
        raise Rechazo(409, f"«{titular.razon_social}» está dado de baja en Titulares: reactivalo para emitir a su "
                           "nombre.")


def emitir(sesion: Session, usuario: dict | None, orden_id: int, datos: dict, *, confirmo: bool) -> CartaPorte:
    """Emite la CPE de la orden a nombre del titular de `datos` y la guarda vinculada. Ver el docstring del módulo."""
    orden = sesion.get(OrdenCarga, orden_id)
    if orden is None:
        raise Rechazo(404, f"no existe la orden {orden_id}")
    est = estado(sesion)
    amb = est["ambiente"]
    if amb is None:
        raise Rechazo(409, "No hay certificado de «CTG y Carta de Porte» cargado: cargalo en Configuración / ARCA.")
    if not est["puede_emitir"]:
        raise Rechazo(409, "La emisión de Cartas de Porte reales está apagada: la habilita un administrador.")
    if amb == "produccion" and not confirmo:
        raise Rechazo(422, "Confirmá que vas a emitir una Carta de Porte real.")
    _exigir_que_emitamos_nosotros(sesion, digitos(datos.get("cuit_titular", "")))
    cuit, amb, ticket = _acceso(datos.get("cuit_titular", ""))
    habilitados = w.cuits_habilitados(ticket)
    if habilitados and cuit not in habilitados:
        raise Rechazo(409, f"El titular {cuit} no le delegó la emisión a este certificado en ARCA.")
    try:
        solicitud = _solicitud({**datos, "cuit_titular": cuit})
    except (KeyError, TypeError, ValueError) as e:
        raise Rechazo(422, f"Falta o no sirve un dato de la carta de porte: {e}") from None
    try:
        cpe = asyncio.run(w.emitir_cpe(cuit, ticket["token"], ticket["sign"], solicitud, ambiente=amb))
    except w.SolicitudInvalida as e:
        raise Rechazo(422, "; ".join(e.problemas)) from None
    except w.EmisionIncierta as e:
        raise Rechazo(502, f"{e} (sucursal {e.sucursal}, número {e.nro_orden})") from None
    except w.CuitNoRelacionado as e:
        raise Rechazo(409, str(e)) from None
    except w.ErrorWscpe as e:
        raise Rechazo(422, f"ARCA rechazó la carta de porte: {e}") from None
    except RuntimeError as e:
        raise Rechazo(502, str(e)) from None

    try:
        fila = cpe_servicio.guardar(sesion, usuario, cpe, cuit, amb, orden.id)
        fila.emitida = True
        plantilla = sesion.get(PlantillaCpe, cuit)
        recordado = {k: datos.get(k) for k in CAMPOS_DE_PLANTILLA if k != "km"}
        recordado["km"] = (datos.get("transporte") or {}).get("km")
        recordado["mercaderia_fumigada"] = (datos.get("transporte") or {}).get("mercaderia_fumigada")
        if plantilla is None:
            sesion.add(PlantillaCpe(cuit_titular=cuit, datos=recordado, updated_by=_usuario_id(usuario)))
        else:
            plantilla.datos, plantilla.updated_by = recordado, _usuario_id(usuario)
        sesion.commit()
    except Exception:
        sesion.rollback()
        logger.exception("CPE emitida (CTG %s) y no guardada", cpe.nro_ctg)
        raise Rechazo(500, f"La Carta de Porte SE EMITIÓ en ARCA (CTG {cpe.nro_ctg}, N.º {cpe.numero}) pero no "
                           "se pudo guardar acá: traela con «Traer de ARCA» con ese CTG. No la vuelvas a emitir."
                      ) from None
    return fila


def _usuario_id(usuario: dict | None) -> int | None:
    valor = str((usuario or {}).get("id", ""))
    return int(valor) if valor.isdigit() else None


# ── Anular ─────────────────────────────────────────────────────────────────

def anular(sesion: Session, usuario: dict | None, fila: CartaPorte, observaciones: str | None) -> CartaPorte:
    """Anula en ARCA una CPE **emitida desde acá** y la vuelve a traer para guardar su estado."""
    if not fila.emitida:
        raise Rechazo(409, "Sólo se anulan desde acá las cartas de porte que emitió este sistema.")
    if fila.estado == "AN":
        raise Rechazo(409, "La carta de porte ya está anulada.")
    cuit, amb, ticket = fila.cuit_representada, fila.ambiente, cpe_servicio._ticket(fila.ambiente)
    _llamar(w.anular_cpe(cuit, ticket["token"], ticket["sign"], sucursal=fila.sucursal, nro_orden=fila.nro_orden,
                         tipo_cpe=fila.tipo_cpe or w.TIPO_AUTOMOTOR, observaciones=observaciones or None,
                         ambiente=amb))
    actualizada = cpe_servicio.actualizar(sesion, usuario, fila, ticket)
    sesion.commit()
    return actualizada


# ── El enlace al PDF para el chofer ────────────────────────────────────────

def _firma(id_: int, vence: int) -> str:
    secreto = os.environ.get("SECRET_KEY", "")
    if not secreto:
        raise Rechazo(503, "Esta instancia no tiene SECRET_KEY: no se pueden firmar enlaces.")
    return hmac.new(secreto.encode(), f"cpe-pdf:{id_}:{vence}".encode(), hashlib.sha256).hexdigest()[:32]


def enlace(id_: int, ahora: float | None = None) -> tuple[str, datetime]:
    """La ruta firmada (sin dominio) al PDF de la CPE, y cuándo vence. El chofer no tiene usuario en el sistema."""
    vence = int((ahora or time.time()) + VIGENCIA_ENLACE)
    return f"/cpe/{id_}/{vence}/{_firma(id_, vence)}.pdf", datetime.fromtimestamp(vence, UTC)


def verificar_enlace(id_: int, vence: int, firma: str) -> bool:
    if vence < time.time():
        return False
    return hmac.compare_digest(_firma(id_, vence), firma)
