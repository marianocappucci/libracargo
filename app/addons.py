"""El gate de los add-ons (`plans.ADDONS`).

Un add-on se prende por instancia desde el backoffice, que lo escribe en la
tabla `modulos` de la base de LibraCore por `app.database.set_addon`. Este gate
lo lee **por la misma vía** —`app.database.get_modulos`—, así que lo que el
backoffice muestra y lo que la API deja pasar no pueden divergir.

🔴 **Por qué no el `require_module` de LibraCore.** Ese lee
`request.app.state.modules`, que carga el arranque de los productos con gating
por plan. LibraCargo no tiene gating por módulo —el core no se gatea, ver
`plans.py`— y nunca carga `app.state.modules`. Montarlo acá no daría un 403
limpio: daría un error al primer request, o, si alguien le pusiera un
`state.modules` de compromiso, una foto del arranque que no se entera de un
toggle hecho después desde el backoffice.

🔑 **Falla cerrado.** Si no se puede leer el estado —core sin configurar, tabla
`modulos` que no existe, base caída— la respuesta es 403 y no 500. Un add-on
es algo que se cobra aparte: ante la duda, apagado. El motivo va al log, para
que "no se pudo leer" no se confunda en silencio con "está apagado".
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import HTTPException

from app import database

_log = logging.getLogger(__name__)


def require_addon(nombre: str) -> Callable[[], None]:
    """Dependencia que deja pasar sólo si el add-on `nombre` está prendido.

    Prendido quiere decir que hay una fila en `modulos` con `habilitado`
    verdadero. Sin fila, apagado: así viene cada instancia.
    """

    def _addon_habilitado() -> None:
        try:
            habilitado = bool(database.get_modulos().get(nombre, False))
        except Exception:
            _log.warning("No se pudo leer el add-on %r: se niega el acceso.", nombre, exc_info=True)
            habilitado = False
        if not habilitado:
            raise HTTPException(403, f"El add-on '{nombre}' no está habilitado en esta instancia.")

    return _addon_habilitado
