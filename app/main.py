"""Construcción de la aplicación.

`crear_app()` no se ejecuta al importar: el entrypoint es `app/asgi.py`. Es a
propósito — con la app armada al importar, la configuración queda resuelta por
el primer import y un test que quiera otra base ya llega tarde.
"""

from __future__ import annotations

from fastapi import FastAPI
from libraauth.bootstrap import ensure_default_admin
from libraauth.models import Base as AuthBase

from app import db
from app.auth import UserRepository, construir_session_auth
from app.config import Config
from app.routers import auth as auth_router
from app.routers import comprobantes, cuentas, maestros, ordenes, reportes, salud

# Con alias: mas abajo hay una variable local llamada usuarios con el
# repositorio, y sin el alias el import queda pisado.
from app.routers import usuarios as usuarios_router


def crear_app(config: Config | None = None, *, sembrar_admin: bool = True) -> FastAPI:
    db.inicializar(config)
    motor = db.engine()

    # Las tablas del motor de auth las crea el motor, con el mismo engine que
    # el dominio: `usuarios` vive en la MISMA base, así que las FK de sus
    # tablas satélite resuelven. Las tablas propias van por Alembic; las de
    # `libraauth` no, porque su schema lo versiona él y no nosotros. Es el
    # mismo reparto que hace LibraDesk.
    AuthBase.metadata.create_all(motor)

    usuarios = UserRepository(db.fabrica_de_sesiones())
    if sembrar_admin:
        # Variante **fail-closed**: sin `LIBRACARGO_ADMIN_PASSWORD` la app no
        # levanta, salvo `ENV=development`. Es la que usan los productos
        # FastAPI de la familia; la otra (`ensure_admin_user`) inventa una
        # contraseña y la imprime, y no son intercambiables.
        ensure_default_admin(usuarios, env_prefix="LIBRACARGO")

    app = FastAPI(
        title="LibraCargo",
        description="Gestión de agencia de cargas — familia Libra",
        version="0.1.0",
    )
    # El router de `libraauth` los lee de acá por nombre: sin estos dos, el
    # login devuelve 500 al primer request y no al arrancar.
    app.state.users = usuarios
    app.state.session_auth = construir_session_auth(usuarios)

    app.include_router(salud.router)
    app.include_router(auth_router.router)
    for router in maestros.TODOS:
        app.include_router(router)
    app.include_router(ordenes.router)
    app.include_router(cuentas.router)
    app.include_router(comprobantes.router)
    app.include_router(usuarios_router.router)
    app.include_router(reportes.router)
    return app
