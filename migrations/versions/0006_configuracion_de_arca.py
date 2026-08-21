"""Configuración de ARCA por razón social.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-20

Crea `configuracion_arca`: certificado, clave y ambiente con los que cada razón
social propia va a facturar electrónicamente. **Esta migración no habilita nada**
— la tabla nace vacía y la bandera `habilitado` arranca en falso.

🔴 **El `DROP TYPE` del `downgrade` es a mano y es obligatorio.** Alembic
autogenera el `drop_table` pero **no** el del tipo `ENUM`: sin él, bajar y
volver a subir muere con `DuplicateObject` y la migración *parece* reversible
sin serlo. Es exactamente lo que pasó con la `0001` (ADR-007), y el test del
ciclo completo lo agarra contando los tipos huérfanos.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuracion_arca",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("razon_social_id", sa.Integer(), nullable=False),
        sa.Column(
            "ambiente",
            sa.Enum("homologacion", "produccion", name="ambiente_arca"),
            nullable=False,
        ),
        sa.Column("certificado", sa.LargeBinary(), nullable=True),
        sa.Column("certificado_nombre", sa.String(length=160), nullable=True),
        sa.Column("clave", sa.LargeBinary(), nullable=True),
        sa.Column("clave_nombre", sa.String(length=160), nullable=True),
        sa.Column("habilitado", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        # Habilitado sin las dos mitades es una instancia que dice que puede
        # facturar y falla en el primer intento.
        sa.CheckConstraint(
            "NOT habilitado OR (certificado IS NOT NULL AND clave IS NOT NULL)",
            name="ck_arca_habilitado_con_credenciales",
        ),
        sa.ForeignKeyConstraint(["razon_social_id"], ["razones_sociales.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # Una configuración por razón social: el certificado es de un CUIT.
        sa.UniqueConstraint("razon_social_id"),
    )


def downgrade() -> None:
    op.drop_table("configuracion_arca")
    # Ver el encabezado: sin esto el tipo queda huérfano y el próximo upgrade
    # muere con `DuplicateObject`.
    op.execute("DROP TYPE IF EXISTS ambiente_arca")
