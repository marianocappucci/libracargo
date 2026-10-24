"""La caja pasa a `caja_movimientos` del motor, con lo propio en `movimientos_caja_cargo` (ADR-055).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-23

Hasta acá este producto llevaba su propia caja, `movimientos_caja`, que ni el motor ni
los otros productos veían. Desde esta revisión cada movimiento es una fila de
`caja_movimientos` de LibraCore (sus ganchos de caja y el `origen` con el que la caja de
un nodo sube al central, ADR-076 del motor), con lo propio de acá —el tercero, la
descripción, el recibo— en `movimientos_caja_cargo`, con el **mismo id**. Es lo que la
`0017` hizo con la cuenta corriente.

En una sola transacción:

1. Crea `movimientos_caja_cargo`.
2. Copia cada movimiento a `caja_movimientos` **con el mismo id**: la fecha como texto ISO,
   que es como la guarda el motor; el tipo y el medio de pago como texto; el importe tal
   cual (`NUMERIC`, sin pasar por `float`); `anulado` como `0`/`1`; `caja_id` con la misma
   regla que el motor cuando no se le dice (la caja por defecto, o la primera, o ninguna).
   Y lo propio, a `movimientos_caja_cargo`.
3. Adelanta la secuencia de `caja_movimientos` (sin retrocederla si el motor ya la había
   pasado).
4. Apunta la FK de `movimientos_cuenta_cargo.movimiento_caja_id` a `caja_movimientos`.
5. Renombra `movimientos_caja` a `movimientos_caja_legado`. **No se borra**: queda de sólo
   lectura, para comparar antes y después (`scripts/comparar_caja.py`) y como respaldo en
   la misma base. Se retira en una revisión aparte, cuando el humano lo pida.

🔴 **Los ids se conservan o la revisión no toca nada.** Si algún id de `movimientos_caja`
ya está ocupado en `caja_movimientos` por una fila que no es su copia, se niega con el
número de filas y los primeros ids. Remapear es una decisión aparte: mueve el vínculo de la
cuenta corriente, el log de auditoría y los enlaces `/caja?ver=<id>`.

**Idempotente**: `copiar_a_motor` sólo copia lo que no tiene su fila propia. Correrla dos
veces —o sobre una base a medias— no duplica nada.

Pide que `caja_movimientos` exista con el `origen` de la caja del nodo: libracore >= v1.188.0
(migración `0028_caja_del_nodo`); el pin de este producto es v1.191.0.
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

FK_CUENTA = "fk_movimientos_cuenta_cargo_movimiento_caja"
FK_CUENTA_ANTES = "movimientos_cuenta_cargo_movimiento_caja_id_fkey"


def _existe(con, tabla: str) -> bool:
    return con.execute(sa.text("SELECT to_regclass(:t)"), {"t": tabla}).scalar() is not None


def copiar_a_motor(con, origen: str = "movimientos_caja") -> dict[str, int]:
    """Copia a `caja_movimientos` y `movimientos_caja_cargo` lo que todavía no está. Devuelve los conteos.

    `origen` es la tabla de la caja propia: `movimientos_caja` al migrar, o `movimientos_caja_legado` para volver a
    correrla sobre una base ya migrada (los tests lo hacen). No hace `commit`: lo llama la revisión (que corre en una
    transacción). Es idempotente, y se niega —sin tocar nada— si un id a copiar lo ocupa otra fila del motor.
    """
    if origen not in ("movimientos_caja", "movimientos_caja_legado"):
        raise ValueError(f"tabla de origen desconocida: {origen}")
    # Lo que todavía no tiene su fila propia: la definición de «falta copiar».
    falta = "NOT EXISTS (SELECT 1 FROM movimientos_caja_cargo c WHERE c.movimiento_id = m.id)"
    ocupados = con.execute(sa.text(
        f"SELECT count(*), (array_agg(m.id ORDER BY m.id))[1:10] FROM {origen} m "
        f"JOIN caja_movimientos a ON a.id = m.id WHERE {falta}")).one()
    if ocupados[0]:
        raise RuntimeError(
            f"{ocupados[0]} ids de movimientos_caja ya están ocupados en caja_movimientos por otra fila "
            f"(los primeros: {ocupados[1]}). La caja no se mueve: remapear los ids es una decisión aparte.")

    caja_id = con.execute(sa.text(
        "SELECT coalesce((SELECT id FROM cajas WHERE es_default = 1 ORDER BY id LIMIT 1), "
        "(SELECT id FROM cajas ORDER BY id LIMIT 1))")).scalar()
    total = con.execute(sa.text(f"SELECT count(*) FROM {origen}")).scalar()
    a_copiar = con.execute(sa.text(f"SELECT count(*) FROM {origen} m WHERE {falta}")).scalar()

    con.execute(sa.text(
        "INSERT INTO caja_movimientos (id, fecha, tipo, concepto, monto, referencia, caja_id, medio_pago, "
        "anulado, created_at) "
        "SELECT m.id, to_char(m.fecha, 'YYYY-MM-DD'), m.tipo::text, m.concepto, m.importe, '', :caja_id, "
        "m.medio_pago::text, CASE WHEN m.anulado THEN 1 ELSE 0 END, "
        "to_char(m.created_at AT TIME ZONE 'America/Argentina/Buenos_Aires', 'YYYY-MM-DD HH24:MI:SS') "
        f"FROM {origen} m WHERE {falta} ORDER BY m.id"), {"caja_id": caja_id})
    con.execute(sa.text(
        "INSERT INTO movimientos_caja_cargo (movimiento_id, descripcion, tercero_id, recibo, origen_legado, "
        "created_at, updated_at, created_by, updated_by) "
        "SELECT m.id, m.descripcion, m.tercero_id, m.recibo, m.origen_legado, m.created_at, m.updated_at, "
        f"m.created_by, m.updated_by FROM {origen} m WHERE {falta} ORDER BY m.id"))

    # La secuencia sigue al id más alto, sin retroceder si el motor ya la había pasado.
    secuencia = con.execute(sa.text("SELECT pg_get_serial_sequence('caja_movimientos', 'id')")).scalar()
    maximo = con.execute(sa.text("SELECT coalesce(max(id), 0) FROM caja_movimientos")).scalar()
    ultimo, llamada = con.execute(sa.text(f"SELECT last_value, is_called FROM {secuencia}")).one()
    if maximo > (ultimo if llamada else 0):
        con.execute(sa.text("SELECT setval(:s, :m)"), {"s": secuencia, "m": maximo})
    return {"movimientos": total, "copiados": a_copiar, "ya_estaban": total - a_copiar}


def upgrade() -> None:
    con = op.get_bind()
    if not _existe(con, "caja_movimientos") or not con.execute(sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'caja_movimientos' "
            "AND column_name = 'origen'")).scalar():
        raise RuntimeError(
            "falta `caja_movimientos` con la columna `origen` del motor: corré `libracore-migrar upgrade "
            "--prefijo libracargo` antes (libracore >= v1.188.0, migración 0028_caja_del_nodo)")

    op.create_table(
        "movimientos_caja_cargo",
        sa.Column("movimiento_id", sa.BigInteger,
                  sa.ForeignKey("caja_movimientos.id", ondelete="RESTRICT",
                                name="fk_movimientos_caja_cargo_movimiento"),
                  primary_key=True, autoincrement=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("tercero_id", sa.Integer, sa.ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("recibo", sa.String(30), nullable=True),
        sa.Column("origen_legado", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )
    op.create_index("ix_caja_cargo_tercero", "movimientos_caja_cargo", ["tercero_id"])
    op.create_index("ix_caja_cargo_origen_legado", "movimientos_caja_cargo", ["origen_legado"], unique=True)

    copiar_a_motor(con)

    # La cuenta corriente apunta al movimiento del motor, que tiene el mismo id.
    viejas = con.execute(sa.text(
        "SELECT conname FROM pg_constraint WHERE contype = 'f' "
        "AND conrelid = 'movimientos_cuenta_cargo'::regclass AND confrelid = 'movimientos_caja'::regclass")).scalars().all()
    for nombre in viejas:
        op.drop_constraint(nombre, "movimientos_cuenta_cargo", type_="foreignkey")
    op.create_foreign_key(FK_CUENTA, "movimientos_cuenta_cargo", "caja_movimientos",
                          ["movimiento_caja_id"], ["id"], ondelete="RESTRICT")

    op.rename_table("movimientos_caja", "movimientos_caja_legado")
    op.execute("COMMENT ON TABLE movimientos_caja_legado IS "
               "'Sólo lectura desde la revisión 0032: la caja vive en caja_movimientos. Se retira aparte.'")


def downgrade() -> None:
    """Vuelve a la caja propia. **Sólo es seguro si la caja no cambió** desde la `0032`: lo cargado
    o anulado después no está en la tabla vieja, y volvería a su valor de antes."""
    con = op.get_bind()
    nuevos = con.execute(sa.text(
        "SELECT count(*) FROM movimientos_caja_cargo c "
        "WHERE NOT EXISTS (SELECT 1 FROM movimientos_caja_legado l WHERE l.id = c.movimiento_id)")).scalar()
    if nuevos:
        raise RuntimeError(f"hay {nuevos} movimientos de caja cargados después de la 0032: no se puede volver")
    cambiados = con.execute(sa.text(
        "SELECT count(*) FROM movimientos_caja_legado l "
        "JOIN caja_movimientos a ON a.id = l.id JOIN movimientos_caja_cargo c ON c.movimiento_id = l.id "
        "WHERE a.monto <> l.importe OR a.anulado <> CASE WHEN l.anulado THEN 1 ELSE 0 END "
        "OR a.fecha <> to_char(l.fecha, 'YYYY-MM-DD') OR a.tipo <> l.tipo::text OR a.concepto <> l.concepto "
        "OR a.medio_pago <> l.medio_pago::text OR c.tercero_id IS DISTINCT FROM l.tercero_id "
        "OR c.descripcion IS DISTINCT FROM l.descripcion OR c.recibo IS DISTINCT FROM l.recibo")).scalar()
    if cambiados:
        raise RuntimeError(f"hay {cambiados} movimientos de caja corregidos o anulados después de la 0032: "
                           "no se puede volver")
    ids = [r[0] for r in con.execute(sa.text("SELECT movimiento_id FROM movimientos_caja_cargo"))]
    op.drop_constraint(FK_CUENTA, "movimientos_cuenta_cargo", type_="foreignkey")
    op.rename_table("movimientos_caja_legado", "movimientos_caja")
    op.execute("COMMENT ON TABLE movimientos_caja IS NULL")
    op.create_foreign_key(FK_CUENTA_ANTES, "movimientos_cuenta_cargo", "movimientos_caja",
                          ["movimiento_caja_id"], ["id"], ondelete="RESTRICT")
    op.drop_table("movimientos_caja_cargo")
    if ids:
        con.execute(sa.text("DELETE FROM caja_movimientos WHERE id = ANY(:ids)"), {"ids": ids})
