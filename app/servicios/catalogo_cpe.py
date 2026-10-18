"""Los códigos de ARCA de la Carta de Porte (grano, provincia, localidad) con su nombre (ADR-051).

Una CPE guarda los **códigos** de ARCA: `cod_grano = 23`, `cod_provincia = 12`, `cod_localidad = 4211`. Para leerlos
hace falta la tabla de WSCPE (`consultarTiposGrano`, `consultarProvincias`, `consultarLocalidadesPorProvincia`), que se
pide con certificado y ticket: **no se puede consultar en cada pantalla** (ni existe en la demo, que no tiene
certificado). Por eso acá hay una copia (`catalogo_cpe`, por ambiente) con dos caras:

- **Leer** (`Traductor`): una consulta a la base por pedido, nunca a ARCA. Lo que no está en la copia se muestra con su
  código, como antes: la pantalla no se rompe ni miente.
- **Completar** (`completar`): pide a ARCA **sólo lo que falta**, con el ticket que ya tiene quien está consultando CPE
  (traer, actualizar, el refresco programado), y lo guarda. Es de mejor esfuerzo: un error de ARCA se registra y se
  sigue, jamás hace fallar a quien trajo la carta.

🔑 **Es sólo consulta.** No emite ni anula nada y no depende del interruptor de la emisión real ni del del refresco:
las tablas de códigos no tienen efecto fiscal, y sin ellas la carta que el operador acaba de traer se vería con
números.

🔑 **Una tabla que ARCA contestó no se vuelve a pedir enseguida.** Un código que ARCA no conoce (un grano retirado, un
dato mal cargado) seguiría «faltando» para siempre; sin esta pausa (`REPETIR_DESPUES_DE`) cada corrida del refresco
volvería a pedir la misma tabla entera.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from libracore import arca_wscpe
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.cartas_porte import (
    CATALOGO_GRANO,
    CATALOGO_LOCALIDAD,
    CATALOGO_PROVINCIA,
    CartaPorte,
    CatalogoCpe,
)

logger = logging.getLogger(__name__)

#: Cuánto se espera para pedir de nuevo una tabla que ya se pidió y de la que siguen faltando códigos.
REPETIR_DESPUES_DE = timedelta(hours=12)

#: Una clave del catálogo: `(ambiente, tipo, cod_provincia, codigo)`. `cod_provincia` es 0 salvo en la localidad.
Clave = tuple[str, str, int, int]


# ── Qué códigos usa una carta ──────────────────────────────────────────────

def claves_de(ambiente: str, *, cod_grano, cod_provincia_origen, cod_localidad_origen,
              cod_provincia_destino, cod_localidad_destino) -> set[Clave]:
    """Las claves que hacen falta para leer una carta. Una localidad sin su provincia no se puede ubicar: se omite."""
    claves: set[Clave] = set()
    if cod_grano is not None:
        claves.add((ambiente, CATALOGO_GRANO, 0, cod_grano))
    for provincia, localidad in ((cod_provincia_origen, cod_localidad_origen),
                                 (cod_provincia_destino, cod_localidad_destino)):
        if provincia is not None:
            claves.add((ambiente, CATALOGO_PROVINCIA, 0, provincia))
            if localidad is not None:
                claves.add((ambiente, CATALOGO_LOCALIDAD, provincia, localidad))
    return claves


def claves_de_fila(fila: CartaPorte) -> set[Clave]:
    return claves_de(fila.ambiente, cod_grano=fila.cod_grano,
                     cod_provincia_origen=fila.cod_provincia_origen, cod_localidad_origen=fila.cod_localidad_origen,
                     cod_provincia_destino=fila.cod_provincia_destino,
                     cod_localidad_destino=fila.cod_localidad_destino)


def claves_de_cpe(cpe: arca_wscpe.CartaDePorte, ambiente: str) -> set[Clave]:
    """Lo mismo para la vista previa, que todavía no es una fila."""
    return claves_de(ambiente, cod_grano=cpe.carga.cod_grano,
                     cod_provincia_origen=cpe.origen.cod_provincia, cod_localidad_origen=cpe.origen.cod_localidad,
                     cod_provincia_destino=cpe.destino.cod_provincia,
                     cod_localidad_destino=cpe.destino.cod_localidad)


# ── Leer ───────────────────────────────────────────────────────────────────

def nombres(sesion: Session, claves: Iterable[Clave]) -> dict[Clave, str]:
    """`clave -> nombre` de las que están en la copia. **Una sola consulta**, sin importar cuántas claves sean."""
    pedidas = list(set(claves))
    if not pedidas:
        return {}
    filas = sesion.execute(
        select(CatalogoCpe.ambiente, CatalogoCpe.tipo, CatalogoCpe.cod_provincia, CatalogoCpe.codigo,
               CatalogoCpe.nombre)
        .where(tuple_(CatalogoCpe.ambiente, CatalogoCpe.tipo, CatalogoCpe.cod_provincia, CatalogoCpe.codigo)
               .in_(pedidas))).all()
    return {(a, t, p, c): n for a, t, p, c, n in filas}


class Traductor:
    """Los nombres de los códigos de un conjunto de cartas, traídos de la base de una vez."""

    def __init__(self, sesion: Session, claves: Iterable[Clave]):
        self._nombres = nombres(sesion, claves)

    def _buscar(self, ambiente: str, tipo: str, provincia: int, codigo: int | None) -> str | None:
        if codigo is None:
            return None
        nombre = self._nombres.get((ambiente, tipo, provincia, codigo))
        return nombre or None

    def grano(self, ambiente: str, codigo: int | None) -> str | None:
        return self._buscar(ambiente, CATALOGO_GRANO, 0, codigo)

    def provincia(self, ambiente: str, codigo: int | None) -> str | None:
        return self._buscar(ambiente, CATALOGO_PROVINCIA, 0, codigo)

    def localidad(self, ambiente: str, provincia: int | None, codigo: int | None) -> str | None:
        return None if provincia is None else self._buscar(ambiente, CATALOGO_LOCALIDAD, provincia, codigo)


# ── Completar ──────────────────────────────────────────────────────────────

def _guardar(sesion: Session, ambiente: str, tipo: str, cod_provincia: int, items: dict[int, str]) -> None:
    if not items:
        return
    ahora = datetime.now(UTC)
    filas = [{"ambiente": ambiente, "tipo": tipo, "cod_provincia": cod_provincia, "codigo": c,
              "nombre": n[:200], "actualizado_en": ahora} for c, n in items.items()]
    alta = insert(CatalogoCpe).values(filas)
    sesion.execute(alta.on_conflict_do_update(
        index_elements=["ambiente", "tipo", "cod_provincia", "codigo"],
        set_={"nombre": alta.excluded.nombre, "actualizado_en": alta.excluded.actualizado_en}))


def _pedida_hace_poco(sesion: Session, ambiente: str, tipo: str, cod_provincia: int) -> bool:
    ultima = sesion.scalar(select(func.max(CatalogoCpe.actualizado_en)).where(
        CatalogoCpe.ambiente == ambiente, CatalogoCpe.tipo == tipo, CatalogoCpe.cod_provincia == cod_provincia))
    return ultima is not None and datetime.now(UTC) - ultima < REPETIR_DESPUES_DE


def _pedir(cuits: list[str], que: str, hacer: Callable[[str], object]) -> dict[int, str] | None:
    """Corre `hacer(cuit)` con el primer CUIT por el que ARCA deje consultar. `None` si no se pudo, y lo registra."""
    for cuit in cuits:
        try:
            return asyncio.run(hacer(cuit))
        except arca_wscpe.CuitNoRelacionado:
            continue
        except Exception as e:  # mejor esfuerzo: ARCA caída, sin red, XML raro. Se registra y se sigue
            logger.warning("CPE: no se pudo pedir a ARCA %s: %s", que, e)
            return None
    logger.warning("CPE: ningún CUIT de las cartas deja pedir %s a ARCA", que)
    return None


def completar(sesion: Session, filas: Iterable[CartaPorte], ticket_de: Callable[[str], dict]) -> int:
    """Pide a ARCA y guarda los códigos de `filas` que la copia no tiene. Devuelve cuántos nombres sumó.

    `ticket_de(ambiente)` es el ticket de WSAA (el que ya tiene quien llama). **Nunca levanta**: si no hay ticket, si
    ARCA no contesta o si la base falla, lo registra y devuelve lo que alcanzó a sumar. Commitea lo que guarda.
    """
    por_ambiente: dict[str, list[CartaPorte]] = {}
    for fila in filas:
        por_ambiente.setdefault(fila.ambiente, []).append(fila)
    sumados = 0
    for ambiente, cartas in por_ambiente.items():
        try:
            sumados += _completar_ambiente(sesion, ambiente, cartas, ticket_de)
        except Exception as e:  # la base o el ticket: no es motivo para fallar la operación que sí anduvo
            sesion.rollback()
            logger.warning("CPE: no se completó el catálogo de %s: %s", ambiente, e)
    return sumados


def _completar_ambiente(sesion: Session, ambiente: str, cartas: list[CartaPorte],
                        ticket_de: Callable[[str], dict]) -> int:
    necesarias: set[Clave] = set().union(*(claves_de_fila(c) for c in cartas))
    faltan = necesarias - nombres(sesion, necesarias).keys()
    if not faltan:
        return 0
    cuits = list(dict.fromkeys(c.cuit_representada for c in cartas))
    try:
        ticket = ticket_de(ambiente)
    except Exception as e:  # sin certificado, sin delegación, ARCA sin contestar
        logger.warning("CPE: sin ticket de %s para pedir los códigos: %s", ambiente, e)
        return 0
    token, sign = ticket["token"], ticket["sign"]

    pedidos: list[tuple[str, int, str, Callable[[str], object]]] = []
    if any(t == CATALOGO_GRANO for _, t, _, _ in faltan):
        pedidos.append((CATALOGO_GRANO, 0, "los granos",
                        lambda cuit: arca_wscpe.tipos_grano(cuit, token, sign, ambiente)))
    if any(t == CATALOGO_PROVINCIA for _, t, _, _ in faltan):
        pedidos.append((CATALOGO_PROVINCIA, 0, "las provincias",
                        lambda cuit: arca_wscpe.provincias(cuit, token, sign, ambiente)))
    for provincia in sorted({p for _, t, p, _ in faltan if t == CATALOGO_LOCALIDAD}):
        pedidos.append((CATALOGO_LOCALIDAD, provincia, f"las localidades de la provincia {provincia}",
                        lambda cuit, p=provincia: arca_wscpe.localidades(
                            cuit, token, sign, cod_provincia=p, ambiente=ambiente)))

    sumados = 0
    for tipo, provincia, que, hacer in pedidos:
        if _pedida_hace_poco(sesion, ambiente, tipo, provincia):
            continue
        items = _pedir(cuits, que, hacer)
        if items:
            _guardar(sesion, ambiente, tipo, provincia, items)
            sesion.commit()
            sumados += len(items)
    return sumados
