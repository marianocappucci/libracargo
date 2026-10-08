"""El tarifario de referencia: cargarlo y consultar la tarifa por tonelada de unos km en una fecha (ADR-038)."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass
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


# ── Leer el PDF que publica el sector (ADR-039) ─────────────────────────────
#
# 🔑 **Los números del PDF vienen con otra tipografía, sin tabla de caracteres**: el extractor no ve «9.636,69»
# sino «(cid:497)(cid:558)(cid:494)…». Lo medido en la edición del 10 de abril de 2026: 488-497 son los dígitos
# 0-9, 558 el punto de miles y 559 la coma. **No se deja fijo**, porque otra edición puede numerar distinto: se
# deduce de la forma de las tarifas («ddd.ddd,dd») y el resultado se verifica (km consecutivos, tarifas que no
# bajan). Si algo no cierra, no se carga nada y se pide el CSV.

_MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
          "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}
_CID = re.compile(r"\(cid:(\d+)\)")
_PAR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})?) (\d{1,3}(?:\.\d{3})*,\d{2})(?![\d,])")
#: Menos filas que esto no es un tarifario: es otro PDF.
MIN_FILAS = 100


@dataclass(frozen=True)
class TarifarioLeido:
    filas: dict[int, Decimal]
    vigencia: date | None
    valor_estadia: Decimal | None
    nombre: str


def _palabras_cid(texto: str) -> list[list[int]]:
    """Las palabras hechas sólo de `(cid:N)`, como listas de N."""
    salida = []
    for palabra in texto.split():
        if _CID.fullmatch(palabra) or re.fullmatch(r"(?:\(cid:\d+\))+", palabra):
            salida.append([int(n) for n in _CID.findall(palabra)])
    return salida


def _deducir_cids(palabras: list[list[int]]) -> dict[int, str]:
    """`cid -> carácter`: la coma es lo que va 3 lugares antes del final de cada tarifa; el punto de miles, 7; los
    diez restantes, ordenados, son 0-9. Levanta `TarifarioInvalido` si no da exactamente eso."""
    comas = Counter(p[-3] for p in palabras if len(p) >= 4)
    if not comas:
        raise TarifarioInvalido("el PDF no tiene números con la forma de una tarifa («9.636,69»)")
    coma = comas.most_common(1)[0][0]
    puntos = Counter(p[-7] for p in palabras if len(p) >= 8 and p[-3] == coma)
    punto = puntos.most_common(1)[0][0] if puntos else None
    digitos = sorted({c for p in palabras for c in p} - {coma, punto})
    if len(digitos) != 10:
        raise TarifarioInvalido(f"no se pudieron reconocer los dígitos del PDF ({len(digitos)} símbolos en vez de 10)")
    mapa = {c: str(i) for i, c in enumerate(digitos)}
    mapa[coma] = ","
    if punto is not None:
        mapa[punto] = "."
    return mapa


def _verificar(filas: dict[int, Decimal]) -> None:
    if len(filas) < MIN_FILAS:
        raise TarifarioInvalido(f"del PDF salieron {len(filas)} filas: no parece un tarifario de referencia")
    kms = sorted(filas)
    consecutivos = next((i for i, k in enumerate(kms, start=kms[0]) if k != i), None)
    tramo = kms[: (consecutivos - kms[0]) if consecutivos else len(kms)]
    if kms[0] != 1 or len(tramo) < MIN_FILAS:
        raise TarifarioInvalido("los km del PDF no arrancan en 1 ni son consecutivos: no se pudo leer con seguridad")
    if any(filas[a] > filas[b] for a, b in zip(kms, kms[1:], strict=False)):
        raise TarifarioInvalido("las tarifas del PDF no crecen con los km: no se pudo leer con seguridad")


def leer_pdf(contenido: bytes) -> TarifarioLeido:
    """Las filas `km -> $/t`, la vigencia y el valor de estadía del PDF del tarifario de referencia."""
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]
    except Exception as e:  # noqa: BLE001 - un PDF roto llega con cualquier excepción de pdfminer
        raise TarifarioInvalido(f"no se pudo abrir el PDF: {type(e).__name__}") from None
    crudo = "\n".join(textos)
    palabras = _palabras_cid(crudo)
    if palabras:
        mapa = _deducir_cids(palabras)
        texto = _CID.sub(lambda m: mapa.get(int(m.group(1)), "?"), crudo)
    else:
        texto = crudo
    filas: dict[int, Decimal] = {}
    for km, tarifa in _PAR.findall(texto):
        filas[int(km.replace(".", ""))] = _numero(tarifa).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    _verificar(filas)

    vigencia = None
    fecha = re.search(r"(\d{1,2})\s+(" + "|".join(_MESES) + r")\s+(\d{4})", texto.upper())
    if fecha:
        try:
            vigencia = date(int(fecha.group(3)), _MESES[fecha.group(2)], int(fecha.group(1)))
        except ValueError:
            vigencia = None
    estadia = re.search(r"estad[ií]a:?\s*\$?\s*([\d.]+,\d{2})", texto, re.IGNORECASE)
    nombre = "Tarifa de referencia de cereales y oleaginosas"
    if vigencia:
        nombre += f", {vigencia.day} de {[k for k, v in _MESES.items() if v == vigencia.month][0].lower()}" \
                  f" de {vigencia.year}"
    return TarifarioLeido(filas=filas, vigencia=vigencia,
                          valor_estadia=_numero(estadia.group(1)) if estadia else None, nombre=nombre)
