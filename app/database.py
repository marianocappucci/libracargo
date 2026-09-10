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

**No confundir con `app.db`**, que es el engine de SQLAlchemy de la base del
DOMINIO. Esto habla con la base de **LibraCore**, que es otra: la tabla
`modulos` vive en la del core y no en la del dominio. Medido en
`libracargo-demo` el 2026-09-10: la del dominio no la tiene, la del core sí.

Acá no se copia lógica: se delega en `libracore.db.modulos`, que es la
implementación única de la familia.
"""

from __future__ import annotations

from libracore.db import core as libracore_core
from libracore.db import modulos as _modulos
from libracore.db.url_de_instancia import url_de_instancia


def _asegurar_core_configurado() -> None:
    """Apunta `libracore.db.core` a la base de core de ESTA instancia si nadie lo hizo.

    Estas funciones tienen dos vidas muy distintas:

    - Adentro de la app, `crear_app()` ya configuró el core
      (`libracore_core.configure(config.database_url_core)`) y acá no hay nada
      que hacer.
    - Bajo el `docker exec` del backoffice no corrió ningún arranque, así que el
      core está sin configurar y `get_connection()` levanta `RuntimeError`. Ese
      es el caso que se tiene que resolver solo, sin bootear la app entera.

    Se pregunta antes (`esta_configurado()`) para no pisarle la configuración a
    una app viva.

    🔴 **`core=True` no es opcional.** Sin él, `url_de_instancia` busca
    `LIBRACARGO_DATABASE_URL`, que el contenedor no define —usa `DATABASE_URL`—
    y con `requerida=True` muere. Y aunque la encontrara, sería la base del
    DOMINIO, que no tiene `modulos`. Es la misma URL que arma
    `Config.desde_entorno` para el core.
    """
    if not libracore_core.esta_configurado():
        libracore_core.configure(url_de_instancia("libracargo", core=True, requerida=True))


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
