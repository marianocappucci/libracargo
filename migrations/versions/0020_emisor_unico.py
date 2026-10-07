"""Un solo emisor: «Datos de la empresa». Se retira la razón social (ADR-035).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-07

El CUIT del emisor estaba en tres lugares que había que mantener iguales a mano: `configuracion_empresa`,
`razones_sociales` y `arca_config`. Se queda uno solo, la empresa; `arca_config` queda como lo técnico
(certificado, clave, punto de venta y ambiente) y se emite sólo si su CUIT es el de la empresa.

Esta revisión:

1. **Copia a la empresa lo que sólo estaba en la razón social**, antes de borrarla (ver `_copiar_a_la_empresa`).
2. **Pasa `configuracion_empresa.condicion_iva` de texto libre a la enumeración del tercero** (`condicion_iva`).
   Lo que se reconoce se mapea (`_condicion_de`); lo demás queda en `NULL` y se vuelve a elegir en la pantalla.
3. **Quita `razon_social_id`** de `ordenes_carga`, `comprobantes_cargo`, `pre_facturas_cargo` y
   `comprobante_de_apertura`, con sus índices y claves, y **borra `razones_sociales`**. El tipo `ENUM`
   `condicion_iva` se queda: lo usa `terceros`.

`comprobantes_cargo` se queda como la marca «este comprobante es de LibraCargo» (la que lee `puede_ver`), con el
tercero, el anulado y el origen del legado; sólo pierde la columna.

🔴 **El `downgrade` recrea la estructura, no la historia**: vuelve la tabla con **una** fila hecha de la empresa
y las columnas apuntando a ella. Las razones sociales que hubiera antes de subir no se reconstruyen (Suitrans
tenía una sola).
"""
from __future__ import annotations

import re
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

#: Las tablas que llevaban la columna, con el nombre de su índice (si lo tenían).
_TABLAS = (
    ("ordenes_carga", None),
    ("comprobantes_cargo", "ix_comprobantes_cargo_razon_social"),
    ("pre_facturas_cargo", "ix_pre_facturas_cargo_razon_social"),
    ("comprobante_de_apertura", None),
)

#: Cómo se lee cada valor de la enumeración, para el `downgrade` (donde vuelve a ser texto).
_ETIQUETA = {
    "responsable_inscripto": "Responsable Inscripto",
    "monotributo": "Monotributista",
    "exento": "Exento",
    "consumidor_final": "Consumidor Final",
    "no_categorizado": "",
}


def _condicion_de(texto: str | None) -> str | None:
    """El valor de `condicion_iva` que dice este texto libre, o `None` si no se reconoce.

    Se reconoce lo que alguien escribe de verdad: «Responsable Inscripto», «IVA Responsable Inscripto», «RI»,
    «Resp. Insc.», «Monotributo», «Monotributista», «Exento», «Consumidor Final». **Nada se adivina**: un texto
    raro queda en `NULL` antes que una condición fiscal equivocada, de la que depende qué factura se puede emitir.
    """
    normal = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    normal = re.sub(r"[^a-z0-9]+", " ", normal).strip()
    if not normal:
        return None
    # «No inscripto» y «no responsable» son otra cosa que «inscripto»: se descartan antes.
    if re.search(r"\bno (inscripto|responsable)\b", normal):
        return None
    if "monotribut" in normal:
        return "monotributo"
    if "exent" in normal:
        return "exento"
    if "consumidor" in normal:
        return "consumidor_final"
    if "inscripto" in normal or normal in {"ri", "resp insc", "resp inscripto", "iva ri"}:
        return "responsable_inscripto"
    return None


def _digitos(texto: str | None) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def _razon_de_la_empresa(razones: list) -> object | None:
    """La razón social que es **la** empresa, o `None` si no se puede decir sin adivinar.

    Es la única que hay, o, si hay más de una (el legado facturaba con dos nombres), la única con CUIT.
    """
    if len(razones) == 1:
        return razones[0]
    con_cuit = [r for r in razones if _digitos(r.cuit)]
    return con_cuit[0] if len(con_cuit) == 1 else None


