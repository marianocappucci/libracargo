"""La Carta de Porte guarda desde cuándo está en su estado (`fechaInicioEstado` de ARCA).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-08

Una columna nueva, vacía: las CPE ya guardadas la completan la próxima vez que se actualicen. Pedido del humano al
ver una CPE «Anulada» cuyo PDF decía otra cosa: el PDF es de cuando se emitió y la anulación vino después.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cartas_porte", sa.Column("fecha_inicio_estado", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cartas_porte", "fecha_inicio_estado")
