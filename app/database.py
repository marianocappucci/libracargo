"""Módulos y add-ons de la instancia: el contrato que espera el backoffice.

🔴 **Este módulo existe por un contrato externo, no por el producto.** El
backoffice (`libracore.admin.services`) prende, apaga y lee los add-ons corriendo
un snippet ADENTRO de este contenedor:

    docker exec <contenedor> python3 -c "... from app.database import set_addon; ..."

así que `app.database` tiene que exportar `get_modulos` y `set_addon` con esos
nombres. LibraCargo lo necesita desde que declaró su primer add-on
(`plans.ADDONS`). Es el mismo contrato que cumple LibraDesk, que al principio no
lo cumplía: el `docker exec` moría con `ImportError` y el backoffice mostraba
destildado un add-on que estaba prendido en la base.

**No confundir con `app.db`**, que es el engine de SQLAlchemy del dominio. Esto
habla con el schema de **LibraCore** por la conexión SQL cruda de
`libracore.db.core`. Desde la `0015` (ADR-029) es la misma base que la del
dominio; hasta entonces eran dos, y la tabla `modulos` sólo existía en la del
core (medido en `libracargo-demo` el 2026-09-10).

Acá no se copia lógica: se delega en `libracore.db.modulos`, que es la
implementación única de la familia.
"""

from __future__ import annotations

from libracore.db import core as libracore_core
from libracore.db import modulos as _modulos

from app.config import Config


def _asegurar_core_configurado() -> None:
    """Apunta `libracore.db.core` a la base de ESTA instancia si nadie lo hizo.

    Estas funciones tienen dos vidas muy distintas:

    - Adentro de la app, `crear_app()` ya configuró el core
      (`libracore_core.configure(config.database_url)`) y acá no hay nada que
      hacer.
    - Bajo el `docker exec` del backoffice no corrió ningún arranque, así que el
      core está sin configurar y `get_connection()` levanta `RuntimeError`. Ese
      es el caso que se tiene que resolver solo, sin bootear la app entera.

    Se pregunta antes (`esta_configurado()`) para no pisarle la configuración a
    una app viva.

    🔴 **La URL sale de `Config.desde_entorno()` y no de `url_de_instancia(...,
    core=True)`.** El core es la base del dominio (ADR-054): `desde_entorno` la
    resuelve con los dos nombres (`LIBRACARGO_DATABASE_URL` y `DATABASE_URL`), que
    es lo que define el contenedor, y rechaza una variable del core que apunte a
    otra base. Pedir la variable del core acá haría que un contenedor sin ella
    muriera justo bajo el `docker exec`, que es donde nadie mira el arranque.
    """
    if not libracore_core.esta_configurado():
        libracore_core.configure(Config.desde_entorno().database_url)


def get_modulos() -> dict[str, bool]:
    """`{modulo: habilitado}` de esta instancia. Ver `_asegurar_core_configurado`."""
    _asegurar_core_configurado()
    return _modulos.get_modulos()


def set_addon(nombre: str, habilitado: bool) -> None:
    """Prende o apaga un add-on en esta instancia.

    Efecto inmediato: `app.addons.require_addon` relee `get_modulos()` en cada
    request. No valida que `nombre` sea un add-on: eso lo hace quien llama,
    contra `plans.ADDONS`.
    """
    _asegurar_core_configurado()
    _modulos.set_addon(nombre, habilitado)
