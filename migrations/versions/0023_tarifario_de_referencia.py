"""El tarifario de referencia (una tarifa por tonelada por kilómetro) y los km y la tarifa por tonelada de la orden
(ADR-038).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-08

Tablas nuevas y vacías: `tarifarios` (una edición por vigencia) y `tarifas_referencia` (km → $/t). La orden gana
`km` y `tarifa_tonelada`, vacíos: no cambia el importe (`tarifa`) ni nada de lo facturado. El tarifario se carga
después, desde la pantalla o la API.
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tarifarios",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vigencia", sa.Date, nullable=False, unique=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("valor_estadia", sa.Numeric(14, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )
    op.create_table(
        "tarifas_referencia",
        sa.Column("tarifario_id", sa.Integer, sa.ForeignKey("tarifarios.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("km", sa.Integer, primary_key=True),
        sa.Column("tarifa", sa.Numeric(14, 2), nullable=False),
        sa.CheckConstraint("km >= 1 AND tarifa >= 0", name="ck_tarifas_referencia_valores"),
    )
    op.add_column("ordenes_carga", sa.Column("km", sa.Integer, nullable=True))
    op.add_column("ordenes_carga", sa.Column("tarifa_tonelada", sa.Numeric(14, 2), nullable=True))
    op.create_check_constraint("ck_ordenes_km_y_tarifa_tonelada", "ordenes_carga",
                               "COALESCE(km, 1) >= 1 AND COALESCE(tarifa_tonelada, 0) >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_ordenes_km_y_tarifa_tonelada", "ordenes_carga", type_="check")
    op.drop_column("ordenes_carga", "tarifa_tonelada")
    op.drop_column("ordenes_carga", "km")
    op.drop_table("tarifas_referencia")
    op.drop_table("tarifarios")
