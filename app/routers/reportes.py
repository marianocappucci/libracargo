"""Los reportes del negocio: un catálogo, y cada uno con sus parámetros.

Son **de lectura** y agregan en la base: ninguno devuelve filas de detalle. Para
el detalle están los listados, que tienen sus propios filtros y su impresión.

`GET /api/reportes` devuelve el **catálogo**: qué reportes hay, qué contesta cada
uno y **qué parámetros acepta**. La pantalla se arma con eso en vez de repetir la
lista del lado del frontend — un reporte nuevo aparece solo, y uno que cambia sus
parámetros no queda con la pantalla vieja ofreciendo un filtro que ya no existe.
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


class Reporte(BaseModel):
    """Una entrada del catálogo."""

    slug: str
    titulo: str
    #: Qué pregunta contesta, en una línea. Es lo que se lee antes de entrar.
    descripcion: str
    #: Los parámetros que acepta, en el orden en que conviene ofrecerlos.
    parametros: list[str]


#: El catálogo. `parametros` usa nombres que la pantalla sabe dibujar:
#: `rango`, `cliente`, `fletero`, `tercero`, `razon_social`, `origen`,
#: `destino`, `medio_pago`, `tipo_caja`, `rol`, `incluir_en_cero`, `limite`.
CATALOGO = [
    Reporte(slug="resumen", titulo="Resumen del período",
            descripcion="Cuántas órdenes se hicieron, cuánto se facturó, cuánto se "
                        "cobró y cuánto se pagó. Se puede acotar a un cliente o a un "
                        "fletero.",
            parametros=["rango", "cliente", "fletero"]),
    Reporte(slug="por-cliente", titulo="Clientes",
            descripcion="Ranking de clientes por lo facturado en el período, con las "
                        "órdenes que hizo cada uno y **su saldo de hoy** — que no se "
                        "acota al período, porque el saldo no tiene rango.",
            parametros=["rango", "cliente", "limite"]),
    Reporte(slug="por-fletero", titulo="Fleteros",
            descripcion="Lo mismo del lado del transporte: qué fletero movió más, la "
                        "comisión de sus órdenes y su saldo de hoy.",
            parametros=["rango", "fletero", "limite"]),
    Reporte(slug="pendientes-de-facturar", titulo="Pendientes de facturar",
            descripcion="Las órdenes que todavía no salieron en ningún comprobante, "
                        "agrupadas por cliente: a quién hay que facturarle y por cuánto.",
            parametros=["rango", "cliente"]),
    Reporte(slug="saldos", titulo="Saldos de cuenta corriente",
            descripcion="Las tres cuentas corrientes de una vez, con el último "
                        "movimiento de cada una. En el sistema viejo había que abrirlas "
                        "de a una, y son 267.",
            parametros=["rol", "tercero", "incluir_en_cero"]),
    Reporte(slug="caja", titulo="Caja",
            descripcion="Ingresos y egresos del período, abiertos por tipo y medio de "
                        "pago. Se puede acotar a un tercero.",
            parametros=["rango", "tercero", "medio_pago", "tipo_caja"]),
    Reporte(slug="por-razon-social", titulo="Facturado por razón social",
            descripcion="Cuánto facturó cada razón social propia en el período.",
            parametros=["rango", "razon_social"]),
    Reporte(slug="por-ruta", titulo="Rutas más transitadas",
            descripcion="Origen y destino como par —la ida y la vuelta son dos rutas "
                        "distintas—, con las órdenes, la cantidad y lo que dejaron.",
            parametros=["rango", "origen", "destino", "cliente", "fletero", "limite"]),
]


class Resumen(BaseModel):
    desde: date | None
    hasta: date | None
    cliente_id: int | None
    fletero_id: int | None
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


class FilaDePendiente(BaseModel):
    cliente_id: int
    cliente: str
    ordenes: int
    desde: date | None
    hasta: date | None
    total: Decimal


@router.get("", response_model=list[Reporte])
def catalogo():
    """Qué reportes hay, qué contesta cada uno y qué parámetros acepta."""
    return CATALOGO


@router.get("/resumen", response_model=Resumen)
def resumen(sesion: Session = Depends(obtener_sesion),
            desde: date | None = None, hasta: date | None = None,
            cliente_id: int | None = None, fletero_id: int | None = None):
    return servicio.resumen(sesion, desde, hasta, cliente_id, fletero_id)


@router.get("/por-cliente", response_model=list[FilaDeTercero])
def por_cliente(sesion: Session = Depends(obtener_sesion),
                desde: date | None = None, hasta: date | None = None,
                cliente_id: int | None = None,
                limite: int = Query(default=100, ge=1, le=1000)):
    return servicio.por_tercero(sesion, RolCuenta.CLIENTE, desde, hasta, limite, cliente_id)


@router.get("/por-fletero", response_model=list[FilaDeTercero])
def por_fletero(sesion: Session = Depends(obtener_sesion),
                desde: date | None = None, hasta: date | None = None,
                fletero_id: int | None = None,
                limite: int = Query(default=100, ge=1, le=1000)):
    return servicio.por_tercero(sesion, RolCuenta.FLETERO, desde, hasta, limite, fletero_id)


@router.get("/pendientes-de-facturar", response_model=list[FilaDePendiente])
def pendientes_de_facturar(sesion: Session = Depends(obtener_sesion),
                           desde: date | None = None, hasta: date | None = None,
                           cliente_id: int | None = None,
                           limite: int = Query(default=200, ge=1, le=1000)):
    return servicio.pendientes_de_facturar(sesion, desde, hasta, cliente_id, limite)


@router.get("/saldos", response_model=list[FilaDeSaldo])
def saldos(sesion: Session = Depends(obtener_sesion),
           rol: RolCuenta | None = None, tercero_id: int | None = None,
           # Por omisión **no** se muestran las cuentas en cero: son las que ya
           # están saldadas y llenarían el papel. Se piden explícitamente.
           incluir_en_cero: bool = Query(default=False)):
    return servicio.saldos(sesion, rol, incluir_en_cero, tercero_id)


@router.get("/caja", response_model=list[FilaDeCaja])
def caja(sesion: Session = Depends(obtener_sesion),
         desde: date | None = None, hasta: date | None = None,
         tercero_id: int | None = None, medio_pago: MedioPago | None = None,
         tipo: TipoMovimientoCaja | None = None):
    return servicio.caja(sesion, desde, hasta, tercero_id, medio_pago, tipo)


@router.get("/por-razon-social", response_model=list[FilaDeRazonSocial])
def por_razon_social(sesion: Session = Depends(obtener_sesion),
                     desde: date | None = None, hasta: date | None = None,
                     razon_social_id: int | None = None):
    return servicio.por_razon_social(sesion, desde, hasta, razon_social_id)


@router.get("/por-ruta", response_model=list[FilaDeRuta])
def por_ruta(sesion: Session = Depends(obtener_sesion),
             desde: date | None = None, hasta: date | None = None,
             origen_id: int | None = None, destino_id: int | None = None,
             cliente_id: int | None = None, fletero_id: int | None = None,
             limite: int = Query(default=50, ge=1, le=500)):
    return servicio.por_ruta(sesion, desde, hasta, limite,
                             origen_id, destino_id, cliente_id, fletero_id)
