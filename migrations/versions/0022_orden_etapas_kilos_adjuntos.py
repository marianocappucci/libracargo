"""La orden gana etapa, kilos de carga y de descarga, y adjuntos; el chofer, su CUIT (ADR-037).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-07

- `ordenes_carga.etapa` (tipo `etapa_orden`: asignada, cargada, en_viaje, descargada, cerrada), aparte del estado
  de facturación, que no cambia. **Todo lo que ya existe queda en `cerrada`**: son viajes hechos (en Suitrans,
  4.112 facturadas y 226 pendientes, 225 de más de 60 días; decisión del humano del 2026-10-07). Las órdenes
  nuevas nacen en `asignada`.
- `kg_bruto_carga`, `kg_tara_carga`, `kg_neto_carga` y los tres de descarga, enteros y vacíos. `cantidad` no se toca.
- `choferes.cuit` (once dígitos), vacío.
- `ordenes_adjuntos`, vacía: la foto del ticket de descarga y otros archivos, en la base para que entren en el respaldo.

El `downgrade` saca todo: se pierden las etapas, los kilos, los CUIT de choferes y los adjuntos cargados después.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_ETAPAS = ("asignada", "cargada", "en_viaje", "descargada", "cerrada")
_KILOS = ("kg_bruto_carga", "kg_tara_carga", "kg_neto_carga",
          "kg_bruto_descarga", "kg_tara_descarga", "kg_neto_descarga")


def upgrade() -> None:
    etapa = postgresql.ENUM(*_ETAPAS, name="etapa_orden")
    etapa.create(op.get_bind(), checkfirst=False)
    # Primero con «cerrada» de default, para que las filas existentes nazcan cerradas; después el default pasa
    # a «asignada», que es como nace una orden nueva.
    op.add_column("ordenes_carga", sa.Column(
        "etapa", postgresql.ENUM(*_ETAPAS, name="etapa_orden", create_type=False),
        nullable=False, server_default="cerrada"))
    op.alter_column("ordenes_carga", "etapa", server_default="asignada")
    op.create_index("ix_ordenes_etapa", "ordenes_carga", ["etapa"])

    for columna in _KILOS:
        op.add_column("ordenes_carga", sa.Column(columna, sa.Integer, nullable=True))
    op.create_check_constraint(
        "ck_ordenes_kilos_no_negativos", "ordenes_carga",
        " AND ".join(f"COALESCE({c}, 0) >= 0" for c in _KILOS))

    op.add_column("choferes", sa.Column("cuit", sa.String(11), nullable=True))
    op.create_index("ix_choferes_cuit", "choferes", ["cuit"])

    op.create_table(
        "ordenes_adjuntos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("orden_id", sa.Integer, sa.ForeignKey("ordenes_carga.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("tipo_contenido", sa.String(100), nullable=False),
        sa.Column("tamanio", sa.Integer, nullable=False),
        sa.Column("contenido", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
    )
    op.create_index("ix_ordenes_adjuntos_orden", "ordenes_adjuntos", ["orden_id"])


def downgrade() -> None:
    op.drop_index("ix_ordenes_adjuntos_orden", table_name="ordenes_adjuntos")
    op.drop_table("ordenes_adjuntos")
    op.drop_index("ix_choferes_cuit", table_name="choferes")
    op.drop_column("choferes", "cuit")
    op.drop_constraint("ck_ordenes_kilos_no_negativos", "ordenes_carga", type_="check")
    for columna in _KILOS:
        op.drop_column("ordenes_carga", columna)
    op.drop_index("ix_ordenes_etapa", table_name="ordenes_carga")
    op.drop_column("ordenes_carga", "etapa")
    postgresql.ENUM(name="etapa_orden").drop(op.get_bind(), checkfirst=False)
