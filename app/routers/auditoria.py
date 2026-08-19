"""El log: quién hizo qué, y qué cambió.

**Sólo lectura, y sólo para admin.** No hay endpoint que borre ni edite un
asiento: un log que se puede corregir no sirve para lo que existe. Tampoco hay
alta manual — los asientos los pone el sistema, en la misma transacción que el
cambio que registran.

Sobre la instancia de Suitrans esta pantalla arranca con **15.884 registros
migrados** de la tabla `sucesos` del legado: esos traen quién y cuándo, pero no
qué cambió, porque el sistema viejo nunca lo guardó. Los nuevos sí.
"""

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import obtener_sesion
from app.models.auditoria import RegistroAuditoria
from app.models.enums import AccionAuditoria

router = APIRouter(prefix="/api/auditoria", tags=["auditoria"],
                   dependencies=[Depends(require_admin)])


class RegistroOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    ts: datetime
    usuario_id: int | None
    usuario_nombre: str | None
    entidad: str
    entidad_id: int | None
    accion: AccionAuditoria
    datos_antes: dict[str, Any] | None
    datos_despues: dict[str, Any] | None


class PaginaDeLog(BaseModel):
    #: El total de la consulta **sin paginar**. Sin esto la pantalla no puede
    #: decir "1 a 50 de 15.884", y un listado que no dice cuánto hay se lee como
    #: si fuera todo.
    total: int
    registros: list[RegistroOut]


@router.get("", response_model=PaginaDeLog)
def listar(
    sesion: Session = Depends(obtener_sesion),
    entidad: str | None = None,
    entidad_id: int | None = None,
    usuario: str | None = Query(default=None, description="nombre de usuario exacto"),
    accion: AccionAuditoria | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = Query(default=50, ge=1, le=500),
    desplazamiento: int = Query(default=0, ge=0),
):
    consulta = select(RegistroAuditoria)
    for columna, valor in (
        (RegistroAuditoria.entidad, entidad),
        (RegistroAuditoria.entidad_id, entidad_id),
        (RegistroAuditoria.usuario_nombre, usuario),
        (RegistroAuditoria.accion, accion),
    ):
        if valor is not None:
            consulta = consulta.where(columna == valor)
    if desde is not None:
        consulta = consulta.where(RegistroAuditoria.ts >= desde)
    if hasta is not None:
        # `hasta` es un día, y `ts` un instante: sin sumarle el día, "hasta el
        # 18" dejaría afuera todo lo que pasó el 18 después de la medianoche.
        consulta = consulta.where(
            func.date(func.timezone("America/Argentina/Buenos_Aires", RegistroAuditoria.ts))
            <= hasta)

    # 🔴 `count(RegistroAuditoria.id)` y no `count()`: sin columna, una consulta
    # sin `WHERE` pierde el `FROM` y devuelve 1 en vez de fallar. Ya pasó en los
    # reportes (PR #19).
    total = sesion.scalar(
        consulta.with_only_columns(func.count(RegistroAuditoria.id)).order_by(None))

    registros = list(sesion.scalars(
        consulta.order_by(RegistroAuditoria.ts.desc(), RegistroAuditoria.id.desc())
        .limit(limite).offset(desplazamiento)))
    return PaginaDeLog(total=total or 0, registros=registros)


@router.get("/entidades", response_model=list[str])
def entidades(sesion: Session = Depends(obtener_sesion)):
    """Las entidades que efectivamente aparecen en el log.

    Se leen de los datos y no de una lista fija: sobre una base migrada las que
    hay son las del legado, y una lista escrita a mano ofrecería filtros que no
    devuelven nada.
    """
    return list(sesion.scalars(
        select(RegistroAuditoria.entidad).distinct().order_by(RegistroAuditoria.entidad)))


@router.get("/usuarios", response_model=list[str])
def usuarios(sesion: Session = Depends(obtener_sesion)):
    """Los usuarios que aparecen en el log, incluidos los que ya no existen.

    Un usuario dado de baja **sigue** en el log: lo que hizo, lo hizo.
    """
    return list(sesion.scalars(
        select(RegistroAuditoria.usuario_nombre).distinct()
        .where(RegistroAuditoria.usuario_nombre.is_not(None))
        .order_by(RegistroAuditoria.usuario_nombre)))
