"""Anular movimientos de caja.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-21

Agrega `movimientos_caja.anulado`. Todo lo que ya existe queda **vigente**:
sobre la instancia del cliente son **8.387 movimientos** migrados del legado, y
ninguno estaba anulado — en el sistema viejo anular era borrar.

🔴 **La columna se agrega con `server_default`, y no es opcional.** Alembic
autogenera `sa.Column("anulado", sa.Boolean(), nullable=False)` sin default, y
eso **falla en una tabla con filas**: PostgreSQL no sabe qué poner en las 8.387
que ya están. En una base vacía —la de los tests— pasa sin ruido, así que el
defecto viaja hasta producción y ahí no hay dónde esconderlo.

El default del servidor se deja puesto: no molesta, y saca del medio la
diferencia entre "lo inserta la aplicación" y "lo inserta un script".
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "movimientos_caja",
        sa.Column("anulado", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("movimientos_caja", "anulado")
