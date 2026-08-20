#!/usr/bin/env python3
"""Panel de administración de LibraCargo.

    python3 scripts/panel_admin.py            → menú interactivo
    python3 scripts/panel_admin.py listar
    python3 scripts/panel_admin.py backup micliente

Envoltorio de configuración sobre `libracore.provisioning.panel_admin`. Es
además lo que consume el backoffice compartido (`libra-backoffice`) a través de
`libracore.admin.services`: sin este archivo, LibraCargo se podría listar pero
no operar.
"""
from pathlib import Path

from libracore.provisioning import (
    client_from_config,
    configure,
    forward_host_from_config,
    le_email_from_config,
    npm_available,
)
from libracore.provisioning.panel_admin import (
    _set_servicio_estado,
    cli,
    cmd_activar,
    cmd_actualizar,
    cmd_backup,
    cmd_backup_all,
    cmd_eliminar,
    cmd_estado_servicio,
    cmd_info,
    cmd_list_backups,
    cmd_listar,
    cmd_logs,
    cmd_npm_crear,
    cmd_npm_eliminar,
    cmd_npm_listar,
    cmd_pausar,
    cmd_restart,
    cmd_restore_db,
    cmd_start,
    cmd_stop,
    cmd_suspender,
    compose,
    container_status,
    find_client,
    interactive,
    load_clients,
    pick_client,
)

REPO_ROOT = Path(__file__).parent.parent.resolve()

#: Re-exportados: es la interfaz que consume el backoffice compartido a través
#: de `libracore.admin.services`. Van en `__all__` para que quede escrito que la
#: razón de importarlos es exponerlos, y para que el linter no los borre por
#: "no usados".
__all__ = [
    "cli", "cmd_activar", "cmd_actualizar", "cmd_backup", "cmd_backup_all",
    "cmd_eliminar", "cmd_estado_servicio", "cmd_info", "cmd_list_backups",
    "cmd_listar", "cmd_logs", "cmd_npm_crear", "cmd_npm_eliminar",
    "cmd_npm_listar", "cmd_pausar", "cmd_restart", "cmd_restore_db",
    "cmd_start", "cmd_stop", "cmd_suspender", "compose", "container_status",
    "find_client", "interactive", "load_clients", "pick_client",
    "_set_servicio_estado",
    "client_from_config", "configure", "forward_host_from_config",
    "le_email_from_config", "npm_available",
    "CLIENTES_DIR", "REPO_ROOT", "_NPM_AVAILABLE",
]

# 🔑 **Este bloque tiene que decir lo MISMO que el del otro script.**
# `configure()` pisa un `_cfg` GLOBAL y `libracore.admin.services` importa los
# dos módulos en el mismo proceso, así que gana el último import. Si uno se
# desviara del otro, un alta hecha después de un listado saldría con la
# configuración del que ganó. `tests/test_provisioning.py` lo verifica
# comparando los dos, no leyendo uno.
configure(
    product_name="LIBRACARGO",
    image_name="libracargo:latest",
    container_prefix="libracargo",
    # Vestigio del tiempo de SQLite: con `postgres=True` no se crea ningún
    # archivo. Sigue siendo obligatorio y el backoffice lo muestra, así que se
    # deja el nombre que le correspondería.
    db_filename="libracargo.db",
    repo_root=REPO_ROOT,
    # Este producto nace sobre PostgreSQL: no hay instancias SQLite que migrar.
    postgres=True,
    # La misma imagen que el CI, la de dev y la del cliente. El collation viene
    # de la imagen y `-alpine` ordena por bytes: una instancia nueva que ordenara
    # distinto que dev sería un cambio de comportamiento invisible.
    postgres_image="postgres:16",
    # El backup del cron arma el MISMO ZIP que la pantalla de Configuración →
    # Datos / Backup, en vez de un `tar.gz` aparte que la pantalla no lista y el
    # cliente no puede restaurar. Este producto puede prenderlo porque su
    # pantalla sale de `libracore.respaldo` (ver `build_backup_router` en
    # `app/main.py`).
    backup_zip=True,
    # `health_path` **no se pasa**: desde hoy este producto sirve `/health`
    # además de `/salud`, que es el default del motor y la ruta de los otros
    # seis. Ver el comentario en `app/routers/salud.py` — con la SPA horneada,
    # apuntar el chequeo a una ruta inexistente devuelve 200 igual.
    #
    # 8069-8098 ya están ocupados por el resto del ecosistema (verificado contra
    # el `docker ps` real del VPS el 2026-08-19).
    base_port=8099,
)

# Re-exportado por compatibilidad con cualquier uso directo de este módulo.
CLIENTES_DIR = REPO_ROOT / "clientes"

_NPM_AVAILABLE = npm_available()

if __name__ == "__main__":
    cli()
