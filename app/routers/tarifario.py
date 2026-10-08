"""El tarifario de referencia (ADR-038): consultarlo cualquiera del staff; cargarlo, sólo un administrador."""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin, require_staff
from app.db import obtener_sesion
from app.models.tarifario import TarifaDeReferencia, Tarifario
from app.schemas.tarifario import FilaOut, ReferenciaOut, SugerenciaOut, TarifarioOut
from app.servicios import tarifario as servicio

router = APIRouter(prefix="/api/tarifario", tags=["tarifario"], dependencies=[Depends(require_staff)])

#: Un tarifario razonable tiene unos mil km; esto es un tope contra un archivo equivocado.
MAX_BYTES = 2 * 1024 * 1024


def _resumen(sesion: Session, t: Tarifario) -> TarifarioOut:
    filas, desde, hasta = sesion.execute(
        select(func.count(), func.min(TarifaDeReferencia.km), func.max(TarifaDeReferencia.km))
        .where(TarifaDeReferencia.tarifario_id == t.id)).one()
    return TarifarioOut(id=t.id, vigencia=t.vigencia, nombre=t.nombre, valor_estadia=t.valor_estadia,
                        filas=filas, km_desde=desde, km_hasta=hasta)


@router.get("", response_model=list[TarifarioOut])
def listar(sesion: Session = Depends(obtener_sesion)):
    """Las ediciones cargadas, la más nueva primero."""
    return [_resumen(sesion, t) for t in sesion.scalars(select(Tarifario).order_by(Tarifario.vigencia.desc()))]


@router.get("/referencia", response_model=ReferenciaOut)
def referencia(km: int = Query(ge=1, le=99999), fecha: date | None = None, sesion: Session = Depends(obtener_sesion)):
    """La tarifa por tonelada de referencia para `km`, con el tarifario que regía en `fecha` (hoy si no se dice)."""
    ref = servicio.referencia(sesion, km, fecha or date.today())
    if ref is None:
        raise HTTPException(404, "no hay un tarifario de referencia cargado para esa fecha")
    return ref


@router.get("/sugerencia", response_model=SugerenciaOut)
def sugerencia(cliente_id: int, sesion: Session = Depends(obtener_sesion)):
    """El porcentaje sobre la referencia del último viaje de ese cliente: una sugerencia, varía por viaje."""
    s = servicio.porcentaje_sugerido(sesion, cliente_id)
    if s is None:
        raise HTTPException(404, "ese cliente todavía no tiene un viaje con km y tarifa por tonelada")
    return s


@router.get("/{tarifario_id}/filas", response_model=list[FilaOut])
def filas(tarifario_id: int, sesion: Session = Depends(obtener_sesion)):
    if sesion.get(Tarifario, tarifario_id) is None:
        raise HTTPException(404, f"no existe el tarifario {tarifario_id}")
    return list(sesion.execute(select(TarifaDeReferencia.km, TarifaDeReferencia.tarifa)
                               .where(TarifaDeReferencia.tarifario_id == tarifario_id)
                               .order_by(TarifaDeReferencia.km)).mappings())


@router.post("", response_model=TarifarioOut, status_code=201, dependencies=[Depends(require_admin)])
def cargar(archivo: UploadFile = File(...), vigencia: date = Form(...), nombre: str = Form(..., min_length=1),
           valor_estadia: str | None = Form(default=None), sesion: Session = Depends(obtener_sesion),
           actual: dict = Depends(get_current_user)):
    """Carga una edición desde un CSV `km;tarifa`. Si ya hay una con esa vigencia, **la reemplaza entera**."""
    contenido = archivo.file.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise HTTPException(422, "el archivo es demasiado grande para un tarifario")
    try:
        filas_leidas = servicio.leer_csv(contenido)
        estadia = servicio._numero(valor_estadia) if valor_estadia and valor_estadia.strip() else None
    except servicio.TarifarioInvalido as e:
        raise HTTPException(422, str(e)) from None
    except (ValueError, InvalidOperation):
        raise HTTPException(422, "el valor de estadía no es un número") from None
    if estadia is not None and estadia < Decimal(0):
        raise HTTPException(422, "el valor de estadía no puede ser negativo")
    t = servicio.cargar(sesion, actual, vigencia=vigencia, nombre=nombre.strip(), filas=filas_leidas,
                        valor_estadia=estadia)
    sesion.commit()
    return _resumen(sesion, t)
