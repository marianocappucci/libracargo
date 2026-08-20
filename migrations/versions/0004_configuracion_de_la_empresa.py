"""Los datos de la empresa que usa la instancia

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-19 16:21:05.069322
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Una sola fila, garantizada por el CHECK: con dos configuraciones, la
    # aplicacion tendria que elegir una, y el papel saldria con los datos de
    # ayer sin que nadie lo note.
    op.create_table('configuracion_empresa',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('razon_social', sa.String(length=120), nullable=False),
    sa.Column('nombre_fantasia', sa.String(length=120), nullable=True),
    sa.Column('cuit', sa.String(length=13), nullable=True),
    sa.Column('condicion_iva', sa.String(length=60), nullable=True),
    sa.Column('ingresos_brutos', sa.String(length=30), nullable=True),
    sa.Column('inicio_actividades', sa.String(length=10), nullable=True),
    sa.Column('domicilio', sa.String(length=160), nullable=True),
    sa.Column('localidad', sa.String(length=80), nullable=True),
    sa.Column('provincia', sa.String(length=60), nullable=True),
    sa.Column('codigo_postal', sa.String(length=12), nullable=True),
    sa.Column('telefono', sa.String(length=40), nullable=True),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('sitio_web', sa.String(length=120), nullable=True),
    sa.Column('pie_de_impresion', sa.Text(), nullable=True),
    sa.Column('logo', sa.LargeBinary(), nullable=True),
    sa.Column('logo_tipo', sa.String(length=60), nullable=True),
    sa.Column('logo_nombre', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.CheckConstraint('id = 1', name='ck_configuracion_una_sola_fila'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # Una sola fila, garantizada por el CHECK: con dos configuraciones, la
    # aplicacion tendria que elegir una, y el papel saldria con los datos de
    # ayer sin que nadie lo note.
    op.drop_table('configuracion_empresa')
