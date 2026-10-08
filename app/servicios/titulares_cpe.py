"""Los titulares de Carta de Porte: a nombre de quién se emite y quién emite (ADR-044).

Pedido del dueño (2026-10-08): *«vamos a tener otros clientes que nos van a delegar en ARCA para que hagamos nosotros
las cartas de porte, como habrá otros que las hagan ellos mismos. Tendríamos que tener en pantalla una sección para
guardar esos datos»*.

🔑 **La lista es una libreta; el permiso es de ARCA.** Que un titular esté cargado no autoriza nada, y que no lo esté
tampoco lo impide: si le delegó a este certificado la emisión de `wscpe`, el ticket de WSAA lo trae entre sus
`relation` (`arca_wscpe.cuits_habilitados`). Eso es lo que se lee —nunca lo que alguien tildó— y da cuatro estados:

- **delegado**: está cargado y está en el ticket;
- **pendiente**: está cargado y ARCA todavía no lo informa (el ticket sale con las relaciones de cuando se pidió, y
  dura hasta 12 horas: el próximo ticket ya lo trae);
- **delegado sin cargar**: está en el ticket y no en la lista (`sin_cargar`), para darlo de alta con un clic;
- **sin verificar**: no hay certificado `wscpe` o ARCA no contestó. No es un error de la pantalla: se dice el motivo.

🔑 **La delegación se mira para todos los titulares, emita quien emita.** Delegar `wscpe` habilita las dos cosas:
consultar una CPE por CTG (como `cuitRepresentada`) y emitirla. «Quién emite» sólo decide si se le ofrece emitir.

🔴 **El ticket es el que ya está en el disco.** Pedir uno a WSAA tiene costo y ARCA rechaza otro mientras el vigente
no venció (`alreadyAuthenticated`). Se usa `cartas_porte._ticket`, que pasa por `arca_wscpe.autenticar` y éste por la
caché del motor: sólo pide uno cuando no hay ninguno vigente, igual que la emisión y la consulta. Nunca se fuerza.

Un ticket sin relaciones legibles (`cuits_habilitados` da `()`) cuenta como «sin verificar» y no como «nadie delegó»:
es lo que ya hace `emitir`, y declarar «pendiente» a todos por un token ilegible sería afirmar lo que no se sabe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from libracore import arca_certificados, arca_credenciales, arca_wscpe
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import AccionAuditoria, Tercero
from app.models.cartas_porte import PlantillaCpe, TitularCpe
from app.schemas.cartas_porte import PlantillaIn, TitularEdicion, TitularIn
from app.servicios import auditoria
from app.servicios import cartas_porte as cpe_servicio
from app.servicios.cartas_porte import Rechazo, digitos
from app.servicios.emision_arca import EMPRESA_ARCA

DELEGADO = "delegado"
PENDIENTE = "pendiente"
SIN_VERIFICAR = "sin_verificar"


# ── Qué dice ARCA ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Delegaciones:
    """Lo que el ticket de `wscpe` informa, o por qué no se pudo saber."""

    ambiente: str | None
    #: Los CUIT del ticket, o `None` si no se pudo verificar (entonces `motivo` dice por qué).
    cuits: tuple[str, ...] | None
    motivo: str | None


def delegaciones() -> Delegaciones:
    """Las relaciones del ticket vigente de `wscpe`. No levanta: lo que no se pudo saber vuelve en `motivo`."""
    amb = cpe_servicio.ambiente()
    if amb is None:
        return Delegaciones(None, None, "No hay certificado de «CTG y Carta de Porte» cargado: cargalo en "
                                        "Configuración / ARCA.")
    try:
        ticket = cpe_servicio._ticket(amb)
    except Rechazo as e:
        return Delegaciones(amb, None, e.detalle)
    cuits = arca_wscpe.cuits_habilitados(ticket)
    if not cuits:
        return Delegaciones(amb, None, "ARCA no informó ninguna delegación en el ticket: puede que todavía nadie haya "
                                       "delegado, o que no se haya podido leer.")
    return Delegaciones(amb, cuits, None)


def _estado_de(titular: TitularCpe, d: Delegaciones) -> str:
    # 🔑 «Quién emite» no cambia lo que hay que mirar: la delegación de `wscpe` habilita consultar una CPE por CTG y
    # emitirla, así que también el que emite él la necesita para que podamos consultarle (ADR-044, 2026-10-08).
    if d.cuits is None:
        return SIN_VERIFICAR
    return DELEGADO if titular.cuit in d.cuits else PENDIENTE


# ── Con Entidades ──────────────────────────────────────────────────────────

def _limpio():
    return func.replace(func.replace(func.coalesce(Tercero.cuit, ""), "-", ""), ".", "")


def _tercero_por_cuit(sesion: Session, cuit: str) -> Tercero | None:
    """La entidad con ese CUIT. Con más de una (el legado dejó repetidos) gana un cliente activo, y el id más bajo."""
    return sesion.scalars(select(Tercero).where(_limpio() == cuit)
                          .order_by(Tercero.es_cliente.desc(), Tercero.activo.desc(), Tercero.id).limit(1)).first()


def _terceros_por_cuit(sesion: Session, cuits: list[str]) -> dict[str, Tercero]:
    if not cuits:
        return {}
    filas = sesion.scalars(select(Tercero).where(_limpio().in_(cuits))
                           .order_by(Tercero.es_cliente.asc(), Tercero.activo.asc(), Tercero.id.desc())).all()
    # Del peor al mejor, así el dict se queda con el mejor (el que `_tercero_por_cuit` elegiría solo).
    return {digitos(t.cuit): t for t in filas}


def _vinculo(titular: TitularCpe, por_cuit: dict[str, Tercero], por_id: dict[int, Tercero]) -> Tercero | None:
    """La entidad del titular: la elegida a mano y, si no hay, la que tiene su mismo CUIT."""
    return por_id.get(titular.tercero_id) if titular.tercero_id else por_cuit.get(titular.cuit)


def _plantillas(sesion: Session) -> set[str]:
    return set(sesion.scalars(select(PlantillaCpe.cuit_titular)))


# ── Listar ─────────────────────────────────────────────────────────────────

def _fila(titular: TitularCpe, d: Delegaciones, tercero: Tercero | None, plantillas: set[str]) -> dict:
    return {
        "id": titular.id, "cuit": titular.cuit, "razon_social": titular.razon_social, "emite": titular.emite,
        "activo": titular.activo, "notas": titular.notas, "delegacion": _estado_de(titular, d),
        "tercero": {"id": tercero.id, "razon_social": tercero.razon_social} if tercero else None,
        "tiene_plantilla": titular.cuit in plantillas,
        "actualizado": titular.updated_at,
    }


def como_fila(sesion: Session, titular: TitularCpe) -> dict:
    """Un titular recién escrito, con la forma de una fila del listado. No consulta a ARCA: la delegación vuelve «sin
    verificar» y se refresca con el próximo listado."""
    tercero = (sesion.get(Tercero, titular.tercero_id) if titular.tercero_id
               else _tercero_por_cuit(sesion, titular.cuit))
    return _fila(titular, Delegaciones(None, None, None), tercero, _plantillas(sesion))


def listar(sesion: Session) -> dict:
    """Los titulares con el estado de su delegación, y los CUIT que ARCA trae y no están cargados."""
    d = delegaciones()
    titulares = list(sesion.scalars(select(TitularCpe).order_by(TitularCpe.razon_social, TitularCpe.id)))
    cargados = {t.cuit for t in titulares}
    sin_cargar_cuits = [c for c in (d.cuits or ()) if c not in cargados]
    por_cuit = _terceros_por_cuit(sesion, [t.cuit for t in titulares] + sin_cargar_cuits)
    por_id = {t.id: t for t in sesion.scalars(select(Tercero).where(
        Tercero.id.in_([x.tercero_id for x in titulares if x.tercero_id])))} if titulares else {}
    plantillas = _plantillas(sesion)
    return {
        "ambiente": d.ambiente,
        "verificado": d.cuits is not None,
        "motivo": d.motivo,
        # Un CUIT por el que el ticket deja operar, para pedir los catálogos de ARCA (son los mismos para todos) aun
        # cuando el titular que se edita todavía no está delegado.
        "cuit_para_catalogos": d.cuits[0] if d.cuits else None,
        "titulares": [_fila(t, d, _vinculo(t, por_cuit, por_id), plantillas) for t in titulares],
        "sin_cargar": [
            {"cuit": c, "tercero": ({"id": por_cuit[c].id, "razon_social": por_cuit[c].razon_social}
                                    if c in por_cuit else None)}
            for c in sin_cargar_cuits],
    }


def de_tercero(sesion: Session, tercero_id: int) -> dict | None:
    """El titular de esa entidad (por vínculo o por CUIT) con su estado, para la ficha del cliente; `None` si no lo es.

    Sólo consulta a ARCA cuando la entidad es titular, emita quien emita (la delegación sirve para consultar y para
    emitir): la ficha de cualquier otro cliente no cuesta nada.
    """
    tercero = sesion.get(Tercero, tercero_id)
    if tercero is None:
        raise Rechazo(404, f"no existe la entidad {tercero_id}")
    cuit = digitos(tercero.cuit)
    vinculo = TitularCpe.tercero_id == tercero_id
    titular = sesion.scalars(
        select(TitularCpe).where(or_(vinculo, TitularCpe.cuit == cuit) if len(cuit) == 11 else vinculo)
        .order_by(TitularCpe.tercero_id.is_(None), TitularCpe.id).limit(1)).first()
    if titular is None:
        return None
    d = delegaciones()
    return {**_fila(titular, d, tercero, _plantillas(sesion)), "motivo": d.motivo}


# ── Alta, edición y baja ───────────────────────────────────────────────────

def _usuario_id(usuario: dict | None) -> int | None:
    valor = str((usuario or {}).get("id", ""))
    return int(valor) if valor.isdigit() else None


def _exigir_tercero(sesion: Session, tercero_id: int | None) -> Tercero | None:
    if tercero_id is None:
        return None
    tercero = sesion.get(Tercero, tercero_id)
    if tercero is None:
        raise Rechazo(404, f"no existe la entidad {tercero_id}")
    return tercero


def crear(sesion: Session, usuario: dict | None, datos: TitularIn) -> TitularCpe:
    if sesion.scalar(select(TitularCpe.id).where(TitularCpe.cuit == datos.cuit)) is not None:
        raise Rechazo(409, "Ese CUIT ya está cargado como titular.")
    # La entidad con ese CUIT, si la hay, se vincula sola; si no se eligió una, y la razón social sale de ella.
    tercero = _exigir_tercero(sesion, datos.tercero_id) or _tercero_por_cuit(sesion, datos.cuit)
    razon_social = datos.razon_social or (tercero.razon_social if tercero else None)
    if not razon_social:
        raise Rechazo(422, "Falta la razón social: el CUIT no es de ninguna entidad cargada.")
    titular = TitularCpe(cuit=datos.cuit, razon_social=razon_social[:120], tercero_id=tercero.id if tercero else None,
                         emite=datos.emite, activo=datos.activo, notas=datos.notas or None,
                         created_by=_usuario_id(usuario))
    sesion.add(titular)
    sesion.flush()
    auditoria.registrar(sesion, usuario, "titular_cpe", titular.id, AccionAuditoria.ALTA, despues=titular)
    sesion.commit()
    return titular


def _traer(sesion: Session, id_: int) -> TitularCpe:
    titular = sesion.get(TitularCpe, id_)
    if titular is None:
        raise Rechazo(404, f"no existe el titular {id_}")
    return titular


def editar(sesion: Session, usuario: dict | None, id_: int, datos: TitularEdicion) -> TitularCpe:
    titular = _traer(sesion, id_)
    antes = auditoria.instantanea(titular)
    _exigir_tercero(sesion, datos.tercero_id)
    titular.razon_social, titular.tercero_id = datos.razon_social, datos.tercero_id
    titular.emite, titular.activo, titular.notas = datos.emite, datos.activo, datos.notas or None
    titular.updated_by = _usuario_id(usuario)
    auditoria.registrar(sesion, usuario, "titular_cpe", titular.id, AccionAuditoria.MODIFICACION,
                        antes=antes, despues=titular)
    sesion.commit()
    return titular


def borrar(sesion: Session, usuario: dict | None, id_: int) -> None:
    """Saca al titular de la lista. Su plantilla queda: es lo último que se emitió a su nombre, y si se vuelve a
    cargar, la retoma. Nada más referencia a un titular (las cartas guardan el CUIT, no la fila)."""
    titular = _traer(sesion, id_)
    auditoria.registrar(sesion, usuario, "titular_cpe", titular.id, AccionAuditoria.BAJA, antes=titular)
    sesion.delete(titular)
    sesion.commit()


# ── La plantilla ───────────────────────────────────────────────────────────

def plantilla(sesion: Session, id_: int) -> dict:
    titular = _traer(sesion, id_)
    fila = sesion.get(PlantillaCpe, titular.cuit)
    return {"datos": dict(fila.datos) if fila else {}, "existe": fila is not None,
            "actualizada": fila.updated_at if fila else None}


def guardar_plantilla(sesion: Session, usuario: dict | None, id_: int, datos: PlantillaIn) -> dict:
    """Reemplaza la plantilla del titular por lo editado. Sin los vacíos: una clave ausente es «que lo complete quien
    emite», que es como los lee `propuesta()`."""
    titular = _traer(sesion, id_)
    nuevos = datos.model_dump(mode="json", exclude_none=True)
    for clave in ("origen", "destino"):
        if clave in nuevos:
            nuevos[clave] = {k: v for k, v in nuevos[clave].items() if v is not None}
    if not nuevos.get("intervinientes"):
        nuevos.pop("intervinientes", None)
    fila = sesion.get(PlantillaCpe, titular.cuit)
    antes = {"datos": dict(fila.datos)} if fila else None
    if fila is None:
        sesion.add(PlantillaCpe(cuit_titular=titular.cuit, datos=nuevos, updated_by=_usuario_id(usuario)))
    else:
        fila.datos, fila.updated_by = nuevos, _usuario_id(usuario)
    auditoria.registrar(sesion, usuario, "plantilla_cpe", titular.id,
                        AccionAuditoria.MODIFICACION if fila else AccionAuditoria.ALTA,
                        antes=antes, despues={"datos": nuevos})
    sesion.commit()
    return plantilla(sesion, id_)


def borrar_plantilla(sesion: Session, usuario: dict | None, id_: int) -> None:
    titular = _traer(sesion, id_)
    fila = sesion.get(PlantillaCpe, titular.cuit)
    if fila is None:
        return
    auditoria.registrar(sesion, usuario, "plantilla_cpe", titular.id, AccionAuditoria.BAJA,
                        antes={"datos": dict(fila.datos)})
    sesion.delete(fila)
    sesion.commit()


# ── Instrucciones de delegación ────────────────────────────────────────────

def instrucciones() -> dict:
    """Lo que el titular necesita para delegarnos `wscpe`, sacado del certificado cargado y no escrito a mano:
    el CUIT del representante (el que firma el certificado) y el alias del computador fiscal (su nombre común).

    Sin ARCA: sólo se lee el .crt del disco. No levanta; si no se puede, `disponible` es falso y `motivo` dice por qué.
    """
    amb = cpe_servicio.ambiente()
    if amb is None:
        return {"disponible": False, "ambiente": None, "alias": None, "cuit_representante": None,
                "motivo": "No hay certificado de «CTG y Carta de Porte» cargado: cargalo en Configuración / ARCA."}
    cert, _ = arca_credenciales.paths_en_disco_de_servicio(EMPRESA_ARCA, arca_wscpe.SERVICIO, amb)
    try:
        datos = arca_certificados.leer_certificado_de_archivo(cert)
    except (arca_certificados.ArchivoFaltante, arca_certificados.ArchivoInvalido) as e:
        return {"disponible": False, "ambiente": amb, "alias": None, "cuit_representante": None,
                "motivo": f"No se pudo leer el certificado de «CTG y Carta de Porte»: {e}"}
    m = re.search(r"(?:^|,)CN=([^,]+)", datos.sujeto)
    alias, cuit = (m.group(1).strip() if m else ""), datos.cuit
    if not alias or not cuit:
        return {"disponible": False, "ambiente": amb, "alias": alias or None, "cuit_representante": cuit or None,
                "motivo": "El certificado no trae el alias (CN) o el CUIT (serialNumber) en su sujeto."}
    return {"disponible": True, "ambiente": amb, "alias": alias, "cuit_representante": cuit, "motivo": None}
