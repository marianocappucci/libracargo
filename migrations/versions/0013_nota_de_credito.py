"""La nota de crédito sabe a qué comprobante acredita.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04

Agrega a `comprobantes`:

- `comprobante_asociado_id`: a qué comprobante acredita una nota (clave foránea a la misma
  tabla, `RESTRICT`). `NULL` en todo lo que no es una nota.
- `motivo`: por qué se emitió la nota.
- Un `CHECK`: toda nota de crédito tiene asociado, y nada que no sea una nota lo tiene.
- Un índice sobre el asociado: la guarda «esta factura ya tiene una nota» lo consulta.

🔑 **Esta migración no toca ni una fila.** Las dos columnas son `NULL` y no tienen default. El
`CHECK` es verdadero para todo lo que hay: ninguna fila es una nota (los 742 comprobantes de
Suitrans son facturas), así que `false = false`. El valor `nota_credito_*` ya estaba en el
`ENUM` desde la `0001`.

El `downgrade` sólo es seguro sin notas emitidas: borrar la columna perdería a qué factura
acredita cada una. Las notas con CAE existen en ARCA y no se pueden deshacer.
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comprobantes", sa.Column("comprobante_asociado_id", sa.Integer(), nullable=True))
    op.add_column("comprobantes", sa.Column("motivo", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_comprobantes_asociado", "comprobantes", "comprobantes",
        ["comprobante_asociado_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_comprobantes_asociado", "comprobantes", ["comprobante_asociado_id"])
    op.create_check_constraint(
        "ck_comprobantes_nota_con_asociado", "comprobantes",
        "(tipo::text IN ('nota_credito_a', 'nota_credito_b', 'nota_credito_c'))"
        " = (comprobante_asociado_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comprobantes_nota_con_asociado", "comprobantes", type_="check")
    op.drop_index("ix_comprobantes_asociado", table_name="comprobantes")
    op.drop_constraint("fk_comprobantes_asociado", "comprobantes", type_="foreignkey")
    op.drop_column("comprobantes", "motivo")
    op.drop_column("comprobantes", "comprobante_asociado_id")
