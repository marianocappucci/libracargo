"""La pre factura: lo propio de este producto sobre la bandeja del motor (ADR-032).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-06

La pre factura vive en `comprobantes_pendientes` del motor (ADR-030 de LibraCore, `libracore.pre_facturas`).
Esta revisión agrega las dos tablas con lo que sólo sabe este producto:

- `pre_facturas_cargo`: una fila por pre factura, con el **mismo id**: la razón social que facturaría y el
  tercero (`comprobantes_cargo` hace lo mismo con `facturas`).
- `pre_factura_ordenes`: la reserva de las órdenes. **`orden_id` es la clave primaria**: una orden está en a lo
  sumo una pre factura abierta, y lo garantiza la base.

Las dos nacen vacías: no cambia nada de lo que hay. Pide `comprobantes_pendientes` con las columnas de la pre
factura (`libracore-migrar`, que en el deploy corre antes que esta cadena).
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    con = op.get_bind()
    tiene = con.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'comprobantes_pendientes' AND column_name = 'numero_interno'")).scalar()
    if tiene is None:
        raise RuntimeError(
            "falta la pre factura del motor (`comprobantes_pendientes.numero_interno`) en esta base: "
            "corré `libracore-migrar upgrade --prefijo libracargo` antes, con libracore v1.140.0 o más")

    op.create_table(
        "pre_facturas_cargo",
        sa.Column("pre_factura_id", sa.BigInteger,
                  sa.ForeignKey("comprobantes_pendientes.id", ondelete="RESTRICT",
                                name="fk_pre_facturas_cargo_pre_factura"),
                  primary_key=True, autoincrement=False),
        sa.Column("razon_social_id", sa.Integer,
                  sa.ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cliente_id", sa.Integer,
                  sa.ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False),
    )
    op.create_index("ix_pre_facturas_cargo_cliente", "pre_facturas_cargo", ["cliente_id"])
    op.create_index("ix_pre_facturas_cargo_razon_social", "pre_facturas_cargo", ["razon_social_id"])

    op.create_table(
        "pre_factura_ordenes",
        sa.Column("orden_id", sa.Integer,
                  sa.ForeignKey("ordenes_carga.id", ondelete="RESTRICT"),
                  primary_key=True, autoincrement=False),
        sa.Column("pre_factura_id", sa.BigInteger,
                  sa.ForeignKey("comprobantes_pendientes.id", ondelete="RESTRICT",
                                name="fk_pre_factura_ordenes_pre_factura"),
                  nullable=False),
    )
    op.create_index("ix_pre_factura_ordenes_pre_factura", "pre_factura_ordenes", ["pre_factura_id"])


def downgrade() -> None:
    op.drop_table("pre_factura_ordenes")
    op.drop_table("pre_facturas_cargo")
