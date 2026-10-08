"""Los seis ABM de maestros, armados con un mismo constructor.

Se comparte el constructor y no cada endpoint copiado seis veces porque las
seis tablas hacen lo mismo: listar con filtro, traer una, dar de alta, editar y
dar de baja. Lo que cambia de una a otra —el nombre de la columna de estado,
por dónde se busca, cómo se ordena— entra por parámetro.
"""

# 🔴 SIN `from __future__ import annotations` a propósito. Los endpoints se
# arman dentro de `construir_router`, donde el tipo del cuerpo es el parámetro
# `entrada`: con las anotaciones diferidas eso queda como el string "entrada",
# que Pydantic no puede resolver porque no es un nombre de módulo. El síntoma no
# es un error al importar — las rutas simplemente **no se registran**, y el
# `openapi()` explota mucho después con un mensaje que no nombra la causa.

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from libracore import geografia
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin, require_staff
from app.db import obtener_sesion
from app.models.enums import AccionAuditoria
from app.models.maestros import Chofer, Localidad, Tercero, TipoCarga, Vehiculo
from app.models.operacion import OrdenCarga
from app.schemas.maestros import (
    ChoferIn,
    ChoferOut,
    LocalidadIn,
    LocalidadOut,
    TerceroIn,
    TerceroOut,
    TipoCargaIn,
    TipoCargaOut,
    VehiculoIn,
    VehiculoOut,
)
from app.servicios import auditoria


def _a_salida(obj, salida, campo_activo: str):
    """La fila como la ve la API, con `activo` normalizado.

    Ver la nota de `app/schemas/maestros.py`: en la base esa columna se llama
    `activa` en una de las cinco tablas.
    """
    datos = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    datos["activo"] = getattr(obj, campo_activo)
    return salida.model_validate(datos)


def traducir_integridad(err: IntegrityError) -> HTTPException:
    """Una violación de unicidad es un 409, no un 500.

    El mensaje nombra la restricción y **nada más**: el `str()` de un error de
    psycopg arrastra el statement completo, y con él los valores de la fila.
    """
    nombre = getattr(getattr(err.orig, "diag", None), "constraint_name", None)
    if nombre:
        return HTTPException(409, f"ya existe un registro que choca con la restriccion {nombre}")
    return HTTPException(409, "el registro choca con una restriccion de la base")


