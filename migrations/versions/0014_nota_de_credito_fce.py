"""La nota de crédito de una FCE, y el CHECK de las notas que la incluye.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05

- Tres valores al `ENUM` `tipo_comprobante`: `nota_credito_fce_a`, `nota_credito_fce_b` y
  `nota_credito_fce_c` (los códigos 203, 208 y 213 de ARCA).
- `ck_comprobantes_nota_con_asociado` se rehace para contarlas como notas: toda nota (también la de
  una FCE) tiene comprobante asociado, y nada más lo tiene.

🔑 **Esta migración no toca ni una fila.** Ninguna fila es todavía una nota de FCE (el valor no existía),
así que el `CHECK` nuevo da lo mismo que el viejo para todo lo que hay. `::text` y no el literal del
`ENUM`, como en la `0012`: no depende de que el valor ya esté creado en la misma transacción.

⚠️ **El `downgrade` no quita los valores del `ENUM`** (PostgreSQL no lo permite; ver la `0012`) y sólo es
seguro sin notas de FCE emitidas: con el `CHECK` viejo, una nota de FCE con asociado lo violaría.
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

VALORES = ("nota_credito_fce_a", "nota_credito_fce_b", "nota_credito_fce_c")
NOMBRE = "ck_comprobantes_nota_con_asociado"
NOTAS = ("nota_credito_a", "nota_credito_b", "nota_credito_c")


def _check(tipos: tuple[str, ...]) -> str:
    return "(tipo::text IN ({})) = (comprobante_asociado_id IS NOT NULL)".format(
        ", ".join(f"'{t}'" for t in tipos))


def upgrade() -> None:
    for valor in VALORES:
        op.execute(f"ALTER TYPE tipo_comprobante ADD VALUE IF NOT EXISTS '{valor}'")
    op.drop_constraint(NOMBRE, "comprobantes", type_="check")
    op.create_check_constraint(NOMBRE, "comprobantes", _check(NOTAS + VALORES))


def downgrade() -> None:
    op.drop_constraint(NOMBRE, "comprobantes", type_="check")
    op.create_check_constraint(NOMBRE, "comprobantes", _check(NOTAS))
