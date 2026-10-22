"""Configuración por entorno. Ningún secreto vive en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass

from libracore.db.url_de_instancia import url_de_instancia
from sqlalchemy.engine import make_url


def _exigir_postgres(url: str, que: str, variable: str) -> str:
    """Aborta si la URL no es de PostgreSQL, nombrando cuál de las dos es."""
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        esquema = url.split(":", 1)[0]
        raise RuntimeError(
            f"{variable} debe apuntar a PostgreSQL, no a {esquema!r}. "
            f"PostgreSQL es el único motor de la familia Libra ({que})."
        )
    return url


def _destino(url: str) -> tuple[str, int, str] | None:
    """`(host, puerto, base)` de una URL de PostgreSQL, o `None` si no se puede leer.

    Sin usuario, contraseña, driver ni parámetros: lo que identifica **la base**.
    """
    try:
        u = make_url(url)
    except Exception:  # noqa: BLE001 -- el mensaje de SQLAlchemy puede traer la URL entera, con su contraseña
        return None
    if not u.host or not u.database:
        return None
    return (u.host.lower(), u.port or 5432, u.database)


def misma_base(a: str, b: str) -> bool:
    """Si dos URLs apuntan a la misma base de datos.

    Compara servidor, puerto y nombre de la base; ignora el usuario, la
    contraseña, el driver (`postgresql://` o `postgresql+psycopg://`), los
    parámetros (`?sslmode=...`) y la barra final. No resuelve nombres de host:
    dos alias del mismo servidor cuentan como bases distintas, y entonces el
    arranque falla con un mensaje claro (el error barato; el caro sería seguir
    adelante escribiendo en una base que nadie sabe cuál es). Una URL ilegible
    nunca es «la misma».
    """
    da, db = _destino(a), _destino(b)
    return da is not None and da == db


def _nombre_de_base(url: str) -> str:
    """Sólo el nombre de la base, para los mensajes: la URL entera lleva la contraseña."""
    d = _destino(url)
    return repr(d[2]) if d else "una URL ilegible"


@dataclass(frozen=True)
class Config:
    #: La base de **LibraCargo y de LibraCore, que es una sola** (ADR-029 de este
    #: producto, `0015`, 2026-10-05; ADR-054 retira la variable del core). Las
    #: tablas del dominio, las de `libraauth` y el schema del motor viven en
    #: ella: `facturas.usuario_id` apunta a los `usuarios` reales y el
    #: comprobante, las órdenes y la cuenta corriente se escriben en UNA
    #: transacción (ADR-025 del motor). `libracore.db.core` se configura con esta
    #: misma URL (`crear_app`, `app.database`, los scripts).
    database_url: str
    entorno: str
    debug: bool
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
        url = (url_de_instancia("libracargo")
               or (os.environ.get("DATABASE_URL") or "").strip())
        if not url:
            raise RuntimeError(
                "Falta la URL de la base: definí LIBRACARGO_DATABASE_URL "
                "(el nombre vigente) o DATABASE_URL. LibraCargo corre sobre "
                "PostgreSQL; no hay default a SQLite a propósito."
            )
        _exigir_postgres(url, "la base del dominio", "LIBRACARGO_DATABASE_URL")
        cls._exigir_core_en_la_del_dominio(url)
        return cls(
            database_url=url,
            entorno=os.environ.get("ENTORNO", "dev"),
            debug=os.environ.get("DEBUG", "").lower() in {"1", "true", "si"},
            directorio_de_datos=os.environ.get("DATA_DIR", "./data"),
        )

    @staticmethod
    def _exigir_core_en_la_del_dominio(url_del_dominio: str) -> None:
        """El core es la base del dominio. Si alguien declara OTRA, el arranque muere.

        🔑 **`LIBRACARGO_LIBRACORE_DATABASE_URL` ya no hace falta** (ADR-054).
        Desde la `0015` el schema de LibraCore vive en la base del dominio, y
        sin la variable la app, `libracore-migrar` (libracore >= v1.190.1, que
        suma `libracargo` a `_UNA_SOLA_BASE`) y `libraauth-migrar` caen a
        `DATABASE_URL`. Se **sigue aceptando** puesta con la misma base: el
        compose de Suitrans, el de la demo y los que genera
        `libracore.provisioning` todavía la llevan, y sacarla de ahí es un
        paso aparte, con su OK.

        🔴 **Con otra base, fail-closed y no «gana la del dominio».** LibraCargo
        no soporta dos bases desde la `0015`: los comprobantes, las órdenes y la
        cuenta corriente se escriben en una sola transacción. Ignorar la
        variable en silencio dejaría a `libracore-migrar` (que sí la lee)
        migrando una base y a la app escribiendo en otra, y el modo de fallar es
        mudo: la app levanta, `/salud` da 200 y la facturación recién rompe al
        emitir. Una configuración que no cierra tiene que verse en el arranque.

        Los mensajes nombran las bases y no las URL: llevan la contraseña.
        """
        core = url_de_instancia("libracargo", core=True)
        if not core:
            return
        if not misma_base(url_del_dominio, core):
            raise RuntimeError(
                "LIBRACARGO_LIBRACORE_DATABASE_URL apunta a otra base "
                f"({_nombre_de_base(core)}) que la del dominio "
                f"({_nombre_de_base(url_del_dominio)}). LibraCargo corre con UNA sola base "
                "desde la migración 0015 (ADR-029): el schema de LibraCore vive en la del dominio. "
                "Sacá la variable, o ponela igual a LIBRACARGO_DATABASE_URL / DATABASE_URL. "
                "Si esa instancia todavía tiene el core aparte, unila antes con "
                "`libracore-unir-bases`."
            )
