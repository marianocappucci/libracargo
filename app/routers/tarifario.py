"""El tarifario de referencia (ADR-038): consultarlo cualquiera del staff; cargarlo, sólo un administrador."""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin, require_staff
from app.db import obtener_sesion
from app.models.tarifario import TarifaDeReferencia, Tarifario
from app.schemas.tarifario import FilaOut, ReferenciaOut, SugerenciaOut, TarifarioOut, VistaPreviaOut
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


def _leer(contenido: bytes) -> servicio.TarifarioLeido:
    """El PDF que publica el sector (se reconoce por `%PDF`) o un CSV `km;tarifa`."""
    if len(contenido) > MAX_BYTES:
        raise HTTPException(422, "el archivo es demasiado grande para un tarifario")
    try:
        if contenido.lstrip()[:5] == b"%PDF-":
            return servicio.leer_pdf(contenido)
        return servicio.TarifarioLeido(filas=servicio.leer_csv(contenido), vigencia=None, valor_estadia=None,
                                       nombre="")
    except servicio.TarifarioInvalido as e:
        raise HTTPException(422, str(e)) from None


def _estadia(texto: str | None) -> Decimal | None:
    if not texto or not texto.strip():
        return None
    try:
        valor = servicio._numero(texto)
    except (ValueError, InvalidOperation):
        raise HTTPException(422, "el valor de estadía no es un número") from None
    if valor < Decimal(0):
        raise HTTPException(422, "el valor de estadía no puede ser negativo")
    return valor


#: Los km que se muestran en la vista previa, para comparar a ojo contra el PDF.
_MUESTRA = (1, 10, 50, 80, 100, 200, 500, 1000)


@router.post("/previsualizar", response_model=VistaPreviaOut, dependencies=[Depends(require_admin)])
def previsualizar(archivo: UploadFile = File(...), sesion: Session = Depends(obtener_sesion)):
    """Lee el PDF (o el CSV) y dice lo que cargaría, **sin guardar nada**: para revisarlo antes de confirmar."""
    leido = _leer(archivo.file.read(MAX_BYTES + 1))
    existe = (leido.vigencia is not None and
              sesion.scalar(select(Tarifario.id).where(Tarifario.vigencia == leido.vigencia)) is not None)
    return VistaPreviaOut(
        vigencia=leido.vigencia, nombre=leido.nombre or None, valor_estadia=leido.valor_estadia,
        filas=len(leido.filas), km_desde=min(leido.filas), km_hasta=max(leido.filas),
        muestra=[FilaOut(km=k, tarifa=leido.filas[k]) for k in _MUESTRA if k in leido.filas],
        reemplaza=existe)


@router.post("", response_model=TarifarioOut, status_code=201, dependencies=[Depends(require_admin)])
def cargar(archivo: UploadFile = File(...), vigencia: date | None = Form(default=None),
           nombre: str | None = Form(default=None), valor_estadia: str | None = Form(default=None),
           sesion: Session = Depends(obtener_sesion), actual: dict = Depends(get_current_user)):
    """Carga una edición desde el **PDF que publica el sector** o desde un CSV `km;tarifa` (ADR-039).

    Del PDF salen la vigencia, el nombre y el valor de estadía; lo que venga en el formulario **manda** sobre lo
    leído. Si ya hay una edición con esa vigencia, **la reemplaza entera**.
    """
    leido = _leer(archivo.file.read(MAX_BYTES + 1))
    vigencia_final = vigencia or leido.vigencia
    if vigencia_final is None:
        raise HTTPException(422, "indicá la vigencia: el archivo no la dice")
    nombre_final = (nombre or "").strip() or leido.nombre or f"Tarifa de referencia {vigencia_final:%d-%m-%Y}"
    estadia = _estadia(valor_estadia) if valor_estadia and valor_estadia.strip() else leido.valor_estadia
    t = servicio.cargar(sesion, actual, vigencia=vigencia_final, nombre=nombre_final, filas=leido.filas,
                        valor_estadia=estadia)
    sesion.commit()
    return _resumen(sesion, t)
