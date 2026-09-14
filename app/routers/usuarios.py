"""ABM de usuarios, sobre el router único de [[libraauth]] (ADR-018, v0.43.0).

Antes este módulo tenía su propia copia del router (alta, edición, baja,
protecciones de "no te podés borrar/desactivar a vos mismo"). Ahora es un
`build_users_router()` con el prefijo, la tupla de roles y el guard que este
producto ya usaba -- ver el docstring de la factory en `libraauth.usuarios`
para el detalle de cada protección.

> El repositorio es el de `libraauth`: la tabla `usuarios` la crea y la versiona
> el motor, no este producto. Acá sólo se expone.
"""

from libraauth.usuarios import build_users_router

from app.auth import require_admin_o_servicio

router = build_users_router(
    # El prefijo NO cambia: va en castellano como el resto de la API de este
    # producto, y `libra-ui`, el backoffice y los bookmarks del cliente ya lo
    # conocen.
    prefix="/api/usuarios",
    roles=("admin", "staff"),
    # Rol admin **o** token de servicio: el backoffice de la suite administra
    # los usuarios de una instancia por acá, y no tiene (ni debería tener) una
    # sesión de usuario en cada una. El mismo guard que ya gateaba el router
    # entero -- acá no había un envoltorio propio de auditoría (a diferencia de
    # LibraClub): las escrituras de este router no pasan por
    # `app/servicios/auditoria.py`.
    #
    # Sin `LIBRA_SERVICE_TOKEN` en el entorno se comporta exactamente igual
    # que `require_admin`, así que ponerlo en una instancia que no define la
    # variable no abre nada.
    admin_guard=require_admin_o_servicio,
)
