"""Se retiran las pre facturas (ADR-048): se BORRAN las que hay, con las reservas de sus órdenes.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-13

Decidido por el humano el 2026-10-13: «Facturar pendientes» pasa a facturar directo por ARCA y la pre factura
(ADR-032) deja de existir en el producto. **Las pre facturas que ya hay se borran**, y con ellas las reservas de las
órdenes: las órdenes que estaban reservadas vuelven a «Facturar pendientes» (nunca dejaron de estar pendientes, sólo
estaban apartadas).

Qué hace, en una sola transacción:

1. **Cuenta y deja el rastro** de lo que va a borrar: una línea por cada pre factura (número, estado, cliente, total) y
   los totales por estado, en el log del `alembic upgrade` (`print`) y en `auditoria` (una fila `baja` de
   `pre_factura`, con la lista en `datos_antes`). Sin pre facturas, no escribe nada.
2. Borra `pre_factura_ordenes` (las reservas) y **dropea la tabla**: es sólo de LibraCargo.
3. Dropea `pre_facturas_cargo` (el tercero de cada pre factura): también sólo de LibraCargo.
4. Borra de `comprobantes_pendientes` **sólo las filas que LibraCargo creó**: las que tienen `pre_facturas_cargo`
   o `origen_producto = 'libracargo'`. La tabla del motor **no se toca**: la usan otros productos (LibraDesk, Contalibra) y
   no se dropea.

🔑 **Las facturas ya emitidas desde una pre factura no se tocan.** El comprobante vive en `facturas` y sus órdenes
siguen facturadas; lo único que se pierde es el documento intermedio y su número interno `PF-0001`.

🔴 **Es irreversible: el deploy hace respaldo antes** (`pg_dump` verificado, como en cualquier migración con
`DELETE`). El `downgrade` recrea las dos tablas **vacías**; lo borrado se recupera restaurando ese respaldo.

**Idempotente**: si las tablas ya no existen (o la bandeja no tiene filas de LibraCargo) cuenta cero y no hace nada. Lo
llama `retirar(con)`, que devuelve lo que borró, para poder probarla dos veces seguidas.
"""
import json
from collections import Counter

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _existe(con, tabla: str) -> bool:
    return con.execute(sa.text("SELECT to_regclass(:t)"), {"t": tabla}).scalar() is not None


def retirar(con) -> dict:
    """Borra las pre facturas de LibraCargo y sus reservas. Devuelve `{pre_facturas, por_estado, reservas, ordenes}`."""
    hay_bandeja = _existe(con, "comprobantes_pendientes")
    hay_cargo = _existe(con, "pre_facturas_cargo")
    hay_reservas = _existe(con, "pre_factura_ordenes")

    # Las pre facturas de LibraCargo: las que tienen su fila propia y, por si falta alguna, las que el motor marca
    # como suyas (`origen_producto`). Nada más: la bandeja es compartida con otros productos.
    pre_facturas: list[dict] = []
    if hay_bandeja:
        criterios = ["(origen_producto = 'libracargo' AND origen_instancia = '')"]
        if hay_cargo:
            criterios.append("id IN (SELECT pre_factura_id FROM pre_facturas_cargo)")
        filas = con.execute(sa.text(
            "SELECT id, numero_interno, estado, cliente_razon, cliente_cuit, total, factura_id "
            f"FROM comprobantes_pendientes WHERE {' OR '.join(criterios)} ORDER BY id")).mappings().all()
        pre_facturas = [
            {"id": f["id"], "numero": f["numero_interno"], "estado": f["estado"], "cliente": f["cliente_razon"],
             "cuit": f["cliente_cuit"], "total": str(f["total"]), "factura_id": f["factura_id"]}
            for f in filas]

    reservas = con.execute(sa.text("SELECT count(*) FROM pre_factura_ordenes")).scalar() if hay_reservas else 0
    ordenes = con.execute(sa.text(
        "SELECT count(DISTINCT orden_id) FROM pre_factura_ordenes")).scalar() if hay_reservas else 0
    por_estado = dict(Counter(p["estado"] for p in pre_facturas))

    if pre_facturas or reservas:
        print(f"[0029] pre facturas de LibraCargo: {len(pre_facturas)} — por estado: {por_estado or '-'}; "
              f"reservas de órdenes: {reservas} ({ordenes} órdenes vuelven a Facturar pendientes)")
        for p in pre_facturas:
            print(f"[0029]   se borra {p['numero']} ({p['estado']}) — {p['cliente']} — total {p['total']}"
                  + (f" — facturada en el comprobante {p['factura_id']}" if p["factura_id"] else ""))
        if _existe(con, "auditoria"):
            con.execute(
                sa.text(
                    "INSERT INTO auditoria (usuario_nombre, entidad, entidad_id, accion, datos_antes) "
                    "VALUES ('migracion 0029', 'pre_factura', NULL, 'baja', CAST(:antes AS JSONB))"
                ),
                {"antes": json.dumps({"pre_facturas": pre_facturas, "reservas": reservas, "ordenes": ordenes})})
    else:
        print("[0029] pre facturas de LibraCargo: ninguna, no hay nada que borrar")

    # Primero lo que apunta a la bandeja (las dos FK son RESTRICT) y después las filas de la bandeja.
    # `DROP TABLE` por SQL y no `op.drop_table`: así `retirar(con)` se puede llamar fuera de Alembic, que es como se prueba.
    if hay_reservas:
        con.execute(sa.text("DROP TABLE pre_factura_ordenes"))
    if hay_cargo:
        con.execute(sa.text("DROP TABLE pre_facturas_cargo"))
    if pre_facturas:
        con.execute(sa.text("DELETE FROM comprobantes_pendientes WHERE id = ANY(:ids)"),
                    {"ids": [p["id"] for p in pre_facturas]})
    return {"pre_facturas": len(pre_facturas), "por_estado": por_estado, "reservas": reservas, "ordenes": ordenes}


def upgrade() -> None:
    retirar(op.get_bind())


def downgrade() -> None:
    """Recrea las dos tablas **vacías**. Lo borrado no vuelve: se recupera restaurando el respaldo del deploy."""
    op.create_table(
        "pre_facturas_cargo",
        sa.Column("pre_factura_id", sa.BigInteger,
                  sa.ForeignKey("comprobantes_pendientes.id", ondelete="RESTRICT",
                                name="fk_pre_facturas_cargo_pre_factura"),
                  primary_key=True, autoincrement=False),
        sa.Column("cliente_id", sa.Integer,
                  sa.ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False),
    )
    op.create_index("ix_pre_facturas_cargo_cliente", "pre_facturas_cargo", ["cliente_id"])
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
