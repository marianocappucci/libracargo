"""Las localidades llevan país: el catálogo suma el resto del Mercosur (ADR-042).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-08

- `localidades.pais` (ISO de dos letras), `AR` para todo lo que ya existe.
- `catalogo_id` pasa de 8 a 20 caracteres: los ids de afuera son `{PAÍS}-{geonameid}` (libracore v1.146.0).
- La unicidad suma el país: `(nombre, provincia, pais)`, con `NULLS NOT DISTINCT`.
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("localidades", sa.Column("pais", sa.String(2), nullable=False, server_default="AR"))
    op.alter_column("localidades", "catalogo_id", type_=sa.String(20), existing_type=sa.String(8))
    op.drop_constraint("uq_localidades_nombre_provincia", "localidades", type_="unique")
    op.create_unique_constraint("uq_localidades_nombre_provincia", "localidades", ["nombre", "provincia", "pais"],
                                postgresql_nulls_not_distinct=True)


def downgrade() -> None:
    op.drop_constraint("uq_localidades_nombre_provincia", "localidades", type_="unique")
    op.create_unique_constraint("uq_localidades_nombre_provincia", "localidades", ["nombre", "provincia"],
                                postgresql_nulls_not_distinct=True)
    op.alter_column("localidades", "catalogo_id", type_=sa.String(8), existing_type=sa.String(20))
    op.drop_column("localidades", "pais")
