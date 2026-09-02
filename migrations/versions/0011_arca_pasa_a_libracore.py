"""La configuración de ARCA pasa a `arca_config` de LibraCore.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-02

`configuracion_arca` era la tabla propia de este producto: el par en columnas
`LargeBinary`, un `ambiente` y un `habilitado` por razón social. Desde acá el
par lo guarda el motor —`arca_config` en la base de LibraCore, los archivos en
`CERTS_DIR`— que es lo que le trae a este producto los **dos pares conviviendo**
y el `ambiente` como selector, sin escribirlos de nuevo.

🔑 **Se puede tirar la tabla en vez de trasladar el par porque no hay ninguno
cargado.** Medido el 2026-09-02 contra las tres instancias: `certificado` y
`clave` están en `NULL` en todas, y de los 742 comprobantes de Suitrans ninguno
tiene CAE. Nunca se subió un par ni se emitió electrónicamente. Esa es la única
razón por la que esta revisión es un `drop_table` y no un traslado de bytes a
archivos.

> ⚠️ Y por eso el `upgrade` **aborta si aparece una fila CON credenciales**. No
> es defensivo por costumbre: lo que hay en esas columnas es una clave privada,
> y borrarla en silencio durante un deploy deja a la instancia sin poder
> facturar sin que nadie se entere hasta el primer comprobante. Si alguna vez
> salta, lo que corresponde es bajar el par por la pantalla vieja y volver a
> subirlo por la nueva — no tocar la migración.

🔴 **La primera versión contaba FILAS, y frenó el deploy de `dev` sobre una fila
vacía.** El router viejo creaba la fila **al abrir la pantalla** —"se crea al
primer uso y no en una migración"— así que cualquier instancia donde alguien
entró una vez a Configuración → ARCA tiene una fila con el par en `NULL`. Contar
filas convertía ese estado, que es el normal, en un deploy abortado, y el
mensaje hablaba de credenciales que no existían. Lo que se protege son las
credenciales, así que eso es lo que se cuenta.
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `certificado IS NOT NULL OR clave IS NOT NULL` y no `count(*)`: una fila
    # con las dos en NULL no tiene nada que perder. Ver el encabezado.
    con_par = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM configuracion_arca "
        "WHERE certificado IS NOT NULL OR clave IS NOT NULL"
    )).scalar_one()
    if con_par:
        raise RuntimeError(
            f"configuracion_arca tiene {con_par} fila(s) CON credenciales de "
            "ARCA y esta revisión las borraría. Descargá el certificado y la "
            "clave antes, y volvé a subirlos por Configuración → ARCA después "
            "de migrar: el par ahora lo guarda LibraCore, no esta tabla."
        )
    op.drop_table("configuracion_arca")
    # Ver el encabezado de la `0006`: Alembic no autogenera el `DROP TYPE`, y
    # sin él el tipo queda huérfano y un `downgrade`/`upgrade` posterior muere
    # con `DuplicateObject`. El test del ciclo completo cuenta los huérfanos.
    op.execute("DROP TYPE IF EXISTS ambiente_arca")


def downgrade() -> None:
    """Vuelve a crear la tabla **vacía**, que es el estado del que salió.

    No repone credenciales: para cuando esta revisión corrió no había ninguna.
    Bajar deja al producto leyendo una tabla vacía, o sea sin ARCA configurado,
    que es exactamente donde estaba antes de todo esto.
    """
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
        sa.CheckConstraint(
            "NOT habilitado OR (certificado IS NOT NULL AND clave IS NOT NULL)",
            name="ck_arca_habilitado_con_credenciales",
        ),
        sa.ForeignKeyConstraint(["razon_social_id"], ["razones_sociales.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("razon_social_id"),
    )
