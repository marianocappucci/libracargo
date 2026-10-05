"""Una sola base: la restricción de la tabla de versión deja de llamarse como la del motor.

La tabla de versión de este producto se llamaba `alembic_version` y se renombró
a `alembic_version_libracargo` (ver `migrations/env.py`). Un `RENAME` de tabla
**no renombra sus restricciones**, así que la clave primaria siguió llamándose
`alembic_version_pkc`, el nombre que usa cualquier cadena de Alembic sin sufijo.

Mientras el schema de LibraCore vivió en otra base no importaba. Para unirlas
(etapa 3 del diseño `libracargo-modelo-normalizado-diseno`, salida A) la cadena
del motor tiene que crear **su** `alembic_version` en esta base, y PostgreSQL no
admite dos restricciones con el mismo nombre en un schema: `libracore-migrar`
muere con *relation "alembic_version_pkc" already exists*. Medido el 2026-10-05
sobre una copia de Suitrans.

Idempotente y sólo si hace falta: una base creada después del renombre ya tiene
el nombre bueno.
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'alembic_version_pkc'
                  AND conrelid = to_regclass('alembic_version_libracargo')
            ) THEN
                ALTER TABLE alembic_version_libracargo
                    RENAME CONSTRAINT alembic_version_pkc TO alembic_version_libracargo_pkc;
            END IF;
        END
        $$
        """
    )


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'alembic_version_libracargo_pkc'
                  AND conrelid = to_regclass('alembic_version_libracargo')
            ) AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'alembic_version_pkc') THEN
                ALTER TABLE alembic_version_libracargo
                    RENAME CONSTRAINT alembic_version_libracargo_pkc TO alembic_version_pkc;
            END IF;
        END
        $$
        """
    )