def construir_router(
    *, prefijo: str, etiqueta: str, modelo, entrada, salida,
    campo_orden: str, buscar_en: tuple[str, ...], campo_activo: str = "activo",
    filtros: tuple[str, ...] = (), validar=None,
) -> APIRouter:
    """El ABM de un maestro. Dos costuras para lo que no comparten todos:

    - `filtros`: columnas enteras por las que se puede filtrar el listado por igualdad (`?fletero_id=7`).
    - `validar(sesion, obj, id_actual)`: se llama antes de guardar un alta o una modificación, con el objeto ya
      cargado; levanta `HTTPException` si no va (el CUIT repetido de `terceros`, ADR-040).
    """
    router = APIRouter(
        prefix=f"/api/{prefijo}", tags=[etiqueta], dependencies=[Depends(require_staff)]
    )

    def _traer(sesion: Session, id_: int):
        obj = sesion.get(modelo, id_)
        if obj is None:
            raise HTTPException(404, f"no existe {etiqueta} con id {id_}")
        return obj

    @router.get("", response_model=list[salida])
    def listar(
        sesion: Session = Depends(obtener_sesion),
        q: str | None = Query(default=None, description="busca en los campos de texto"),
        # `None` es "todos", y es distinto de `False`. Con un default en `True`
        # las filas dadas de baja desaparecerían de la única pantalla desde la
        # que se pueden volver a activar.
        activo: bool | None = Query(default=None),
        limite: int = Query(default=200, ge=1, le=1000),
        desplazamiento: int = Query(default=0, ge=0),
        request: Request = None,
    ):
        consulta = select(modelo)
        for campo in filtros:
            valor = request.query_params.get(campo) if request is not None else None
            if valor is not None:
                if not valor.isdigit():
                    raise HTTPException(422, f"{campo} tiene que ser un número")
                consulta = consulta.where(getattr(modelo, campo) == int(valor))
        if activo is not None:
            consulta = consulta.where(getattr(modelo, campo_activo).is_(activo))
        if q:
            patron = f"%{q.strip()}%"
            consulta = consulta.where(
                or_(*[cast(getattr(modelo, c), String).ilike(patron) for c in buscar_en])
            )
        consulta = (
            consulta.order_by(getattr(modelo, campo_orden))
            .limit(limite)
            .offset(desplazamiento)
        )
        return [_a_salida(o, salida, campo_activo) for o in sesion.scalars(consulta)]

    @router.get("/{id_}", response_model=salida)
    def traer(id_: int, sesion: Session = Depends(obtener_sesion)):
        return _a_salida(_traer(sesion, id_), salida, campo_activo)

    @router.post("", response_model=salida, status_code=201)
    def crear(datos: entrada, sesion: Session = Depends(obtener_sesion),
              actual: dict = Depends(get_current_user)):
        obj = modelo(**datos.model_dump(exclude={"activo"}))
        setattr(obj, campo_activo, datos.activo)
        if validar is not None:
            validar(sesion, obj, None)
        sesion.add(obj)
        try:
            # `flush` antes del asiento: sin id, la auditoría no puede decir a
            # qué fila se refiere.
            sesion.flush()
            auditoria.registrar(sesion, actual, prefijo, obj.id,
                                AccionAuditoria.ALTA, despues=obj)
            sesion.commit()
        except IntegrityError as err:
            sesion.rollback()
            raise traducir_integridad(err) from None
        sesion.refresh(obj)
        return _a_salida(obj, salida, campo_activo)

    @router.put("/{id_}", response_model=salida)
    def editar(id_: int, datos: entrada, sesion: Session = Depends(obtener_sesion),
               actual: dict = Depends(get_current_user)):
        obj = _traer(sesion, id_)
        antes = auditoria.instantanea(obj)
        for campo, valor in datos.model_dump(exclude={"activo"}).items():
            setattr(obj, campo, valor)
        setattr(obj, campo_activo, datos.activo)
        if validar is not None:
            validar(sesion, obj, obj.id)
        try:
            auditoria.registrar(sesion, actual, prefijo, obj.id,
                                AccionAuditoria.MODIFICACION, antes=antes, despues=obj)
            sesion.commit()
        except IntegrityError as err:
            sesion.rollback()
            raise traducir_integridad(err) from None
        sesion.refresh(obj)
        return _a_salida(obj, salida, campo_activo)

    @router.delete("/{id_}", response_model=salida)
    def dar_de_baja(id_: int, sesion: Session = Depends(obtener_sesion),
                    actual: dict = Depends(get_current_user)):
        """Baja **lógica**, siempre.

        Un tercero borrado de verdad se lleva puesto el historial: las órdenes y
        los movimientos de cuenta lo referencian. El legado ya tenía movimientos
        huérfanos porque no había una sola clave foránea; acá la FK existe, así
        que un DELETE real fallaría o borraría en cascada, y las dos cosas son
        peores que una fila inactiva.
        """
        obj = _traer(sesion, id_)
        antes = auditoria.instantanea(obj)
        setattr(obj, campo_activo, False)
        auditoria.registrar(sesion, actual, prefijo, obj.id,
                            AccionAuditoria.BAJA, antes=antes, despues=obj)
        sesion.commit()
        sesion.refresh(obj)
        return _a_salida(obj, salida, campo_activo)

    return router


_ROLES = {"cliente": "es_cliente", "fletero": "es_fletero", "proveedor": "es_proveedor"}


def _digitos(cuit: str | None) -> str:
    return "".join(c for c in (cuit or "") if c.isdigit())


def _roles_de(t: Tercero) -> list[str]:
    return [rol for rol, columna in _ROLES.items() if getattr(t, columna)]


