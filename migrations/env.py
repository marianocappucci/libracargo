from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

url = os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("Falta DATABASE_URL: LibraCargo migra sobre PostgreSQL.")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata

#: 🔴 **La tabla de versión es PROPIA de este producto, no `alembic_version`.**
#:
#: Este repo tiene UNA sola base: el esquema de LibraCore vive en la misma que
#: el dominio, sin `_core` aparte como en LibraClub, Gestiolibra y MedLibra. Y
#: LibraCore tiene **su propia cadena de Alembic** —hoy sin nadie que la corra,
#: pero eso está por cambiar—, que usa el nombre por defecto. Dos cadenas
#: compartiendo `alembic_version` se corrompen mutuamente: cada `upgrade`
#: pisaría la revisión de la otra y la siguiente correría sobre un esquema que
#: no es el que espera.
#:
#: LibraDesk, Gestiolibra y MedLibra ya usan el nombre con sufijo por este
#: mismo motivo. Acá faltaba, y era la precondición para que el deploy de este
#: producto pueda sumar la cadena del motor.
#:
#: ⚠️ **Renombrarlo NO es sólo esta línea.** Las bases que ya existen tienen la
#: tabla vieja: hay que correrles
#: `ALTER TABLE alembic_version RENAME TO alembic_version_libracargo` **antes**
#: de que llegue este código. Con el nombre nuevo y la tabla vieja, Alembic no
#: encuentra revisión, cree que la base está sin migrar y arranca en la `0001`
#: contra tablas que ya existen — lo que aborta el deploy.
VERSION_TABLE = "alembic_version_libracargo"


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
