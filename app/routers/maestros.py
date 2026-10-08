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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_staff
from app.db import obtener_sesion
from app.models.enums import AccionAuditoria
from app.models.maestros import Chofer, Localidad, Tercero, TipoCarga, Vehiculo
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