def _cuit_no_repetido(sesion: Session, obj: Tercero, id_actual: int | None) -> None:
    """Una persona o empresa es **una sola entidad** con uno o más roles (ADR-040): un CUIT que ya tiene otra
    entidad no se vuelve a dar de alta; se le suma el rol a la que existe.

    Sólo cuenta un CUIT de 11 dígitos. El legado dejó CUIT de relleno («1») en 68 terceros de Suitrans: esos no
    identifican a nadie y no se comparan.
    """
    cuit = _digitos(obj.cuit)
    if len(cuit) != 11:
        return
    limpio = func.replace(func.replace(func.coalesce(Tercero.cuit, ""), "-", ""), ".", "")
    consulta = select(Tercero).where(limpio == cuit)
    if id_actual is not None:
        consulta = consulta.where(Tercero.id != id_actual)
    otro = sesion.scalars(consulta.order_by(Tercero.id).limit(1)).first()
    if otro is None:
        return
    roles = _roles_de(otro)
    raise HTTPException(409, {
        "mensaje": (f"El CUIT {obj.cuit} ya es de «{otro.razon_social}»"
                    + (f" ({', '.join(roles)})" if roles else "")
                    + ". Sumale el rol en vez de cargarla de nuevo."),
        "existente": {"id": otro.id, "razon_social": otro.razon_social, "roles": roles, "activo": otro.activo},
    })


terceros = construir_router(
    prefijo="terceros", etiqueta="terceros", modelo=Tercero,
    entrada=TerceroIn, salida=TerceroOut, campo_orden="razon_social",
    buscar_en=("razon_social", "cuit", "localidad", "contacto"),
    validar=_cuit_no_repetido,
)


@terceros.post("/{id_}/roles/{rol}", response_model=TerceroOut)
def sumar_rol(id_: int, rol: str, sesion: Session = Depends(obtener_sesion),
              actual: dict = Depends(get_current_user)):
    """Le suma un rol (cliente, fletero o proveedor) a una entidad que ya existe, y la reactiva si estaba de baja.

    Es lo que ofrece la pantalla cuando el alta choca con un CUIT existente (ADR-040).
    """
    if rol not in _ROLES:
        raise HTTPException(404, f"rol desconocido: {rol!r} (cliente, fletero o proveedor)")
    t = sesion.get(Tercero, id_)
    if t is None:
        raise HTTPException(404, f"no existe terceros con id {id_}")
    antes = auditoria.instantanea(t)
    setattr(t, _ROLES[rol], True)
    t.activo = True
    auditoria.registrar(sesion, actual, "terceros", t.id, AccionAuditoria.MODIFICACION, antes=antes, despues=t)
    sesion.commit()
    sesion.refresh(t)
    return _a_salida(t, TerceroOut, "activo")


# El filtro por rol va aparte del constructor: es lo único que `terceros` no
# comparte con los otros cinco maestros, y lo tiene porque es la tabla única que
# reemplazó a los tres maestros separados del legado.
@terceros.get("/rol/{rol}", response_model=list[TerceroOut])
def terceros_por_rol(
    rol: str,
    sesion: Session = Depends(obtener_sesion),
    solo_activos: bool = Query(default=True),
):
    columnas = {
        "cliente": Tercero.es_cliente,
        "fletero": Tercero.es_fletero,
        "proveedor": Tercero.es_proveedor,
    }
    if rol not in columnas:
        raise HTTPException(404, f"rol desconocido: {rol!r} (cliente, fletero o proveedor)")
    consulta = select(Tercero).where(columnas[rol].is_(True))
    if solo_activos:
        consulta = consulta.where(Tercero.activo.is_(True))
    consulta = consulta.order_by(Tercero.razon_social)
    return [_a_salida(o, TerceroOut, "activo") for o in sesion.scalars(consulta)]


localidades = construir_router(
    prefijo="localidades", etiqueta="localidades", modelo=Localidad,
    entrada=LocalidadIn, salida=LocalidadOut, campo_activo="activa",
    campo_orden="nombre", buscar_en=("nombre", "provincia"),
)

