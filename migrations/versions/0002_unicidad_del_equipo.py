"""la unicidad del equipo cuenta el "sin acoplado"

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 🔴 La restriccion original era `UNIQUE (patente_chasis, patente_acoplado)`
    # a secas. Como `patente_acoplado` es nullable y en SQL `NULL` no colisiona
    # con `NULL`, **dos camiones sin acoplado con la misma patente entraban los
    # dos** — y el camion sin acoplado es el caso comun, no el raro. Medido con
    # el ABM andando: la segunda alta devolvia 201.
    #
    # `NULLS NOT DISTINCT` (PostgreSQL 15+) hace que "sin acoplado" cuente como
    # un valor mas, que es lo que la restriccion siempre quiso decir.
    op.execute("ALTER TABLE vehiculos DROP CONSTRAINT uq_vehiculos_equipo")
    op.execute(
        "ALTER TABLE vehiculos ADD CONSTRAINT uq_vehiculos_equipo "
        "UNIQUE NULLS NOT DISTINCT (patente_chasis, patente_acoplado)"
    )


def downgrade() -> None:
    # Vuelve a la forma laxa. Puede fallar si mientras tanto se cargaron dos
    # equipos que solo se distinguen por el acoplado nulo -- y esta bien que
    # falle: bajar la restriccion no deberia borrar datos en silencio.
    op.execute("ALTER TABLE vehiculos DROP CONSTRAINT uq_vehiculos_equipo")
    op.execute(
        "ALTER TABLE vehiculos ADD CONSTRAINT uq_vehiculos_equipo "
        "UNIQUE (patente_chasis, patente_acoplado)"
    )
