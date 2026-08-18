"""Session auth de LibraCargo — shim sobre `libraauth`, mismo patrón que
`libradesk/app/auth.py`.

Existe para que el resto del producto importe de un solo lugar: si mañana
cambia la forma de pedir un rol, se toca acá y no en cada router.
"""

from __future__ import annotations

from libraauth.repository import UserRepository
from libraauth.session_auth import (
    SessionAuth,
)
from libraauth.session_auth import (
    json_api_get_current_user as get_current_user,
)
from libraauth.session_auth import (
    json_api_get_session_auth as get_session_auth,
)
from libraauth.session_auth import (
    json_api_require_admin as require_admin,
)
from libraauth.session_auth import (
    json_api_require_role as require_role,
)
from libraauth.session_auth import (
    json_api_require_staff as require_staff,
)

__all__ = [
    "SessionAuth", "UserRepository", "construir_session_auth",
    "get_current_user", "get_session_auth",
    "require_admin", "require_role", "require_staff",
]

#: Nombre de la cookie. Propio por producto: dos instancias de productos
#: distintos bajo el mismo dominio padre se pisarían la sesión si compartieran
#: nombre.
COOKIE = "lc_session"


def construir_session_auth(usuarios: UserRepository) -> SessionAuth:
    return SessionAuth(
        dev_secret_fallback="libracargo-dev-secret-not-for-prod",
        get_user_by_username=usuarios.get_by_username,
        check_credentials=usuarios.check_credentials,
        cookie_name=COOKIE,
    )