choferes = construir_router(
    prefijo="choferes", etiqueta="choferes", modelo=Chofer,
    entrada=ChoferIn, salida=ChoferOut, campo_orden="nombre",
    buscar_en=("nombre", "dni", "cuit", "telefono"),
    filtros=("fletero_id",),
)

vehiculos = construir_router(
    prefijo="vehiculos", etiqueta="vehiculos", modelo=Vehiculo,
    entrada=VehiculoIn, salida=VehiculoOut, campo_orden="patente_chasis",
    buscar_en=("patente_chasis", "patente_acoplado"),
    filtros=("fletero_id",),
)

tipos_carga = construir_router(
    prefijo="tipos-carga", etiqueta="tipos de carga", modelo=TipoCarga,
    entrada=TipoCargaIn, salida=TipoCargaOut, campo_orden="nombre",
    buscar_en=("nombre", "unidad_default"),
)

#: El orden es el del menú, no alfabético.
TODOS = [terceros, localidades, choferes, vehiculos, tipos_carga]


# ── Localidades: el catálogo de LibraCore y los parajes (ADR-041) ───────────
#
# El maestro sigue siendo el que usan las órdenes (FK). El catálogo censal de LibraCore es de sólo lectura y
# tiene las 4.027 localidades de Argentina: una localidad se **trae** de ahí (queda vinculada por su código
# censal) en vez de tipearse; lo que no está —un paraje, una planta, un campo con nombre— se carga a mano como
# **paraje**, con su provincia.


class _CatalogoIn(BaseModel):
    catalogo_id: str = Field(min_length=1, max_length=20)


class _UnificarIn(BaseModel):
    en_id: int


def _del_catalogo(catalogo_id: str) -> dict:
    loc = geografia.localidad(catalogo_id)
    if loc is None:
        raise HTTPException(404, f"no hay una localidad con código {catalogo_id!r} en el catálogo")
    return loc


@localidades.get("/buscar/combinado")
def buscar_localidades(q: str = Query(min_length=1), limite: int = Query(default=20, ge=1, le=100),
                       sesion: Session = Depends(obtener_sesion)):
    """Para el selector de origen y destino: lo que ya está en el maestro y, debajo, lo del catálogo que todavía
    no está (con su provincia). Lo del catálogo se trae con `POST /desde-catalogo` al elegirlo."""
    aguja = geografia.normalizar(q)
    propias = [loc for loc in sesion.scalars(select(Localidad).order_by(Localidad.nombre))
               if aguja in geografia.normalizar(loc.nombre)]
    propias.sort(key=lambda loc: (not geografia.normalizar(loc.nombre).startswith(aguja), loc.nombre))
    ya = {loc.catalogo_id for loc in propias if loc.catalogo_id} | set(
        sesion.scalars(select(Localidad.catalogo_id).where(Localidad.catalogo_id.is_not(None))))
    # Todo el Mercosur, con Argentina primero (ADR-042).
    catalogo = [c for c in geografia.localidades(q=q, limite=limite + len(ya), pais=None)
                if c["id"] not in ya][:limite]
    return {"maestro": [_a_salida(loc, LocalidadOut, "activa") for loc in propias[:limite]], "catalogo": catalogo}


