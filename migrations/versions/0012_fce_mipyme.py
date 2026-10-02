"""Factura de Crédito Electrónica MiPyME (FCE).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-02

Agrega lo que una FCE necesita y el resto de los comprobantes no:

- Tres valores al `ENUM` `tipo_comprobante`: `fce_a`, `fce_b` y `fce_c` (los
  códigos 201, 206 y 211 de ARCA). Sólo facturas; ver `TipoComprobante`.
- `fch_vto_pago`, `fce_cbu` y `fce_transmision` en `comprobantes`: el vencimiento
  de pago que ARCA exige, y el CBU y la modalidad con los que salió.
- Un `CHECK`: una FCE sin vencimiento de pago no existe.

🔑 **Esta migración no toca ni una fila.** Las tres columnas son `NULL` y no tienen
default: todo lo que ya está (comprobantes migrados, registrados a mano o emitidos
por ARCA) queda idéntico. El `CHECK` es verdadero para ellos porque ninguno es FCE.

⚠️ **El `downgrade` no quita los valores del `ENUM`**: PostgreSQL no permite sacar
un valor de un tipo. Quedan sin usar, y volver a subir es inofensivo
(`ADD VALUE IF NOT EXISTS`). Bajar hasta `0001` sí borra el tipo entero, como
siempre. Antes de bajar, no puede haber comprobantes FCE: no hay cómo representarlos.
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

VALORES = ("fce_a", "fce_b", "fce_c")


def upgrade() -> None:
    for valor in VALORES:
        op.execute(f"ALTER TYPE tipo_comprobante ADD VALUE IF NOT EXISTS '{valor}'")
    op.add_column("comprobantes", sa.Column("fch_vto_pago", sa.Date(), nullable=True))
    op.add_column("comprobantes", sa.Column("fce_cbu", sa.String(22), nullable=True))
    op.add_column("comprobantes", sa.Column("fce_transmision", sa.String(3), nullable=True))
    op.create_check_constraint(
        "ck_comprobantes_fce_vencimiento", "comprobantes",
        "tipo::text NOT IN ('fce_a', 'fce_b', 'fce_c') OR fch_vto_pago IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comprobantes_fce_vencimiento", "comprobantes", type_="check")
    op.drop_column("comprobantes", "fce_transmision")
    op.drop_column("comprobantes", "fce_cbu")
    op.drop_column("comprobantes", "fch_vto_pago")
