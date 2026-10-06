"""Los comprobantes pasan a `facturas`, la tabla del motor (etapa 3b, ADR-030).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05

Hasta acá este producto tenía su propia tabla `comprobantes`. Desde esta revisión
el comprobante es **el de la familia**: una fila de `facturas` de LibraCore, con
lo propio de acá en `comprobantes_cargo` (diseño `libracargo-modelo-normalizado-
diseno`, etapa 3b). Pide la base unida de la `0015`: `facturas` tiene que existir
en esta misma base, así que `libracore-migrar` corre antes (es el orden que
declara el deploy).

Qué hace, en una sola transacción:

1. Crea `comprobante_de_apertura` y `comprobantes_cargo`.
2. Pasa el comprobante de apertura del legado (`pv 0`, `número 0`, ADR-010) a su
   tabla: **no es fiscal** y no entra en `facturas` (decisión 5 del diseño). Sus
   órdenes pasan de `comprobante_id` a `apertura_id`.
3. Copia cada comprobante a `facturas` **con el mismo id**, así las FK de
   `ordenes_carga` y `movimientos_cuenta` no cambian de valor: sólo de tabla.
   - el tipo va como código de ARCA y las fechas como texto ISO, que es como las
     guarda el motor; el vencimiento del CAE, como lo devuelve ARCA (`AAAAMMDD`);
   - los datos fiscales del cliente se copian de `terceros`, como hace el motor
     al emitir;
   - los ítems, uno por orden (las notas, uno con su motivo);
   - `ambiente = 'produccion'`: todo lo que hay es del cliente (un ensayo contra
     homologación nunca se guardó, ver `facturar`);
   - el emisor es la fila de `arca_config` del CUIT de la razón social, si hay
     una sola; si no, `NULL`, el emisor único;
   - las notas llevan `cbte_asoc_*` de su comprobante.
4. Adelanta la secuencia de `facturas`.
5. Reapunta las FK de `ordenes_carga` y `movimientos_cuenta` a `facturas`.
6. Renombra `comprobantes` a `comprobantes_legado`. **No se borra**: queda de
   sólo lectura un ciclo y se retira con su propio OK (etapa 4 del diseño).

🔴 **Se niega antes que romper.** Si dos comprobantes chocarían en el índice de
numeración del motor (`emisor, ambiente, tipo, pv, número`), o si un movimiento de
cuenta apunta al comprobante de apertura, levanta con el detalle y no toca nada.
"""
import json
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

#: Congelado acá y no importado de `app`: una migración tiene que dar lo mismo
#: aunque el código cambie después.
CODIGO_ARCA = {
    "factura_a": 1, "factura_b": 6, "factura_c": 11,
    "nota_credito_a": 3, "nota_credito_b": 8, "nota_credito_c": 13,
    "fce_a": 201, "fce_b": 206, "fce_c": 211,
    "nota_credito_fce_a": 203, "nota_credito_fce_b": 208, "nota_credito_fce_c": 213,
}
#: La condición de IVA del receptor con el código de la familia (`IVA_CODES`).
CODIGO_IVA = {
    "responsable_inscripto": 1, "monotributo": 6, "exento": 4,
    "consumidor_final": 5, "no_categorizado": 0,
}


def _digitos(texto):
    return "".join(c for c in (texto or "") if c.isdigit())


def _fk_de(con, tabla: str, columna: str) -> str | None:
    """El nombre de la FK de esa columna, como haya quedado en esta base."""
    return con.execute(sa.text(
        "SELECT c.conname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.conrelid = to_regclass(:t) AND c.contype = 'f' AND a.attname = :c"
    ), {"t": tabla, "c": columna}).scalar()


def _emisores(con) -> dict[int, int | None]:
    """`razon_social_id → arca_config.id` por CUIT, sólo si hay una sola fila de ese CUIT."""
    configs = con.execute(sa.text("SELECT id, cuit FROM arca_config WHERE activo = 1")).all()
    salida = {}
    for rid, cuit in con.execute(sa.text("SELECT id, cuit FROM razones_sociales")):
        candidatas = [c.id for c in configs if _digitos(cuit) and _digitos(c.cuit) == _digitos(cuit)]
        salida[rid] = candidatas[0] if len(candidatas) == 1 else None
    return salida


