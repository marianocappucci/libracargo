"""Los reportes del negocio: un catálogo, y cada uno con sus parámetros.

Son **de lectura**, y vienen en dos familias:

* Los **agregados**, que es lo que había desde F6: cuánto se facturó, quién debe,
  qué ruta rindió. Devuelven una fila por grupo.
* Los **listados** (`detalle=True`), que devuelven las filas de detalle de una
  pantalla —órdenes, comprobantes, caja— para poder imprimirlas. Antes cada
  listado tenía su propio botón de imprimir arriba a la derecha, y como ninguno
  obligaba a poner fechas, el papel salía de noventa hojas. Acá el rango **es
  obligatorio**: sin `desde` y `hasta` el endpoint contesta 422 en vez de barrer
  la tabla entera.

`GET /api/reportes` devuelve el **catálogo**: qué reportes hay, qué contesta cada
uno y **qué parámetros acepta**. La pantalla se arma con eso en vez de repetir la
lista del lado del frontend — un reporte nuevo aparece solo, y uno que cambia sus
parámetros no queda con la pantalla vieja ofreciendo un filtro que ya no existe.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import (
    es_visitante_de_demo,
    get_current_user,
    require_admin,
    require_staff,
)
from app.db import obtener_sesion
from app.models.enums import (
    AccionAuditoria,
    MedioPago,
    RolCuenta,
    TipoComprobante,
    TipoMovimientoCaja,
)

# Los listados **no repiten la consulta**: llaman al mismo `listar` que sirve la
# pantalla. Si mañana el listado de órdenes cambia un filtro o un orden, el papel
# cambia con él — que es justo lo que no pasaba cuando cada pantalla armaba su
# propia impresión.
from app.routers import auditoria as r_auditoria
from app.routers import comprobantes as r_comprobantes
from app.routers import cuentas as r_cuentas
from app.routers import gastos as r_gastos
from app.routers import ordenes as r_ordenes
from app.schemas.comprobantes import ComprobanteOut
from app.schemas.cuentas import MovimientoCajaOut
from app.schemas.gastos import GastoOut
from app.schemas.ordenes import OrdenOut
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
    #: Devuelve **filas de detalle** en vez de agregados: es un listado para
    #: imprimir, no un resumen. Los de detalle **exigen rango** —la pantalla no
    #: los corre sin fechas y el endpoint las exige igual—, porque son los que
    #: sin filtro salen de noventa hojas.
    detalle: bool = False
    #: Sólo para admin. El log de actividad es el único: su endpoint pide rol
    #: admin, así que la pantalla tampoco lo ofrece al resto.
    solo_admin: bool = False


#: El catálogo. `parametros` usa nombres que la pantalla sabe dibujar:
#: `rango`, `cliente`, `fletero`, `proveedor`, `tercero`, `razon_social`,
#: `origen`, `destino`, `medio_pago`, `tipo_caja`, `rol`, `incluir_en_cero`,
#: `limite`, `entidad`, `usuario`, `accion`.
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

    # ── Los listados ────────────────────────────────────────────────────────
    #
    # Las filas de detalle de cada pantalla, para imprimir. Viven acá y no en un
    # botón arriba a la derecha de cada listado porque ahí no había forma de
    # obligar a poner fechas: se apretaba con la pantalla recién abierta y salían
    # las 4.337 órdenes en noventa hojas. Todos llevan `detalle=True`, que es lo
    # que hace que el rango sea obligatorio.
    Reporte(slug="listado-ordenes", titulo="Listado de órdenes",
            descripcion="Las órdenes del período, una por línea, con el tramo, el "
                        "fletero y los importes. Es el listado de la pantalla de "
                        "órdenes, en papel.",
            parametros=["rango", "cliente", "fletero", "origen", "destino"],
            detalle=True),
    Reporte(slug="listado-comprobantes", titulo="Listado de comprobantes",
            descripcion="Los comprobantes emitidos en el período, con su neto, su IVA "
                        "y su total. Los anulados salen marcados como tales.",
            parametros=["rango", "razon_social", "cliente"],
            detalle=True),
    Reporte(slug="listado-gastos", titulo="Listado de comprobantes de proveedores",
            descripcion="Lo que los proveedores entregaron en el período y a qué "
                        "fletero se le descontó.",
            parametros=["rango", "proveedor", "fletero"],
            detalle=True),
    Reporte(slug="listado-caja", titulo="Listado de movimientos de caja",
            descripcion="Los cobros y pagos del período, uno por línea, con el medio "
                        "de pago y el recibo.",
            parametros=["rango", "tercero", "medio_pago", "tipo_caja"],
            detalle=True),
    Reporte(slug="listado-logs", titulo="Listado del log de actividad",
            descripcion="Quién hizo qué en el período. Es el log de actividad en "
                        "papel; como el resto del log, sólo lo ve un administrador.",
            parametros=["rango", "entidad", "usuario", "accion"],
            detalle=True, solo_admin=True),
]


def _exigir_rango(desde: date | None, hasta: date | None) -> None:
    """Un listado sin fechas es el papel de noventa hojas que sacó estos botones
    de las pantallas. Se corta acá y no sólo en el frontend: la regla es del
    reporte, no del dibujo."""
    if desde is None or hasta is None:
        raise HTTPException(422, "el listado necesita un rango: elegí desde y hasta")


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
def catalogo(actual: dict = Depends(get_current_user)):
    """Qué reportes hay, qué contesta cada uno y qué parámetros acepta.

    🔑 **Los de admin se filtran acá, no en la pantalla.** Un reporte que al
    abrirlo contesta 403 es un ítem de menú roto, y la regla de quién es admin
    —incluido el visitante de la demo, que lee de más sin ser uno— ya vive en
    `libraauth`. Repetirla en el frontend sería la segunda copia de una regla de
    permisos: la que se olvida de actualizar.
    """
    ve_lo_de_admin = actual.get("role") == "admin" or es_visitante_de_demo(actual)
    return [r for r in CATALOGO if not r.solo_admin or ve_lo_de_admin]


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


# ── Los listados ────────────────────────────────────────────────────────────
#
# Cada uno delega en el `listar` de su pantalla: mismos filtros, mismo orden,
# misma paginación. Lo único que agregan es `_exigir_rango`.


@router.get("/listado-ordenes", response_model=list[OrdenOut])
def listado_ordenes(sesion: Session = Depends(obtener_sesion),
                    desde: date | None = None, hasta: date | None = None,
                    cliente_id: int | None = None, fletero_id: int | None = None,
                    origen_id: int | None = None, destino_id: int | None = None,
                    limite: int = Query(default=1000, ge=1, le=1000),
                    desplazamiento: int = Query(default=0, ge=0)):
    _exigir_rango(desde, hasta)
    return r_ordenes.listar(
        sesion=sesion, desde=desde, hasta=hasta,
        cliente_id=cliente_id, fletero_id=fletero_id,
        chofer_id=None, vehiculo_id=None,
        origen_id=origen_id, destino_id=destino_id,
        tipo_carga_id=None, razon_social_id=None,
        estado=None, facturada=None, q=None,
        limite=limite, desplazamiento=desplazamiento)


@router.get("/listado-comprobantes", response_model=list[ComprobanteOut])
def listado_comprobantes(sesion: Session = Depends(obtener_sesion),
                         desde: date | None = None, hasta: date | None = None,
                         razon_social_id: int | None = None,
                         cliente_id: int | None = None,
                         tipo: TipoComprobante | None = None,
                         limite: int = Query(default=1000, ge=1, le=1000),
                         desplazamiento: int = Query(default=0, ge=0)):
    _exigir_rango(desde, hasta)
    return r_comprobantes.listar(
        sesion=sesion, desde=desde, hasta=hasta,
        razon_social_id=razon_social_id, cliente_id=cliente_id, tipo=tipo,
        # `None` y no `False`: los anulados salen, marcados. Un número que falta
        # en la secuencia impresa no tiene explicación en el papel.
        anulado=None,
        limite=limite, desplazamiento=desplazamiento)


@router.get("/listado-gastos", response_model=list[GastoOut])
def listado_gastos(sesion: Session = Depends(obtener_sesion),
                   desde: date | None = None, hasta: date | None = None,
                   proveedor_id: int | None = None, fletero_id: int | None = None,
                   limite: int = Query(default=1000, ge=1, le=1000),
                   desplazamiento: int = Query(default=0, ge=0)):
    _exigir_rango(desde, hasta)
    return r_gastos.listar(
        sesion=sesion, desde=desde, hasta=hasta,
        proveedor_id=proveedor_id, fletero_id=fletero_id, anulado=None,
        limite=limite, desplazamiento=desplazamiento)


@router.get("/listado-caja", response_model=list[MovimientoCajaOut])
def listado_caja(sesion: Session = Depends(obtener_sesion),
                 desde: date | None = None, hasta: date | None = None,
                 tercero_id: int | None = None,
                 medio_pago: MedioPago | None = None,
                 tipo: TipoMovimientoCaja | None = None,
                 limite: int = Query(default=1000, ge=1, le=1000),
                 desplazamiento: int = Query(default=0, ge=0)):
    _exigir_rango(desde, hasta)
    return r_cuentas.listar_caja(
        sesion=sesion, desde=desde, hasta=hasta, tercero_id=tercero_id,
        medio_pago=medio_pago, tipo=tipo,
        limite=limite, desplazamiento=desplazamiento)


# 🔴 `require_admin` **además** del `require_staff` del router: el log es la
# única pantalla del producto que un operador no ve, y moverla a reportes no
# puede ser la forma de que la vea. Las dependencias del router y las de la ruta
# se suman, no se reemplazan.
@router.get("/listado-logs", response_model=list[r_auditoria.RegistroOut],
            dependencies=[Depends(require_admin)])
def listado_logs(sesion: Session = Depends(obtener_sesion),
                 desde: date | None = None, hasta: date | None = None,
                 entidad: str | None = None,
                 usuario: str | None = Query(default=None,
                                             description="nombre de usuario exacto"),
                 accion: AccionAuditoria | None = None,
                 limite: int = Query(default=500, ge=1, le=500),
                 desplazamiento: int = Query(default=0, ge=0)):
    """El log en papel. Devuelve las filas y no la página con su total: el
    encabezado de la hoja ya cuenta cuántas trajo."""
    _exigir_rango(desde, hasta)
    return r_auditoria.listar(
        sesion=sesion, entidad=entidad, entidad_id=None, usuario=usuario,
        accion=accion, desde=desde, hasta=hasta,
        limite=limite, desplazamiento=desplazamiento).registros
