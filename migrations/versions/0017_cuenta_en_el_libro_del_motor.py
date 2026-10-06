"""La cuenta corriente pasa al libro de terceros del motor, `cc_asientos` (ADR-031).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06

Hasta acá este producto llevaba su propio libro, `movimientos_cuenta`. Desde esta
revisión cada asiento es una fila de `cc_asientos`, el libro de cuenta corriente de
terceros de LibraCore (su ADR-026, migración `0019_libro_de_terceros`), con lo propio
de acá —de qué orden, cobro o gasto salió— en `movimientos_cuenta_cargo`. Es la
etapa 5 del diseño del wiki («cuenta-corriente-de-terceros-diseno», opción A).

En una sola transacción:

1. Crea `movimientos_cuenta_cargo`.
2. Copia cada asiento a `cc_asientos` **con el mismo id**: la fecha como texto ISO,
   que es como la guarda el motor; el rol como texto; el comprobante como
   `factura_id` (desde la `0016` ya es una fila de `facturas`).
3. Adelanta la secuencia de `cc_asientos`.
4. Pone la FK del tercero sobre `cc_asientos.tercero_id`. El motor no la declara
   porque el tercero es del producto, y en esta base el producto la sostiene.
5. Renombra `movimientos_cuenta` a `movimientos_cuenta_legado`. **No se borra**:
   queda de sólo lectura un ciclo, como `comprobantes_legado`.

🔴 Pide que `cc_asientos` exista y esté vacía en las filas que se copian: si no, no
toca nada.
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

FK_TERCERO = "fk_cc_asientos_tercero_libracargo"


def upgrade() -> None:
    con = op.get_bind()
    if con.execute(sa.text("SELECT to_regclass('cc_asientos')")).scalar() is None:
        raise RuntimeError(
            "falta la tabla `cc_asientos` del motor: corré `libracore-migrar upgrade --prefijo "
            "libracargo` antes (libracore >= v1.136.0, migración 0019_libro_de_terceros)")
    ocupados = con.execute(sa.text(
        "SELECT count(*) FROM cc_asientos a JOIN movimientos_cuenta m ON m.id = a.id")).scalar()
    if ocupados:
        raise RuntimeError(f"{ocupados} ids de movimientos_cuenta ya están ocupados en cc_asientos")

    op.create_table(
        "movimientos_cuenta_cargo",
        sa.Column("asiento_id", sa.BigInteger,
                  sa.ForeignKey("cc_asientos.id", ondelete="RESTRICT",
                                name="fk_movimientos_cuenta_cargo_asiento"),
                  primary_key=True, autoincrement=False),
        sa.Column("orden_id", sa.Integer,
                  sa.ForeignKey("ordenes_carga.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("movimiento_caja_id", sa.Integer,
                  sa.ForeignKey("movimientos_caja.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("gasto_id", sa.Integer,
                  sa.ForeignKey("gastos_de_proveedor.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )
    op.create_index("ix_cuenta_cargo_orden", "movimientos_cuenta_cargo", ["orden_id"])
    op.create_index("ix_cuenta_cargo_caja", "movimientos_cuenta_cargo", ["movimiento_caja_id"])
    op.create_index("ix_cuenta_cargo_gasto", "movimientos_cuenta_cargo", ["gasto_id"])

    con.execute(sa.text(
        "INSERT INTO cc_asientos (id, fecha, tercero_id, rol, concepto, descripcion, debe, haber, "
        "factura_id, origen_legado, created_at) "
        "SELECT id, to_char(fecha, 'YYYY-MM-DD'), tercero_id, rol::text, concepto, descripcion, "
        "debe, haber, comprobante_id, origen_legado, "
        "to_char(created_at AT TIME ZONE 'America/Argentina/Buenos_Aires', 'YYYY-MM-DD HH24:MI:SS') "
        "FROM movimientos_cuenta ORDER BY id"))
    con.execute(sa.text(
        "INSERT INTO movimientos_cuenta_cargo (asiento_id, orden_id, movimiento_caja_id, gasto_id, "
        "created_at, updated_at, created_by, updated_by) "
        "SELECT id, orden_id, movimiento_caja_id, gasto_id, created_at, updated_at, created_by, "
        "updated_by FROM movimientos_cuenta ORDER BY id"))
    con.execute(sa.text(
        "SELECT setval(pg_get_serial_sequence('cc_asientos', 'id'), "
        "coalesce((SELECT max(id) FROM cc_asientos), 1), (SELECT count(*) > 0 FROM cc_asientos))"))
    op.create_foreign_key(FK_TERCERO, "cc_asientos", "terceros", ["tercero_id"], ["id"],
                          ondelete="RESTRICT")

    op.rename_table("movimientos_cuenta", "movimientos_cuenta_legado")
    op.execute("COMMENT ON TABLE movimientos_cuenta_legado IS "
               "'Sólo lectura desde la revisión 0017: la cuenta vive en cc_asientos. Se retira en un ciclo.'")


def downgrade() -> None:
    """Vuelve al libro propio. **Sólo es seguro si la cuenta no cambió** desde la `0017`:
    lo asentado después no está en la tabla vieja, y lo corregido o borrado después
    volvería a su valor de antes."""
    con = op.get_bind()
    nuevos = con.execute(sa.text(
        "SELECT count(*) FROM movimientos_cuenta_cargo c "
        "WHERE NOT EXISTS (SELECT 1 FROM movimientos_cuenta_legado l WHERE l.id = c.asiento_id)")).scalar()
    if nuevos:
        raise RuntimeError(f"hay {nuevos} asientos escritos después de la 0017: no se puede volver")
    op.rename_table("movimientos_cuenta_legado", "movimientos_cuenta")
    op.execute("COMMENT ON TABLE movimientos_cuenta IS NULL")
    op.drop_constraint(FK_TERCERO, "cc_asientos", type_="foreignkey")
    ids = [r[0] for r in con.execute(sa.text("SELECT asiento_id FROM movimientos_cuenta_cargo"))]
    op.drop_table("movimientos_cuenta_cargo")
    if ids:
        con.execute(sa.text("DELETE FROM cc_asientos WHERE id = ANY(:ids)"), {"ids": ids})
