"""Las Cartas de Porte Electrónicas traídas de ARCA por su CTG (ADR-036).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-07

Dos tablas nuevas, vacías: `cartas_porte` (lo que el producto usa de la CPE, tipado, más la respuesta entera de
ARCA sin el PDF) y `cartas_porte_pdf` (el PDF, aparte). No cambia nada de lo que hay; la orden de carga gana una
referencia opcional desde la CPE (`orden_carga_id`, `ON DELETE SET NULL`), no una columna propia.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cartas_porte",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nro_ctg", sa.BigInteger, nullable=False),
        sa.Column("tipo_cpe", sa.Integer, nullable=True),
        sa.Column("sucursal", sa.Integer, nullable=True),
        sa.Column("nro_orden", sa.BigInteger, nullable=True),
        sa.Column("estado", sa.String(4), nullable=False),
        sa.Column("fecha_emision", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_vencimiento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_partida", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cuit_representada", sa.String(11), nullable=False),
        sa.Column("ambiente", sa.String(15), nullable=False),
        sa.Column("cuit_transportista", sa.String(11), nullable=True),
        sa.Column("cuit_pagador_flete", sa.String(11), nullable=True),
        sa.Column("cuit_chofer", sa.String(11), nullable=True),
        sa.Column("cuit_origen", sa.String(11), nullable=True),
        sa.Column("cuit_destino", sa.String(11), nullable=True),
        sa.Column("cuit_destinatario", sa.String(11), nullable=True),
        sa.Column("dominios", sa.String(40), nullable=True),
        sa.Column("cod_grano", sa.Integer, nullable=True),
        sa.Column("cosecha", sa.Integer, nullable=True),
        sa.Column("peso_bruto", sa.Integer, nullable=True),
        sa.Column("peso_tara", sa.Integer, nullable=True),
        sa.Column("peso_bruto_descarga", sa.Integer, nullable=True),
        sa.Column("peso_tara_descarga", sa.Integer, nullable=True),
        sa.Column("cod_provincia_origen", sa.Integer, nullable=True),
        sa.Column("cod_localidad_origen", sa.Integer, nullable=True),
        sa.Column("cod_provincia_destino", sa.Integer, nullable=True),
        sa.Column("cod_localidad_destino", sa.Integer, nullable=True),
        sa.Column("planta_destino", sa.Integer, nullable=True),
        sa.Column("km", sa.Integer, nullable=True),
        sa.Column("tarifa", sa.Numeric(14, 2), nullable=True),
        sa.Column("respuesta_arca", sa.Text, nullable=False),
        sa.Column("consultada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("orden_carga_id", sa.Integer,
                  sa.ForeignKey("ordenes_carga.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
        sa.UniqueConstraint("nro_ctg", name="uq_cartas_porte_ctg"),
        sa.UniqueConstraint("tipo_cpe", "sucursal", "nro_orden", name="uq_cartas_porte_numero"),
    )
    op.create_index("ix_cartas_porte_orden_carga_id", "cartas_porte", ["orden_carga_id"])

    op.create_table(
        "cartas_porte_pdf",
        sa.Column("carta_porte_id", sa.Integer,
                  sa.ForeignKey("cartas_porte.id", ondelete="CASCADE"),
                  primary_key=True, autoincrement=False),
        sa.Column("contenido", sa.LargeBinary, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cartas_porte_pdf")
    op.drop_index("ix_cartas_porte_orden_carga_id", table_name="cartas_porte")
    op.drop_table("cartas_porte")