def _copiar_a_la_empresa(con) -> None:
    """Lo que tenía la razón social y la empresa no, a la empresa. Nunca pisa lo que la empresa ya tiene.

    - Sin fila en `configuracion_empresa`, la crea (`id = 1`) con el nombre de la razón social.
    - Sin CUIT, copia el de la razón social; sin condición de IVA, la suya (salvo `no_categorizado`, que
      no es un dato); sin razón social (texto), su nombre.
    - Con **dos o más** razones sociales y ninguna única con CUIT, no se elige: se copia sólo el nombre de la
      primera activa si hace falta crear la fila, y el CUIT y la condición se cargan por la pantalla.
    """
    razones = con.execute(sa.text(
        "SELECT id, nombre, cuit, condicion_iva::text AS condicion_iva, activa FROM razones_sociales "
        "ORDER BY id")).fetchall()
    if not razones:
        return
    elegida = _razon_de_la_empresa(razones)
    empresa = con.execute(sa.text(
        "SELECT razon_social, cuit, condicion_iva FROM configuracion_empresa WHERE id = 1")).fetchone()
    if empresa is None:
        base = elegida or next((r for r in razones if r.activa), razones[0])
        con.execute(
            sa.text("INSERT INTO configuracion_empresa (id, razon_social) VALUES (1, :nombre)"),
            {"nombre": base.nombre[:120]})
        empresa = con.execute(sa.text(
            "SELECT razon_social, cuit, condicion_iva FROM configuracion_empresa WHERE id = 1")).fetchone()
    if elegida is None:
        return
    cambios: dict[str, str] = {}
    if not (empresa.razon_social or "").strip():
        cambios["razon_social"] = elegida.nombre[:120]
    if not _digitos(empresa.cuit) and _digitos(elegida.cuit):
        cambios["cuit"] = elegida.cuit
    if empresa.condicion_iva is None and elegida.condicion_iva != "no_categorizado":
        cambios["condicion_iva"] = elegida.condicion_iva
    if cambios:
        # Los nombres de columna son los de arriba, fijos: no entra texto de afuera en el SQL.
        asignaciones = ", ".join(f"{c} = :{c}" for c in cambios)
        con.execute(sa.text(f"UPDATE configuracion_empresa SET {asignaciones} WHERE id = 1"), cambios)


def upgrade() -> None:
    con = op.get_bind()

    # ── 1. La condición de IVA de la empresa pasa a ser la enumeración ─────────────────────────────
    # Se lee el texto, se cambia el tipo de la columna (sin conservar nada) y se vuelve a escribir lo reconocido.
    # Es a lo sumo una fila (`ck_configuracion_una_sola_fila`).
    previo = con.execute(sa.text("SELECT condicion_iva FROM configuracion_empresa WHERE id = 1")).scalar()
    op.alter_column(
        "configuracion_empresa", "condicion_iva",
        existing_type=sa.String(60), type_=postgresql.ENUM(name="condicion_iva", create_type=False),
        existing_nullable=True, postgresql_using="NULL")
    mapeada = _condicion_de(previo)
    if mapeada is not None:
        con.execute(
            sa.text("UPDATE configuracion_empresa SET condicion_iva = CAST(:c AS condicion_iva) WHERE id = 1"),
            {"c": mapeada})

    # ── 2. Lo que sólo estaba en la razón social, a la empresa ─────────────────────────────────────
    _copiar_a_la_empresa(con)

    # ── 3. Se quita la razón social ────────────────────────────────────────────────────────────────
    for tabla, indice in _TABLAS:
        if indice:
            op.drop_index(indice, table_name=tabla)
        # Soltar la columna suelta también su clave foránea.
        op.drop_column(tabla, "razon_social_id")
    op.drop_table("razones_sociales")


def downgrade() -> None:
    con = op.get_bind()

    # La tabla, como la dejó la baseline.
    op.create_table(
        "razones_sociales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("cuit", sa.String(13), nullable=True),
        sa.Column("condicion_iva", postgresql.ENUM(name="condicion_iva", create_type=False), nullable=False),
        sa.Column("punto_venta", sa.Integer(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("codigo_legado", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("nombre", name="uq_razones_sociales_nombre"),
        sa.UniqueConstraint("codigo_legado", name="uq_razones_sociales_codigo_legado"),
    )
    # Una sola fila, hecha de la empresa (si la hay): el punto de venta es el de la configuración de ARCA.
    nueva = con.execute(sa.text(
        "INSERT INTO razones_sociales (nombre, cuit, condicion_iva, punto_venta, activa, codigo_legado) "
        "SELECT razon_social, cuit, COALESCE(condicion_iva, 'no_categorizado'::condicion_iva), "
        "       COALESCE((SELECT punto_venta FROM arca_config WHERE activo = 1 ORDER BY id LIMIT 1), 1), "
        "       true, 1 "
        "FROM configuracion_empresa WHERE id = 1 RETURNING id")).scalar()

    # Las columnas vuelven **nulas permitidas**, apuntando a esa fila: sin empresa no hay a quién apuntar.
    for tabla, indice in _TABLAS:
        op.add_column(tabla, sa.Column(
            "razon_social_id", sa.Integer(),
            sa.ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=True))
        if nueva is not None:
            con.execute(sa.text(f"UPDATE {tabla} SET razon_social_id = :id"), {"id": nueva})
        if indice:
            op.create_index(indice, tabla, ["razon_social_id"])

    # La condición de IVA de la empresa vuelve a ser texto libre, con la etiqueta de siempre.
    op.alter_column(
        "configuracion_empresa", "condicion_iva",
        existing_type=postgresql.ENUM(name="condicion_iva", create_type=False), type_=sa.String(60),
        existing_nullable=True,
        postgresql_using=(
            "CASE condicion_iva::text "
            + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in _ETIQUETA.items() if v)
            + " ELSE NULL END"))
