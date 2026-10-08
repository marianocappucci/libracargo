"""El tarifario de referencia: cargarlo y consultar la tarifa por tonelada de unos km en una fecha (ADR-038)."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AccionAuditoria, OrdenCarga
from app.models.tarifario import TarifaDeReferencia, Tarifario
from app.servicios import auditoria

CENTAVO = Decimal("0.01")


class TarifarioInvalido(ValueError):
    """El archivo del tarifario no se puede leer. El mensaje dice en qué línea y por qué."""


def _numero(texto: str) -> Decimal:
    """`9.636,69`, `9636,69` o `9636.69` → `Decimal('9636.69')`. Con coma, el punto es de miles."""
    t = texto.strip().replace("$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return Decimal(t)


def leer_csv(contenido: bytes) -> dict[int, Decimal]:
    """`km;tarifa` (o con coma como separador de columnas), con o sin encabezado. Un km repetido es un error."""
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")
    primera = texto.strip().splitlines()[0] if texto.strip() else ""
    separador = ";" if ";" in primera or "," not in primera else ","
    filas: dict[int, Decimal] = {}
    for n, fila in enumerate(csv.reader(io.StringIO(texto), delimiter=separador), 1):
        if not fila or not "".join(fila).strip():
            continue
        if len(fila) < 2:
            raise TarifarioInvalido(f"línea {n}: hacen falta dos columnas, km y tarifa")
        km_texto, tarifa_texto = fila[0].strip(), fila[1].strip()
        if n == 1 and not km_texto.replace(".", "").isdigit():
            continue  # el encabezado
        try:
            km = int(km_texto.replace(".", ""))
            tarifa = _numero(tarifa_texto)
        except (ValueError, InvalidOperation):
            raise TarifarioInvalido(f"línea {n}: «{';'.join(fila)}» no es un km y una tarifa") from None
        if km < 1 or tarifa < 0:
            raise TarifarioInvalido(f"línea {n}: el km tiene que ser 1 o más y la tarifa no puede ser negativa")
        if km in filas:
            raise TarifarioInvalido(f"línea {n}: el km {km} está repetido")
        filas[km] = tarifa.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    if not filas:
        raise TarifarioInvalido("el archivo no tiene ninguna fila de km y tarifa")
    return filas


def cargar(sesion: Session, usuario: dict | None, *, vigencia: date, nombre: str, filas: dict[int, Decimal],
           valor_estadia: Decimal | None = None) -> Tarifario:
    """Carga (o reemplaza entero) el tarifario de esa vigencia. **No commitea.**"""
    tarifario = sesion.scalar(select(Tarifario).where(Tarifario.vigencia == vigencia))
    accion = AccionAuditoria.MODIFICACION if tarifario else AccionAuditoria.ALTA
    if tarifario is None:
        tarifario = Tarifario(vigencia=vigencia, nombre=nombre, valor_estadia=valor_estadia)
        sesion.add(tarifario)
    else:
        tarifario.nombre, tarifario.valor_estadia = nombre, valor_estadia
    sesion.flush()
    sesion.execute(delete(TarifaDeReferencia).where(TarifaDeReferencia.tarifario_id == tarifario.id))
    sesion.add_all(TarifaDeReferencia(tarifario_id=tarifario.id, km=km, tarifa=t) for km, t in sorted(filas.items()))
    sesion.flush()
    auditoria.registrar(sesion, usuario, "tarifario", tarifario.id, accion, despues={
        "vigencia": vigencia.isoformat(), "nombre": nombre, "filas": len(filas),
        "km_desde": min(filas), "km_hasta": max(filas),
        "valor_estadia": str(valor_estadia) if valor_estadia is not None else None})
    return tarifario


def vigente(sesion: Session, fecha: date) -> Tarifario | None:
    """El tarifario que regía en `fecha`: el de vigencia más reciente que no sea posterior."""
    return sesion.scalar(select(Tarifario).where(Tarifario.vigencia <= fecha)
                         .order_by(Tarifario.vigencia.desc()).limit(1))


def referencia(sesion: Session, km: int, fecha: date) -> dict | None:
    """La tarifa de referencia por tonelada para `km` en `fecha`, o `None` si no hay tarifario o no tiene ese km.

    Un km que no está en la tabla (más allá de su último km) **no se extrapola**: se informa que falta.
    """
    tarifario = vigente(sesion, fecha)
    if tarifario is None:
        return None
    tarifa = sesion.scalar(select(TarifaDeReferencia.tarifa).where(
        TarifaDeReferencia.tarifario_id == tarifario.id, TarifaDeReferencia.km == km))
    return {"tarifario_id": tarifario.id, "vigencia": tarifario.vigencia, "nombre": tarifario.nombre, "km": km,
            "tarifa": tarifa, "valor_estadia": tarifario.valor_estadia}


def porcentaje_sugerido(sesion: Session, cliente_id: int) -> dict | None:
    """El porcentaje sobre la referencia que se usó en el último viaje de ese cliente con km y tarifa por tonelada.

    El porcentaje **varía por viaje** (decisión del humano, 2026-10-08): esto es sólo una sugerencia para el
    próximo, sacada del último que se cargó. `None` si no hay ninguno o su tarifa de referencia no se conoce.
    """
    ultimas = sesion.scalars(
        select(OrdenCarga).where(OrdenCarga.cliente_id == cliente_id, OrdenCarga.km.is_not(None),
                                 OrdenCarga.tarifa_tonelada.is_not(None))
        .order_by(OrdenCarga.fecha.desc(), OrdenCarga.id.desc()).limit(1))
    orden = next(iter(ultimas), None)
    if orden is None:
        return None
    ref = referencia(sesion, orden.km, orden.fecha)
    if ref is None or not ref["tarifa"]:
        return None
    porcentaje = (orden.tarifa_tonelada * 100 / ref["tarifa"]).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return {"porcentaje": porcentaje, "orden_id": orden.id, "fecha": orden.fecha, "km": orden.km,
            "tarifa_tonelada": orden.tarifa_tonelada, "tarifa_referencia": ref["tarifa"]}
