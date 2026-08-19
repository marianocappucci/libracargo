"""Los reportes del negocio.

Son **de lectura**, y agregan en la base: ninguno devuelve filas de detalle. Para
el detalle están los listados, que tienen sus propios filtros y su impresión.

Todos aceptan el mismo par `desde`/`hasta` y **devuelven el rango que usaron**,
para que la pantalla y el papel puedan imprimirlo al lado del número: un total
sin su universo es un número que nadie puede verificar.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import obtener_sesion
from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja
from app.servicios import reportes as servicio

router = APIRouter(prefix="/api/reportes", tags=["reportes"],
                   dependencies=[Depends(require_staff)])


class Resumen(BaseModel):
    desde: date | None
    hasta: date | None
    ordenes: int
    ordenes_anuladas: int
    ordenes_pendientes: int
    tarifa: Decimal
    iva: Decimal
    total: Decimal
    comision: Decimal
    comprobantes: int
    facturado: Decimal
    movimientos_caja: int
    cobrado: Decimal
    pagado: Decimal


class FilaDeTercero(BaseModel):
    tercero_id: int
    tercero: str
    ordenes: int
    facturado: Decimal
    comision: Decimal
    #: **No** acotado al rango: lo facturado en el período y lo que el tercero
    #: debe son dos preguntas distintas.
    saldo: Decimal


class FilaDeSaldo(BaseModel):
    tercero_id: int
    rol: RolCuenta
    tercero: str
    movimientos: int
    ultimo_movimiento: date | None
    saldo: Decimal


class FilaDeCaja(BaseModel):
    tipo: TipoMovimientoCaja
    medio_pago: MedioPago
    movimientos: int
    importe: Decimal


class FilaDeRazonSocial(BaseModel):
    razon_social_id: int
    razon_social: str
    comprobantes: int
    neto: Decimal
    iva: Decimal
    total: Decimal


class FilaDeRuta(BaseModel):
    origen: str
    destino: str
    ordenes: int
    total: Decimal
    comision: Decimal
    cantidad: Decimal


@router.get("/resumen", response_model=Resumen)
def resumen(sesion: Session = Depends(obtener_sesion),
            desde: date | None = Query(default=None), hasta: date | None = Query(default=None)):
    return servicio.resumen(sesion, desde, hasta)


@router.get("/por-cliente", response_model=list[FilaDeTercero])
def por_cliente(sesion: Session = Depends(obtener_sesion),
                desde: date | None = None, hasta: date | None = None,
                limite: int = Query(default=100, ge=1, le=1000)):
    return servicio.por_tercero(sesion, RolCuenta.CLIENTE, desde, hasta, limite)


@router.get("/por-fletero", response_model=list[FilaDeTercero])
def por_fletero(sesion: Session = Depends(obtener_sesion),
                desde: date | None = None, hasta: date | None = None,
                limite: int = Query(default=100, ge=1, le=1000)):
    return servicio.por_tercero(sesion, RolCuenta.FLETERO, desde, hasta, limite)


@router.get("/saldos", response_model=list[FilaDeSaldo])
def saldos(sesion: Session = Depends(obtener_sesion),
           rol: RolCuenta | None = None,
           # Por omisión **no** se muestran las cuentas en cero: son las que ya
           # están saldadas y llenarían el papel. Se piden explícitamente.
           incluir_en_cero: bool = Query(default=False)):
    return servicio.saldos(sesion, rol, incluir_en_cero)


@router.get("/caja", response_model=list[FilaDeCaja])
def caja(sesion: Session = Depends(obtener_sesion),
         desde: date | None = None, hasta: date | None = None):
    return servicio.caja(sesion, desde, hasta)


@router.get("/por-razon-social", response_model=list[FilaDeRazonSocial])
def por_razon_social(sesion: Session = Depends(obtener_sesion),
                     desde: date | None = None, hasta: date | None = None):
    return servicio.por_razon_social(sesion, desde, hasta)


@router.get("/por-ruta", response_model=list[FilaDeRuta])
def por_ruta(sesion: Session = Depends(obtener_sesion),
             desde: date | None = None, hasta: date | None = None,
             limite: int = Query(default=50, ge=1, le=500)):
    return servicio.por_ruta(sesion, desde, hasta, limite)
