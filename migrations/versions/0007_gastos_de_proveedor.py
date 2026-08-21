"""Gastos de proveedor.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-21

Crea `gastos_de_proveedor` —**vacía**— y le agrega a `movimientos_cuenta` el
puntero `gasto_id`, al lado de los otros tres orígenes de un asiento.

**No convierte el histórico.** Los 2.799 gastos del legado ya están como
movimientos de cuenta, con los saldos validados por el gate de F6; crearles un
documento retroactivo duplicaría el importe salvo que además se reescribieran
esos movimientos, y eso es tocar historia conciliada para no ganar nada.

🔴 **El `drop_constraint` del `downgrade` va con nombre.** Alembic autogenera
`op.drop_constraint(None, ...)`, y con `None` PostgreSQL no tiene qué borrar:
el downgrade falla y la migración *parece* reversible sin serlo. Por eso la
clave foránea se crea con nombre explícito.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

FK = "fk_movimientos_cuenta_gasto"


def upgrade() -> None:
    op.create_table(
        "gastos_de_proveedor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("proveedor_id", sa.Integer(), nullable=False),
        sa.Column("fletero_id", sa.Integer(), nullable=False),
        sa.Column("comprobante", sa.String(length=30), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("importe", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("anulado", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("importe > 0", name="ck_gastos_importe_positivo"),
        # Los dos desplegables tienen los mismos terceros adentro: un gasto que
        # un tercero se cobra a sí mismo es un error de carga facil de cometer.
        sa.CheckConstraint("proveedor_id <> fletero_id", name="ck_gastos_partes_distintas"),
        sa.ForeignKeyConstraint(["fletero_id"], ["terceros.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proveedor_id"], ["terceros.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gastos_fecha", "gastos_de_proveedor", ["fecha"])
    op.create_index("ix_gastos_fletero_fecha", "gastos_de_proveedor", ["fletero_id", "fecha"])
    op.create_index("ix_gastos_proveedor_fecha", "gastos_de_proveedor", ["proveedor_id", "fecha"])

    op.add_column("movimientos_cuenta", sa.Column("gasto_id", sa.Integer(), nullable=True))
    op.create_index("ix_cuenta_gasto", "movimientos_cuenta", ["gasto_id"])
    op.create_foreign_key(FK, "movimientos_cuenta", "gastos_de_proveedor",
                          ["gasto_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint(FK, "movimientos_cuenta", type_="foreignkey")
    op.drop_index("ix_cuenta_gasto", table_name="movimientos_cuenta")
    op.drop_column("movimientos_cuenta", "gasto_id")
    op.drop_index("ix_gastos_proveedor_fecha", table_name="gastos_de_proveedor")
    op.drop_index("ix_gastos_fletero_fecha", table_name="gastos_de_proveedor")
    op.drop_index("ix_gastos_fecha", table_name="gastos_de_proveedor")
    op.drop_table("gastos_de_proveedor")
