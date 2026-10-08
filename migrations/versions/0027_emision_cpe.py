"""Emitir Cartas de Porte desde la orden (ADR-043).

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-08

- `cartas_porte.emitida`: si la emitió este sistema (las traídas de ARCA quedan en `false`).
- `configuracion_empresa.cpe_emision_habilitada`: la traba para emitir en producción, **apagada**.
- `plantillas_cpe`: lo último usado por titular (origen, grano, destino, planta, intervinientes), vacía.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cartas_porte", sa.Column("emitida", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("configuracion_empresa", sa.Column("cpe_emision_habilitada", sa.Boolean, nullable=False,
                                                     server_default=sa.false()))
    op.create_table(
        "plantillas_cpe",
        sa.Column("cuit_titular", sa.String(11), primary_key=True),
        sa.Column("datos", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("plantillas_cpe")
    op.drop_column("configuracion_empresa", "cpe_emision_habilitada")
    op.drop_column("cartas_porte", "emitida")