def _items(con) -> dict[int, list[dict]]:
    """Un ítem por orden, con la forma de ítem de la familia (la que lee el PDF del motor).

    La misma que arma `app.servicios.comprobantes.items_de` al emitir.
    """
    filas = con.execute(sa.text(
        "SELECT comprobante_id, id, fecha, remito, tarifa, alicuota_iva FROM ordenes_carga "
        "WHERE comprobante_id IS NOT NULL ORDER BY fecha, id"))
    items: dict[int, list[dict]] = {}
    for f in filas:
        tarifa = float(f.tarifa)
        items.setdefault(f.comprobante_id, []).append({
            "description": "Flete",
            "detalle": f"Orden {f.id} del {f.fecha:%d/%m/%Y}" + (f", remito {f.remito}" if f.remito else ""),
            "qty": 1, "unit_price": tarifa, "subtotal": tarifa,
            "iva_pct": float(f.alicuota_iva),
        })
    return items


def upgrade() -> None:
    con = op.get_bind()
    if con.execute(sa.text("SELECT to_regclass('facturas')")).scalar() is None:
        raise RuntimeError(
            "falta la tabla `facturas` del motor en esta base: corré `libracore-migrar upgrade "
            "--prefijo libracargo` antes (la instancia tiene que estar unida, revisión 0015)")

    op.create_table(
        "comprobante_de_apertura",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("razon_social_id", sa.Integer,
                  sa.ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cliente_id", sa.Integer,
                  sa.ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("neto", sa.Numeric(14, 2), nullable=False),
        sa.Column("iva", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("origen_legado", sa.String(40), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )
    op.create_table(
        "comprobantes_cargo",
        sa.Column("factura_id", sa.BigInteger,
                  sa.ForeignKey("facturas.id", ondelete="RESTRICT", name="fk_comprobantes_cargo_factura"),
                  primary_key=True, autoincrement=False),
        sa.Column("razon_social_id", sa.Integer,
                  sa.ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cliente_id", sa.Integer,
                  sa.ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("anulado", sa.Boolean, nullable=False),
        sa.Column("origen_legado", sa.String(40), nullable=True),
        sa.Column("cae_solicitado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comprobante_asociado_id", sa.BigInteger,
                  sa.ForeignKey("facturas.id", ondelete="RESTRICT", name="fk_comprobantes_cargo_asociado"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )
    op.create_index("ix_comprobantes_cargo_asociado", "comprobantes_cargo", ["comprobante_asociado_id"])
    op.create_index("ix_comprobantes_cargo_cliente", "comprobantes_cargo", ["cliente_id"])
    op.create_index("ix_comprobantes_cargo_razon_social", "comprobantes_cargo", ["razon_social_id"])
    op.create_index("ix_comprobantes_cargo_origen_legado", "comprobantes_cargo", ["origen_legado"],
                    unique=True)
    op.add_column("ordenes_carga", sa.Column(
        "apertura_id", sa.Integer,
        sa.ForeignKey("comprobante_de_apertura.id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_ordenes_apertura", "ordenes_carga", ["apertura_id"])

    # ── La apertura ────────────────────────────────────────────────────────
    aperturas = con.execute(sa.text(
        "SELECT * FROM comprobantes WHERE punto_venta = 0 AND numero = 0 "
        "AND origen_legado = 'apertura'")).mappings().all()
    ids_apertura = [a["id"] for a in aperturas]
    if ids_apertura:
        en_cuenta = con.execute(sa.text(
            "SELECT count(*) FROM movimientos_cuenta WHERE comprobante_id = ANY(:ids)"),
            {"ids": ids_apertura}).scalar()
        if en_cuenta:
            raise RuntimeError(
                f"{en_cuenta} movimientos de cuenta apuntan al comprobante de apertura: "
                "no estaba previsto (medido en 0) y no se mueven a ciegas")
    op.drop_constraint("ck_ordenes_facturada_con_comprobante", "ordenes_carga", type_="check")
    for a in aperturas:
        nuevo = con.execute(sa.text(
            "INSERT INTO comprobante_de_apertura (razon_social_id, cliente_id, fecha, neto, iva, "
            "total, origen_legado, created_at, updated_at, created_by, updated_by) VALUES "
            "(:razon_social_id, :cliente_id, :fecha, :neto, :iva, :total, :origen_legado, "
            ":created_at, :updated_at, :created_by, :updated_by) RETURNING id"), dict(a)).scalar()
        con.execute(sa.text(
            "UPDATE ordenes_carga SET apertura_id = :nuevo, comprobante_id = NULL "
            "WHERE comprobante_id = :viejo"), {"nuevo": nuevo, "viejo": a["id"]})

    # ── Los comprobantes, a `facturas` ─────────────────────────────────────
    comprobantes = con.execute(sa.text(
        "SELECT c.*, t.cuit AS t_cuit, t.razon_social AS t_razon, t.condicion_iva AS t_iva, "
        "       t.direccion AS t_direccion "
        "FROM comprobantes c JOIN terceros t ON t.id = c.cliente_id "
        "WHERE NOT (c.id = ANY(:ap)) ORDER BY c.id"), {"ap": ids_apertura}).mappings().all()
    por_id = {c["id"]: c for c in comprobantes}
    emisores = _emisores(con)
    items = _items(con)

    # El índice de numeración del motor, antes de escribir: un choque se dice con nombre.
    claves: dict[tuple, int] = {}
    for c in comprobantes:
        clave = (emisores.get(c["razon_social_id"]) or 0, CODIGO_ARCA[c["tipo"]],
                 c["punto_venta"], c["numero"])
        if clave in claves:
            raise RuntimeError(
                f"los comprobantes {claves[clave]} y {c['id']} tendrían la misma numeración en "
                f"`facturas` (emisor {clave[0] or 'único'}, tipo {clave[1]}, pv {clave[2]}, "
                f"número {clave[3]}): dos razones sociales sin ARCA propio no pueden compartir "
                "tipo, punto de venta y número")
        claves[clave] = c["id"]
    ya = con.execute(sa.text("SELECT count(*) FROM facturas WHERE id = ANY(:ids)"),
                     {"ids": list(por_id)}).scalar()
    if ya:
        raise RuntimeError(f"{ya} ids de comprobantes ya están ocupados en `facturas`")

    filas_factura, filas_cargo = [], []
    for c in comprobantes:
        asociado = por_id.get(c["comprobante_asociado_id"]) if c["comprobante_asociado_id"] else None
        if items.get(c["id"]):
            renglones = items[c["id"]]
        else:
            neto = float(c["neto"])
            renglones = [{"description": c["motivo"] or "Comprobante migrado", "qty": 1,
                          "unit_price": neto, "subtotal": neto}]
        vto: date | None = c["cae_vencimiento"]
        filas_factura.append({
            "id": c["id"], "tipo": CODIGO_ARCA[c["tipo"]], "punto_venta": c["punto_venta"],
            "numero": c["numero"], "fecha": c["fecha"].isoformat(),
            "cliente_cuit": c["t_cuit"] or "", "cliente_razon": c["t_razon"],
            "cliente_iva_cond": CODIGO_IVA.get(c["t_iva"], 0),
            "cliente_domicilio": c["t_direccion"] or "",
            "items": json.dumps(renglones, ensure_ascii=False),
            "subtotal": c["neto"], "iva_amount": c["iva"], "total": c["total"],
            "cae": c["cae"] or "", "cae_vto": vto.strftime("%Y%m%d") if vto else "",
            "observaciones": c["motivo"] or "",
            "fch_vto_pago": c["fch_vto_pago"].isoformat() if c["fch_vto_pago"] else "",
            "fce_cbu": c["fce_cbu"] or "", "fce_transmision": c["fce_transmision"] or "",
            "cbte_asoc_tipo": CODIGO_ARCA[asociado["tipo"]] if asociado else 0,
            "cbte_asoc_pv": asociado["punto_venta"] if asociado else 0,
            "cbte_asoc_nro": asociado["numero"] if asociado else 0,
            "cbte_asoc_fecha": asociado["fecha"].strftime("%Y%m%d") if asociado else "",
            "emisor_id": emisores.get(c["razon_social_id"]),
            "created_at": c["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
        })
        filas_cargo.append({k: c[k] for k in (
            "razon_social_id", "cliente_id", "anulado", "origen_legado", "cae_solicitado_en",
            "comprobante_asociado_id", "created_at", "updated_at", "created_by", "updated_by")}
            | {"factura_id": c["id"]})
    if filas_factura:
        con.execute(sa.text(
            "INSERT INTO facturas (id, tipo, punto_venta, numero, fecha, cliente_cuit, cliente_razon, "
            "cliente_iva_cond, cliente_domicilio, items, subtotal, iva_amount, total, concepto, cae, "
            "cae_vto, observaciones, ambiente, fch_vto_pago, fce_cbu, fce_transmision, cbte_asoc_tipo, "
            "cbte_asoc_pv, cbte_asoc_nro, cbte_asoc_fecha, emisor_id, created_at) VALUES "
            "(:id, :tipo, :punto_venta, :numero, :fecha, :cliente_cuit, :cliente_razon, "
            ":cliente_iva_cond, :cliente_domicilio, :items, :subtotal, :iva_amount, :total, 1, :cae, "
            ":cae_vto, :observaciones, 'produccion', :fch_vto_pago, :fce_cbu, :fce_transmision, "
            ":cbte_asoc_tipo, :cbte_asoc_pv, :cbte_asoc_nro, :cbte_asoc_fecha, :emisor_id, :created_at)"),
            filas_factura)
        con.execute(sa.text(
            "INSERT INTO comprobantes_cargo (factura_id, razon_social_id, cliente_id, anulado, "
            "origen_legado, cae_solicitado_en, comprobante_asociado_id, created_at, updated_at, "
            "created_by, updated_by) VALUES (:factura_id, :razon_social_id, :cliente_id, :anulado, "
            ":origen_legado, :cae_solicitado_en, :comprobante_asociado_id, :created_at, :updated_at, "
            ":created_by, :updated_by)"), filas_cargo)
    con.execute(sa.text(
        "SELECT setval(pg_get_serial_sequence('facturas', 'id'), "
        "coalesce((SELECT max(id) FROM facturas), 1), (SELECT count(*) > 0 FROM facturas))"))

    # ── Las FK, de `comprobantes` a `facturas` ─────────────────────────────
    for tabla, nombre in (("ordenes_carga", "fk_ordenes_carga_comprobante"),
                          ("movimientos_cuenta", "fk_movimientos_cuenta_comprobante")):
        viejo = _fk_de(con, tabla, "comprobante_id")
        if viejo:
            op.drop_constraint(viejo, tabla, type_="foreignkey")
        op.alter_column(tabla, "comprobante_id", type_=sa.BigInteger)
        op.create_foreign_key(nombre, tabla, "facturas", ["comprobante_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint(
        "ck_ordenes_facturada_con_comprobante", "ordenes_carga",
        "(estado = 'facturada' AND (comprobante_id IS NOT NULL) <> (apertura_id IS NOT NULL)) "
        "OR (estado <> 'facturada' AND comprobante_id IS NULL AND apertura_id IS NULL)")

    op.rename_table("comprobantes", "comprobantes_legado")
    op.execute("COMMENT ON TABLE comprobantes_legado IS "
               "'Sólo lectura desde la revisión 0016: el comprobante vive en facturas. Se retira en la etapa 4.'")


def downgrade() -> None:
    """Vuelve a la tabla propia. **Sólo es seguro sin comprobantes nuevos** desde la `0016`:
    lo que se haya emitido después está sólo en `facturas` y no vuelve."""
    con = op.get_bind()
    nuevos = con.execute(sa.text(
        "SELECT count(*) FROM comprobantes_cargo cc "
        "WHERE NOT EXISTS (SELECT 1 FROM comprobantes_legado l WHERE l.id = cc.factura_id)")).scalar()
    if nuevos:
        raise RuntimeError(f"hay {nuevos} comprobantes emitidos después de la 0016: no se puede volver")
    op.rename_table("comprobantes_legado", "comprobantes")
    op.execute("COMMENT ON TABLE comprobantes IS NULL")
    op.drop_constraint("ck_ordenes_facturada_con_comprobante", "ordenes_carga", type_="check")
    for tabla, nombre in (("ordenes_carga", "fk_ordenes_carga_comprobante"),
                          ("movimientos_cuenta", "fk_movimientos_cuenta_comprobante")):
        op.drop_constraint(nombre, tabla, type_="foreignkey")
        op.alter_column(tabla, "comprobante_id", type_=sa.Integer)
        op.create_foreign_key(None, tabla, "comprobantes", ["comprobante_id"], ["id"], ondelete="RESTRICT")
    # Lo que cambió después de la 0016 en lo propio (anulado, CAE pedido) vuelve a la tabla.
    con.execute(sa.text(
        "UPDATE comprobantes c SET anulado = cc.anulado, cae_solicitado_en = cc.cae_solicitado_en "
        "FROM comprobantes_cargo cc WHERE cc.factura_id = c.id"))
    for a in con.execute(sa.text("SELECT * FROM comprobante_de_apertura")).mappings().all():
        viejo = con.execute(sa.text(
            "SELECT id FROM comprobantes WHERE origen_legado = :o"), {"o": a["origen_legado"]}).scalar()
        con.execute(sa.text(
            "UPDATE ordenes_carga SET comprobante_id = :viejo, apertura_id = NULL "
            "WHERE apertura_id = :id"), {"viejo": viejo, "id": a["id"]})
    op.create_check_constraint(
        "ck_ordenes_facturada_con_comprobante", "ordenes_carga",
        "(estado = 'facturada' AND comprobante_id IS NOT NULL) "
        "OR (estado <> 'facturada' AND comprobante_id IS NULL)")
    ids = [r[0] for r in con.execute(sa.text("SELECT factura_id FROM comprobantes_cargo"))]
    op.drop_table("comprobantes_cargo")
    if ids:
        con.execute(sa.text("DELETE FROM facturas WHERE id = ANY(:ids)"), {"ids": ids})
    op.drop_index("ix_ordenes_apertura", "ordenes_carga")
    op.drop_column("ordenes_carga", "apertura_id")
    op.drop_table("comprobante_de_apertura")
