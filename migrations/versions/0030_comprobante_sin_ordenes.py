"""`comprobantes_cargo.sin_ordenes`: la factura directa y la nota de débito no agrupan órdenes (ADR-048).

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-13

El gate de F5 compara cada comprobante contra las órdenes que agrupa. «Nueva factura» (conceptos libres) y la nota de
débito no tienen órdenes: sin una marca que lo diga, cada una aparecería como un comprobante que no coincide con sus
órdenes, siempre. La marca va en la tabla propia (`comprobantes_cargo`), no en `facturas`, que es del motor.

🔑 **No toca ni una fila.** La columna nace `false` para todo lo que hay, y todo lo que hay agrupa órdenes (o es una nota
de crédito, que se compara por su original). El `downgrade` sólo es seguro sin facturas directas ni notas de débito
emitidas: borrar la columna perdería cuáles eran, y el gate las pondría en rojo.
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comprobantes_cargo",
                  sa.Column("sin_ordenes", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("comprobantes_cargo", "sin_ordenes")
