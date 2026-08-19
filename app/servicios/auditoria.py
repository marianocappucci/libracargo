"""Quién hizo qué, y **qué cambió**.

La tabla `sucesos` del legado registraba que algo había pasado —fecha, hora,
usuario, tipo y un id— pero nunca qué cambió. Con eso, un error de carga no se
puede reconstruir: se sabe que alguien modificó la orden 3.412 el martes, y nada
más.

Acá cada registro lleva `datos_antes` y `datos_despues` en `JSONB`, así que la
pregunta "¿quién le cambió la tarifa a esta orden, y de cuánto a cuánto?" tiene
respuesta.

> 🔑 **El asiento de auditoría va en la MISMA transacción que el cambio.** No se
> commitea aparte: si el cambio entra y la auditoría no, el log miente, y un log
> que miente es peor que no tenerlo. Si la auditoría falla, falla la operación.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models.auditoria import RegistroAuditoria
from app.models.enums import AccionAuditoria

#: Columnas que no aportan nada al diff y lo ensucian: las pone la base, no la
#: persona. `updated_at` cambia en **todas** las modificaciones, así que si
#: entrara, todo diff tendría al menos una diferencia y ninguno sería vacío.
IGNORADAS = frozenset({"created_at", "updated_at", "created_by", "updated_by"})


def _plano(valor: Any) -> Any:
    """A algo que `JSONB` pueda guardar, sin perder precisión.

    Los `Decimal` van como **texto**: pasarlos por `float` para que entren en
    JSON es exactamente el defecto que el producto vino a reparar, y en un log
    de auditoría el importe es el dato.
    """
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, Enum):
        return valor.value
    return valor


def instantanea(objeto: Any) -> dict[str, Any]:
    """El estado de una fila, listo para guardar.

    Acepta un modelo o **un diccionario ya tomado**: los routers sacan la foto
    del "antes" antes de mutar el objeto —después de mutarlo ya no existe— y se
    la pasan a `registrar`, que la vuelve a pasar por acá. Sin este paso, la
    segunda vuelta le buscaba `__table__` a un `dict`.
    """
    if objeto is None:
        return {}
    if isinstance(objeto, dict):
        return objeto
    return {
        c.key: _plano(getattr(objeto, c.key))
        for c in objeto.__table__.columns
        if c.key not in IGNORADAS
    }


def _cambios(antes: dict, despues: dict) -> tuple[dict, dict]:
    """Sólo lo que cambió, de los dos lados.

    Guardar la fila entera dos veces por cada modificación de una columna hace
    que leer el log sea buscar la aguja: sobre `ordenes_carga` son 23 columnas
    para ver que alguien corrigió el remito.
    """
    distintas = {k for k in set(antes) | set(despues) if antes.get(k) != despues.get(k)}
    return ({k: antes[k] for k in distintas if k in antes},
            {k: despues[k] for k in distintas if k in despues})


def registrar(sesion: Session, usuario: dict | None, entidad: str, entidad_id: int | None,
              accion: AccionAuditoria, antes: Any = None, despues: Any = None) -> None:
    """Deja el asiento. **No commitea**: lo hace quien está haciendo el cambio."""
    antes_plano = instantanea(antes) if antes is not None else None
    despues_plano = instantanea(despues) if despues is not None else None

    if antes_plano is not None and despues_plano is not None:
        antes_plano, despues_plano = _cambios(antes_plano, despues_plano)
        if not antes_plano and not despues_plano:
            # Un PUT que no cambió nada no es un evento: anotarlo llena el log de
            # ruido y esconde las modificaciones de verdad.
            return

    usuario_id = None
    if usuario and str(usuario.get("id", "")).isdigit():
        usuario_id = int(usuario["id"])

    sesion.add(RegistroAuditoria(
        usuario_id=usuario_id,
        usuario_nombre=(usuario or {}).get("username"),
        entidad=entidad, entidad_id=entidad_id, accion=accion,
        datos_antes=antes_plano, datos_despues=despues_plano,
    ))
