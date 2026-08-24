"""El CAE del comprobante.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-24

Hasta acá este producto **registraba** comprobantes: el número lo tipeaba una
persona y no había nada fiscal de por medio (F5, ADR-020 — *"emitir por ARCA es
F8, y mezclarlas haría que una diferencia de totales tuviera dos causas
posibles"*). Con la paridad de la migración ya verificada, F8 entra.

🔑 **Las tres columnas son NULL y no tienen default.** Los 741 comprobantes que
vinieron del legado no tienen CAE y nunca lo van a tener: son de un sistema que
facturaba por afuera. `cae IS NULL` es el estado normal de todo lo migrado y de
todo lo que se registre a mano mientras la razón social no tenga ARCA activo, no
una fila incompleta.

Esta migración **no toca ni una fila**: agrega tres columnas nullable. Después de
correrla los comprobantes, las órdenes y los saldos están idénticos.
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comprobantes", sa.Column("cae", sa.String(20), nullable=True))
    op.add_column(
        "comprobantes",
        sa.Column("cae_vencimiento", sa.Date(), nullable=True),
    )
    # Cuándo se le pidió a ARCA, que no es lo mismo que la fecha del
    # comprobante: un reintento después de que ARCA estuvo caído deja las dos
    # separadas, y sin esto no habría cómo saber que pasó.
    op.add_column(
        "comprobantes",
        sa.Column("cae_solicitado_en", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comprobantes", "cae_solicitado_en")
    op.drop_column("comprobantes", "cae_vencimiento")
    op.drop_column("comprobantes", "cae")
