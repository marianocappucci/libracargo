"""CPE fase 2: refresco programado de las cartas abiertas y catálogo de códigos de ARCA (ADR-051).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-18

- `configuracion_empresa.cpe_refresco_habilitado`: el interruptor del refresco programado, **apagado**.
- `configuracion_empresa.cpe_refresco_ultima_corrida` y `cpe_refresco_resumen`: cuándo corrió y qué pasó, vacíos.
- `catalogo_cpe`: lo que ARCA llama cada código de grano, provincia y localidad, **vacía**: se llena sola.

🔑 **No toca ni una fila.** `downgrade` borra el catálogo (se vuelve a llenar) y las tres columnas.
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("configuracion_empresa", sa.Column("cpe_refresco_habilitado", sa.Boolean, nullable=False,
                                                     server_default=sa.false()))
    op.add_column("configuracion_empresa", sa.Column("cpe_refresco_ultima_corrida", sa.DateTime(timezone=True),
                                                     nullable=True))
    op.add_column("configuracion_empresa", sa.Column("cpe_refresco_resumen", sa.String(200), nullable=True))
    op.create_table(
        "catalogo_cpe",
        sa.Column("ambiente", sa.String(15), primary_key=True),
        sa.Column("tipo", sa.String(10), primary_key=True),
        sa.Column("cod_provincia", sa.Integer, primary_key=True, server_default="0"),
        sa.Column("codigo", sa.Integer, primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tipo IN ('grano', 'provincia', 'localidad')", name="ck_catalogo_cpe_tipo"),
    )


def downgrade() -> None:
    op.drop_table("catalogo_cpe")
    op.drop_column("configuracion_empresa", "cpe_refresco_resumen")
    op.drop_column("configuracion_empresa", "cpe_refresco_ultima_corrida")
    op.drop_column("configuracion_empresa", "cpe_refresco_habilitado")
