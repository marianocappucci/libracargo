"""De qué nodo vino cada asiento del libro: `origen_nodo` y `origen_nodo_id` en `movimientos_cuenta_cargo` (ADR-056).

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-24

Con un nodo vinculado, la cuenta corriente se escribe **sólo en el nodo** y sube al central como `cargo.asiento`. El asiento
del central es otra fila, con otro id: para aplicar dos veces lo mismo sin duplicarlo, y para encontrarlo cuando el nodo lo
corrige, lo borra o lo contraasienta, el central guarda el **id del nodo** junto al asiento. Es lo que el motor hace con la
caja (`caja_movimientos.origen` y `origen_id`, libracore ADR-076): el mismo patrón, en la fila propia de este producto
porque el libro del motor (`cc_asientos`) no tiene un origen de nodo (su `origen` es el hecho que lo originó).

Aditiva y nullable: una fila sin nodo (todo lo que ya existe) queda con las dos en `NULL`. El índice único parcial es lo
que vuelve **duro** lo que el aplicador consulta: aplicar la misma operación dos veces es una fila, no dos.
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("movimientos_cuenta_cargo", sa.Column("origen_nodo", sa.Text(), nullable=True))
    op.add_column("movimientos_cuenta_cargo", sa.Column("origen_nodo_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "ux_cuenta_cargo_origen_nodo", "movimientos_cuenta_cargo", ["origen_nodo", "origen_nodo_id"], unique=True,
        postgresql_where=sa.text("origen_nodo IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_cuenta_cargo_origen_nodo_junto", "movimientos_cuenta_cargo",
        "(origen_nodo IS NULL) = (origen_nodo_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cuenta_cargo_origen_nodo_junto", "movimientos_cuenta_cargo", type_="check")
    op.drop_index("ux_cuenta_cargo_origen_nodo", table_name="movimientos_cuenta_cargo")
    op.drop_column("movimientos_cuenta_cargo", "origen_nodo_id")
    op.drop_column("movimientos_cuenta_cargo", "origen_nodo")