@localidades.post("/desde-catalogo", response_model=LocalidadOut)
def traer_del_catalogo(datos: _CatalogoIn, response: Response, sesion: Session = Depends(obtener_sesion),
                       actual: dict = Depends(get_current_user)):
    """La localidad del maestro que corresponde a esa del catálogo: la que ya está vinculada, una del mismo nombre
    y provincia que se vincula, o una nueva (201)."""
    loc = _del_catalogo(datos.catalogo_id)
    existente = sesion.scalar(select(Localidad).where(Localidad.catalogo_id == loc["id"]))
    if existente is not None:
        return _a_salida(existente, LocalidadOut, "activa")
    mismo = next((x for x in sesion.scalars(select(Localidad).where(Localidad.catalogo_id.is_(None)))
                  if geografia.normalizar(x.nombre) == geografia.normalizar(loc["nombre"])
                  and geografia.normalizar(x.provincia or "") == geografia.normalizar(loc["provincia"])
                  and x.pais == loc["pais"]), None)
    if mismo is not None:
        antes = auditoria.instantanea(mismo)
        mismo.catalogo_id, mismo.es_paraje, mismo.activa = loc["id"], False, True
        auditoria.registrar(sesion, actual, "localidades", mismo.id, AccionAuditoria.MODIFICACION,
                            antes=antes, despues=mismo)
        sesion.commit()
        return _a_salida(mismo, LocalidadOut, "activa")
    nueva = Localidad(nombre=loc["nombre"], provincia=loc["provincia"], pais=loc["pais"], catalogo_id=loc["id"],
                      activa=True)
    sesion.add(nueva)
    try:
        sesion.flush()
        auditoria.registrar(sesion, actual, "localidades", nueva.id, AccionAuditoria.ALTA, despues=nueva)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    response.status_code = 201
    return _a_salida(nueva, LocalidadOut, "activa")


@localidades.post("/{id_}/vincular", response_model=LocalidadOut)
def vincular_al_catalogo(id_: int, datos: _CatalogoIn, sesion: Session = Depends(obtener_sesion),
                         actual: dict = Depends(get_current_user)):
    """Vincula una localidad que ya existe con una del catálogo (deja de ser paraje). Completa la provincia si
    faltaba; el nombre no se toca."""
    loc = _del_catalogo(datos.catalogo_id)
    obj = sesion.get(Localidad, id_)
    if obj is None:
        raise HTTPException(404, f"no existe localidades con id {id_}")
    otra = sesion.scalar(select(Localidad).where(Localidad.catalogo_id == loc["id"], Localidad.id != id_))
    if otra is not None:
        raise HTTPException(409, f"«{loc['nombre']}» del catálogo ya está vinculada a «{otra.nombre}» (id {otra.id})"
                                 ": si son la misma, unificalas")
    antes = auditoria.instantanea(obj)
    obj.catalogo_id, obj.es_paraje, obj.pais = loc["id"], False, loc["pais"]
    obj.provincia = obj.provincia or loc["provincia"]
    try:
        auditoria.registrar(sesion, actual, "localidades", obj.id, AccionAuditoria.MODIFICACION,
                            antes=antes, despues=obj)
        sesion.commit()
    except IntegrityError as err:
        sesion.rollback()
        raise traducir_integridad(err) from None
    return _a_salida(obj, LocalidadOut, "activa")


@localidades.post("/{id_}/unificar", response_model=LocalidadOut, dependencies=[Depends(require_admin)])
def unificar(id_: int, datos: _UnificarIn, sesion: Session = Depends(obtener_sesion),
             actual: dict = Depends(get_current_user)):
    """Dos localidades que son el mismo lugar («Pto. San Martín» y «Pto San Martín»): las órdenes de `id_` pasan
    a `en_id` y `id_` queda dada de baja. Sólo un administrador: mueve el origen o el destino de órdenes."""
    if id_ == datos.en_id:
        raise HTTPException(422, "una localidad no se unifica consigo misma")
    origen, destino = sesion.get(Localidad, id_), sesion.get(Localidad, datos.en_id)
    if origen is None or destino is None:
        raise HTTPException(404, "no existe alguna de las dos localidades")
    movidas = 0
    for columna in (OrdenCarga.origen_id, OrdenCarga.destino_id):
        movidas += sesion.execute(update(OrdenCarga).where(columna == id_)
                                  .values({columna.key: datos.en_id})).rowcount
    antes = auditoria.instantanea(origen)
    origen.activa = False
    destino.activa = True
    auditoria.registrar(sesion, actual, "localidades", origen.id, AccionAuditoria.BAJA, antes=antes,
                        despues={**auditoria.instantanea(origen), "unificada_en": destino.id,
                                 "ordenes_movidas": movidas})
    sesion.commit()
    return _a_salida(destino, LocalidadOut, "activa")
