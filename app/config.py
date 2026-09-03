"""Configuración por entorno. Ningún secreto vive en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass

from libracore.db.url_de_instancia import url_de_instancia


def _exigir_postgres(url: str, que: str, variable: str) -> str:
    """Aborta si la URL no es de PostgreSQL, nombrando cuál de las dos es."""
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        esquema = url.split(":", 1)[0]
        raise RuntimeError(
            f"{variable} debe apuntar a PostgreSQL, no a {esquema!r}. "
            f"PostgreSQL es el único motor de la familia Libra ({que})."
        )
    return url


@dataclass(frozen=True)
class Config:
    database_url: str
    entorno: str
    debug: bool
    #: La base de **LibraCore**, que no es la del dominio.
    #:
    #: 🔴 **Son dos bases y no dos schemas de la misma.** El schema del core
    #: declara `usuarios` y `auth_log`, y las dos ya existen en la base del
    #: dominio con la forma de `libraauth`. `init_core_schema` las crea con
    #: `CREATE TABLE IF NOT EXISTS`, así que no fallaría: las dejaría pasar y
    #: el motor terminaría leyendo la tabla del otro. Es la misma razón por la
    #: que Gestiolibra, MedLibra y LibraClub llevan el core aparte — allá el
    #: choque era `clients`.
    #:
    #: El nombre de la variable lo define `libracore.db.url_de_instancia` y no
    #: este archivo: es el único lugar de la familia que sabe cómo se llaman, y
    #: por eso no pueden volver a divergir.
    database_url_core: str
    #: Dónde escribe la app lo que tiene que sobrevivir a un redeploy: los ZIP
    #: de backup y, desde que ARCA se guarda con el motor, el certificado y la
    #: clave. **Tiene que ser un volumen**, no una carpeta del árbol de código
    #: — en `dev` ese árbol es un bind mount del checkout del servidor, y un
    #: `git pull` con archivos nuevos adentro es un problema.
    directorio_de_datos: str = "./data"

    @classmethod
    def desde_entorno(cls) -> Config:
        # 🔴 **Los DOS nombres, y por eso no alcanza con leer `DATABASE_URL`.**
        # `libracore.provisioning.nuevo_cliente` escribe en el compose los
        # nombres que dice `nombres_aceptados("libracargo")`, o sea **sólo**
        # `LIBRACARGO_DATABASE_URL`. Leyendo la genérica a secas, una instancia
        # recién creada moría al arrancar con "Falta DATABASE_URL" — y eso no se
        # veía en ninguna de las tres instancias vivas, porque todas tienen el
        # compose de cuando se crearon, con la genérica.
        #
        # ⚠️ **La genérica NO se puede meter en `_HISTORICOS` del motor**, que
        # sería el lugar natural. Ahí la toma también `migrar.url_de_core`, que
        # cae a la base del DOMINIO cuando no encuentra la del core: con
        # `DATABASE_URL` aceptada, un `libracore-migrar --prefijo libracargo` sin
        # la variable del core migraría el schema del motor **adentro de la base
        # del dominio** y devolvería éxito. Es exactamente la colisión de
        # `usuarios` y `auth_log` que la separación de bases evita. Hay un test
        # del motor que lo fija, y fue el que frenó ese intento.
        url = (url_de_instancia("libracargo")
               or (os.environ.get("DATABASE_URL") or "").strip())
        if not url:
            raise RuntimeError(
                "Falta la URL de la base: definí LIBRACARGO_DATABASE_URL "
                "(el nombre vigente) o DATABASE_URL. LibraCargo corre sobre "
                "PostgreSQL; no hay default a SQLite a propósito."
            )
        _exigir_postgres(url, "la base del dominio", "LIBRACARGO_DATABASE_URL")
        # 🔴 **Fail-closed, y no un default a la base del dominio.** Caer ahí
        # sería exactamente el choque que esta segunda base existe para evitar,
        # y el modo de fallar es mudo: la app levanta, la pantalla de ARCA
        # contesta, y el motor escribe al lado de las tablas de `libraauth`.
        # `requerida=True` hace que el arranque muera nombrando la variable.
        core = url_de_instancia("libracargo", core=True, requerida=True)
        _exigir_postgres(core, "la base de LibraCore",
                         "LIBRACARGO_LIBRACORE_DATABASE_URL")
        return cls(
            database_url=url,
            database_url_core=core,
            entorno=os.environ.get("ENTORNO", "dev"),
            debug=os.environ.get("DEBUG", "").lower() in {"1", "true", "si"},
            directorio_de_datos=os.environ.get("DATA_DIR", "./data"),
        )
