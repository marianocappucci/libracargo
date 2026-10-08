"""Titulares de Carta de Porte: a quién se le emite y quién emite (ADR-044).

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-08

- `titulares_cpe`: el CUIT y la razón social del titular, la entidad de Entidades con que se vincula (si la hay),
  quién emite (`nosotros` o `titular`), si está activo y notas. Es libreta y no permiso: la delegación se lee de ARCA.
- Los titulares con plantilla (`plantillas_cpe`, ADR-043) ya emitieron a su nombre desde este sistema: se cargan como
  `nosotros`. Es un dato de la instancia —sale de su propia tabla—, no del repo: en una base vacía no inserta nada.
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "titulares_cpe",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cuit", sa.String(11), nullable=False, unique=True),
        sa.Column("razon_social", sa.String(120), nullable=False),
        sa.Column("tercero_id", sa.Integer, sa.ForeignKey("terceros.id", ondelete="SET NULL"), nullable=True),
        sa.Column("emite", sa.String(10), nullable=False, server_default="nosotros"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notas", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
        sa.CheckConstraint("emite IN ('nosotros', 'titular')", name="ck_titulares_cpe_emite"),
    )
    op.create_index("ix_titulares_cpe_tercero_id", "titulares_cpe", ["tercero_id"])
    # Un titular por plantilla. La entidad se busca por los dígitos del CUIT (en `terceros` hay CUIT con guiones) y,
    # si hay más de una, gana un cliente activo y el id más bajo. Sin entidad, el nombre provisorio es el CUIT.
    op.execute("""
        INSERT INTO titulares_cpe (cuit, razon_social, tercero_id, emite, activo)
        SELECT p.cuit_titular, COALESCE(t.razon_social, p.cuit_titular), t.id, 'nosotros', true
        FROM plantillas_cpe p
        LEFT JOIN LATERAL (
            SELECT id, razon_social FROM terceros
            WHERE replace(replace(cuit, '-', ''), '.', '') = p.cuit_titular
            ORDER BY es_cliente DESC, activo DESC, id
            LIMIT 1
        ) t ON true
    """)


def downgrade() -> None:
    op.drop_index("ix_titulares_cpe_tercero_id", table_name="titulares_cpe")
    op.drop_table("titulares_cpe")
