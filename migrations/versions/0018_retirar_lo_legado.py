"""Retira las tablas viejas: `comprobantes_legado` y `movimientos_cuenta_legado` (etapa 4).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-06

Desde la `0016` el comprobante vive en `facturas` del motor (ADR-030), y desde la
`0017` la cuenta corriente vive en `cc_asientos` (ADR-031). Las tablas viejas
quedaron como copia de sólo lectura. Esta revisión las borra, con sus tipos `ENUM`
(`tipo_comprobante`, `rol_cuenta`), que ya no usa nadie.

El plan era esperar un ciclo de uso. El humano decidió no esperar el 2026-10-06:
Suitrans, la única instancia de cliente, está en pruebas y el cliente sigue con su
sistema anterior. Cada instancia se respalda antes de desplegar.

🔴 **No tiene vuelta atrás**, como las del motor: lo que se borra no se puede
reconstruir desde lo que queda. Para volver, se restaura el respaldo.
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS movimientos_cuenta_legado")
    op.execute("DROP TABLE IF EXISTS comprobantes_legado")
    op.execute("DROP TYPE IF EXISTS rol_cuenta")
    op.execute("DROP TYPE IF EXISTS tipo_comprobante")


def downgrade() -> None:
    raise NotImplementedError(
        "No se baja: las tablas viejas no se pueden reconstruir desde lo que queda. "
        "Para volver atrás, restaurar el respaldo.")
