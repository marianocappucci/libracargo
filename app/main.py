"""Construcción de la aplicación.

`crear_app()` no se ejecuta al importar: el entrypoint es `app/asgi.py`. Es a
propósito — con la app armada al importar, la configuración queda resuelta por
el primer import y un test que quiera otra base ya llega tarde.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from libraauth.auth_events import AuthEventRepository
from libraauth.bootstrap import ensure_default_admin, ensure_demo_user
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.models import Base as AuthBase
from libraauth.password_reset import PasswordResetService
from libraauth.session_auth import (
    build_demo_codigos_router,
    build_smtp_settings_router,
    demo_username,
)
from libraauth.smtp_settings import SmtpSettingsRepository, resolver_smtp_config
from libraauth.terminos import TerminosRepository, build_terminos_router
from libracore import config_manager
from libracore.arca_router import build_arca_router
from libracore.config_router import build_backup_router
from libracore.db import core as libracore_core
from libracore.geografia import build_geo_router
from libracore.respaldo import Instancia
from libracore.smtp_router import build_smtp_probe_router

from app import db
from app.auth import (
    UserRepository,
    construir_session_auth,
    get_current_user,
    require_admin,
    require_staff,
)
from app.config import Config
from app.routers import (
    auditoria,
    comprobantes,
    configuracion,
    cuentas,
    gastos,
    maestros,
    ordenes,
    reportes,
    salud,
)
from app.routers import auth as auth_router

# Con alias: mas abajo hay una variable local llamada usuarios con el
# repositorio, y sin el alias el import queda pisado.
from app.routers import usuarios as usuarios_router
from app.servicios import auditoria_arca
from app.servicios.emision_arca import EMPRESA_ARCA


def _instancia_a_respaldar(config: Config) -> Instancia:
    """Qué se lleva el backup de esta instancia: las DOS bases y los certificados.

    Hasta el 2026-09-02 acá decía que LibraCargo era el caso más simple de la
    familia —una sola base y ningún archivo en disco— y que `directorios=[]` no
    era un pendiente. Las dos mitades dejaron de ser ciertas el día que la
    configuración de ARCA pasó al motor:

    - **Son dos bases.** El schema de LibraCore no puede convivir con el del
      dominio: los dos declaran `usuarios` y `auth_log`. Ver `Config`.
    - **Y hay archivos en disco.** El certificado y la clave los escribe
      `arca_router` en `CERTS_DIR`, no en una columna.

    🔴 **Un backup que traiga una sola mitad no se puede restaurar**, y el modo
    de fallar es el peor: restaurar deja una instancia que **no puede facturar y
    no lo dice**. Es exactamente la propiedad que la tabla propia protegía
    guardando el par adentro del dump, y la que se paga de vuelta acá.

    `CERTS_DIR` sale de `config_manager` y no se arma con
    `config.directorio_de_datos`: tiene que ser **el mismo valor** que el que
    escribe el upload, o el backup respalda una carpeta vacía al lado de la que
    tiene las credenciales.
    """
    return Instancia(
        # La principal es la del DOMINIO, no la del core: `dumps` nombra a la
        # principal por `nombre` y a las extra por su base, así que invertirlas
        # haría que las dos cayeran en `libracargo.dump` dentro del ZIP y la
        # verificación pasaría igual, sobre un backup con una sola mitad.
        nombre="libracargo",
        postgres_url=config.database_url,
        postgres_extra=[config.database_url_core],
        directorios=[config_manager.CERTS_DIR],
    )


def crear_app(config: Config | None = None, *, sembrar_admin: bool = True) -> FastAPI:
    # Se resuelve acá y no adentro de `db.inicializar` porque el router de
    # backup necesita la MISMA config: la URL para el dump y el directorio de
    # datos para los ZIP.
    config = config or Config.desde_entorno()
    db.inicializar(config)
    motor = db.engine()

    # LibraCore habla con SU base, que no es la del dominio. Es una conexión
    # aparte —`libracore.db` es SQL crudo, sin el engine de SQLAlchemy— igual
    # que en Gestiolibra y MedLibra.
    #
    # 🔴 **Acá NO se llama a `init_core_schema()`**, a diferencia de esos dos.
    # El schema lo crea `libracore-migrar upgrade`, declarado en el deploy y
    # atado por `tests/test_provisioning.py`. Si la app se lo creara sola, un
    # deploy que se olvide de ese paso quedaría invisible — que es exactamente
    # el defecto que este producto pagó el 2026-08-24 con su propia cadena.
    libracore_core.configure(config.database_url_core)

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

    # El visitante de la demo pública, **sólo si esta instancia es una demo**:
    # se guía por `DEMO_MODE` + `DEMO_USERNAME`, las mismas dos variables que
    # registran `POST /auth/demo`. En `suitrans` y en cualquier instancia de
    # cliente devuelve None y no toca la base.
    #
    # 🔴 Sin esta llamada la ruta existe y no tiene a quién loguear: contesta
    # `503 demo user not provisioned`. Cablear `incluir_demo=True` en el router
    # no alcanza — la ruta y la siembra las conecta el producto, cada una por
    # su lado, y ninguna de las dos delata que falta la otra.
    ensure_demo_user(usuarios)

    app = FastAPI(
        title="LibraCargo",
        description="Gestión de agencia de cargas — familia Libra",
        version="0.1.0",
    )
    # El router de `libraauth` los lee de acá por nombre: sin estos dos, el
    # login devuelve 500 al primer request y no al arrancar.
    app.state.users = usuarios
    app.state.session_auth = construir_session_auth(usuarios)

    # 🔴 **Sin esta línea se apagan DOS cosas, y ninguna avisa.** El registro de
    # accesos —quién entró, quién salió, quién lo intentó sin lograrlo— y el
    # **rate limiting del login**: `contar_fallidos_seguro` devuelve 0 cuando no
    # hay repositorio, y 0 significa "nadie agotó intentos", así que el bloqueo
    # por fuerza bruta nunca dispara. Es opt-in por ausencia, a propósito, para
    # que actualizar el motor no obligue a nadie a crear una tabla — pero este
    # producto nunca lo cableó.
    #
    # Se midió el 2026-08-22: `auth_log` existía y tenía **cero filas en las
    # tres instancias**, incluida la de Suitrans en producción. O sea que no
    # había ningún registro de quién entraba, y el login no tenía freno.
    #
    # Mismo `db.fabrica_de_sesiones()` que el resto: en LibraCargo `usuarios`
    # vive en la MISMA base que el dominio. En Gestiolibra/MedLibra/VentaLibra
    # no es así — ver la nota de `demo_codigos` unas líneas más abajo.
    app.state.auth_events = AuthEventRepository(db.fabrica_de_sesiones())

    app.include_router(salud.router)
    # `construir_router()` y no un `router` de módulo: lee `DEMO_MODE` al
    # construirse, y a nivel de módulo quedaría congelado en el primer import.
    # Ver el docstring de `app/routers/auth.py`.
    app.include_router(auth_router.construir_router())

    # Los códigos de acceso de la demo pública. Se emiten desde el backoffice
    # (`admin.libracargo.com.ar`) y los consume `POST /auth/demo`.
    #
    # 🔴 `POST /auth/demo` **falla cerrado** si esta línea no corrió: contesta
    # `503 demo access codes not configured` en vez de dejar entrar sin código.
    # Es incómodo a propósito — la alternativa convertiría un olvido de
    # cableado en una demo abierta a internet, que es exactamente lo que el
    # código de acceso existe para cerrar. Si un día la demo devuelve ese 503,
    # lo que falta es esto.
    #
    # El factory es el mismo `db.fabrica_de_sesiones()` del `UserRepository`
    # porque en LibraCargo `usuarios` vive en la MISMA base que el dominio. En
    # Gestiolibra/MedLibra/VentaLibra no es así y ahí va el factory del engine
    # de auth; copiar de allá sin mirar crearía la tabla en el lugar
    # equivocado y ningún código sería válido.
    if demo_username():
        app.state.demo_codigos = DemoCodigoRepository(db.fabrica_de_sesiones())
        app.include_router(build_demo_codigos_router())

    # Recuperación de contraseña. Mismo `db.fabrica_de_sesiones()` que el
    # `UserRepository` por el mismo motivo que la demo: en LibraCargo `usuarios`
    # vive en la MISMA base que el dominio, y la tabla de tokens tiene FK a
    # `usuarios`. Con el factory del engine de auth de otro producto, la tabla
    # se crearía en el lugar equivocado.
    app.state.smtp_settings = SmtpSettingsRepository(db.fabrica_de_sesiones())
    # Terminos y Condiciones del Servicio: la prueba de la aceptacion y lo que
    # enciende el gate. MISMA fabrica de sesiones que el SMTP y los usuarios --
    # la tabla tiene FK a `usuarios`, que no siempre vive en la base del dominio.
    #
    # 🔴 Sin esta linea el gate NO corta y la instancia no falla: se queda sin
    # gate, en silencio. Por eso cada producto tiene un test que lo prueba.
    app.state.terminos = TerminosRepository(db.fabrica_de_sesiones())
    app.include_router(build_smtp_settings_router())
    # `POST /admin/smtp/probar`: abre la conexion, negocia TLS y hace login.
    #
    # 🔑 Resuelve por el MISMO camino que los envios (`smtp_efectivo` sobre el
    # resolver de abajo), que es lo que hace que el boton signifique algo: un
    # endpoint que probara otra config diria "Conectado" contra un servidor
    # mientras los mails salen por otro. El gate lo pone el producto porque el
    # router del motor no trae ninguno, y esto abre una sesion SMTP con las
    # credenciales del cliente.
    app.include_router(
        build_smtp_probe_router(
            lambda: resolver_smtp_config(db.fabrica_de_sesiones())),
        dependencies=[Depends(require_admin)],
    )
    # `GET /terminos`, `POST /terminos/aceptar`, `GET /terminos/historial`.
    # NO se gatea desde afuera: es el unico camino para salir del gate.
    app.include_router(build_terminos_router())
    app.state.password_reset = PasswordResetService(
        db.fabrica_de_sesiones(),
        product_name="LibraCargo",
        reset_url_base=os.environ.get(
            "LIBRACARGO_RESET_URL_BASE", "https://dev.libracargo.com.ar/reset-password"
        ),
        # CALLABLE, no un valor: se resuelve en cada envío. Con un valor fijo,
        # guardar el SMTP por pantalla no tendría efecto hasta recrear el
        # contenedor.
        smtp_config=lambda: resolver_smtp_config(db.fabrica_de_sesiones()),
    )

    for router in maestros.TODOS:
        app.include_router(router)
    app.include_router(ordenes.router)
    app.include_router(cuentas.router)
    # Gastos de proveedor: el bloque que el legado llamaba COMPROBANTES
    # PROVEEDORES. Deja dos asientos -proveedor al debe, fletero al haber-
    # en una sola transacción.
    app.include_router(gastos.router)
    app.include_router(comprobantes.router)
    app.include_router(usuarios_router.router)
    app.include_router(reportes.router)
    app.include_router(auditoria.router)
    app.include_router(configuracion.router)
    # Configuración de ARCA: la pantalla compartida de la familia, con la
    # dependencia de rol de este producto —el router del motor no trae
    # ninguna, y acá se sube una clave privada—.
    #
    # El prefijo se mantiene en `/api/arca`, que es el que este producto ya
    # publicó: `build_arca_router` lo toma por parámetro justamente porque
    # cambiarlo rompe el frontend desplegado.
    #
    # 🔑 `empresa_por_defecto` sale de `EMPRESA_ARCA` y no de un literal. No
    # es que la emisión lo lea —resuelve la fila activa, justamente para que
    # un slug de más no pueda dejarla ciega—: es que un segundo literal haría
    # que la pantalla y el alta creen **dos filas distintas**, y ahí sí no hay
    # con qué elegir. Ver `EMPRESA_ARCA`.
    #
    # 🔴 **`al_cambiar` es lo que devuelve el registro que este producto
    # tenía y perdió al normalizar.** El router propio anotaba cada alta,
    # upload y borrado del par; el compartido no anotaba nada hasta LibraCore
    # `v1.74.0`. Sin esta línea la pantalla funciona igual y la tabla de
    # auditoría queda muda justo sobre la clave privada del cliente.
    app.include_router(
        build_arca_router(
            prefix="/api/arca",
            empresa_por_defecto=EMPRESA_ARCA,
            usuario_actual=get_current_user,
            al_cambiar=auditoria_arca.construir_hook(db.fabrica_de_sesiones()),
        ),
        dependencies=[Depends(require_admin)],
    )

    # El catálogo de provincias y localidades: 24 y 4.027, de LibraCore. Es de
    # sólo lectura y no toca la base — el maestro editable de localidades, que
    # es el que se usa como origen y destino, sigue siendo el de este producto.
    # El gate lo pone el producto, igual que con el router de backup.
    app.include_router(build_geo_router(), dependencies=[Depends(require_staff)])

    # "Datos / Backup": el motor de la familia, con la dependencia de rol de
    # este producto. El prefijo es `/api/config` —y no `/api/configuracion`,
    # como el router propio de al lado— porque es el que consume la pantalla
    # compartida de `libra-ui`. Renombrarlo obligaría a forkear esa pantalla
    # para cambiarle cuatro strings.
    #
    # 🔴 `cerrar_conexiones`/`reabrir_conexiones` no son opcionales: sin ellos
    # el restore contesta `ok` y no tiene efecto hasta que alguien reinicie el
    # contenedor, porque el pool sigue con la conexión vieja. La pantalla diría
    # que salió bien y los datos serían los de antes.
    app.include_router(
        build_backup_router(
            _instancia_a_respaldar(config),
            os.path.join(config.directorio_de_datos, "backups"),
            cerrar_conexiones=motor.dispose,
            reabrir_conexiones=motor.dispose,
        ),
        dependencies=[Depends(require_admin)],
    )
    return app
