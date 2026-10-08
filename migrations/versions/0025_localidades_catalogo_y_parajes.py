"""Las localidades se vinculan al catálogo de LibraCore; los parajes son la excepción cargada a mano (ADR-041).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-08

- `localidades.catalogo_id` (código censal, único) y `es_paraje`.
- La unicidad pasa de `nombre` a `(nombre, provincia)`: con el catálogo entran «San Pedro» de Buenos Aires y de
  Jujuy, que son dos lugares.
- **Vincula lo que ya hay**: cada localidad cuyo nombre (y provincia, si la tiene) coincide con **una sola**
  localidad del catálogo queda vinculada, y si no tenía provincia se le completa. Medido en Suitrans: 92 de 120.
  Las demás (partidos, abreviaturas, parajes, nombres del legado como «Campo») quedan sin vincular, para
  revisarlas desde la pantalla. **No se renombra ni se borra nada.**
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def _vincular(con) -> None:
    from libracore import geografia

    provincias = {geografia.normalizar(p["nombre"]): p["id"] for p in geografia.provincias()}
    usados: set[str] = set()
    filas = con.execute(sa.text("SELECT id, nombre, provincia FROM localidades ORDER BY id")).all()
    for id_, nombre, provincia in filas:
        prov_id = provincias.get(geografia.normalizar(provincia)) if provincia else None
        candidatas = geografia.buscar(nombre, prov_id) if prov_id else geografia.buscar(nombre)
        if len(candidatas) != 1 or candidatas[0]["id"] in usados:
            continue
        loc = candidatas[0]
        usados.add(loc["id"])
        con.execute(sa.text(
            "UPDATE localidades SET catalogo_id = :c, provincia = COALESCE(provincia, :p) WHERE id = :i"),
            {"c": loc["id"], "p": loc["provincia"], "i": id_})


def upgrade() -> None:
    op.add_column("localidades", sa.Column("catalogo_id", sa.String(8), nullable=True))
    op.add_column("localidades", sa.Column("es_paraje", sa.Boolean, nullable=False, server_default=sa.false()))
    op.drop_constraint("uq_localidades_nombre", "localidades", type_="unique")
    # `NULLS NOT DISTINCT` (PostgreSQL 15+): dos «Suipacha» sin provincia siguen chocando, como antes.
    op.create_unique_constraint("uq_localidades_nombre_provincia", "localidades", ["nombre", "provincia"],
                                postgresql_nulls_not_distinct=True)
    op.create_unique_constraint("uq_localidades_catalogo", "localidades", ["catalogo_id"])
    _vincular(op.get_bind())


def downgrade() -> None:
    op.drop_constraint("uq_localidades_catalogo", "localidades", type_="unique")
    op.drop_constraint("uq_localidades_nombre_provincia", "localidades", type_="unique")
    op.create_unique_constraint("uq_localidades_nombre", "localidades", ["nombre"])
    op.drop_column("localidades", "es_paraje")
    op.drop_column("localidades", "catalogo_id")
