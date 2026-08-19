"""Las restricciones de forma valen para lo que se carga de ahora en adelante

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19

El perfilado del legado de Suitrans encontró 42 filas que los `CHECK` rechazan y
que **no se pueden adaptar sin inventar un dato**:

- **33 órdenes con origen = destino**: viajes dentro de la misma localidad,
  repartidos en 6 localidades y 3 años. Son reales; el `CHECK` asumía que no
  existían.
- **36 asientos de cuenta corriente con debe y haber en cero**.
- **6 movimientos de caja con importe cero**, con descripción real —"echeq
  5948941", "recibí $7.000.000"— a los que nadie les cargó el importe.

La regla queda condicionada a `origen_legado IS NULL`, o sea: **rige para todo lo
que se carga desde el sistema nuevo, y no para el histórico migrado**, que entra
completo y marcado. No es lo mismo que relajarla: un alta nueva sigue sin poder
salir y llegar al mismo lugar, ni asentar un movimiento que no mueve plata.

> El criterio, escrito en ADR-015: se **adapta la forma** cuando la adaptación no
> cambia el significado —invertir el signo de un asiento, ADR-009— y se **relaja
> la regla** cuando adaptarla exigiría inventar un dato que no está en ningún
> lado. Nunca al revés.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


#: `(tabla, restricción, condición original)`. La nueva es la original con el
#: escape por `origen_legado`.
RESTRICCIONES = [
    ("ordenes_carga", "ck_ordenes_origen_distinto_destino", "origen_id <> destino_id"),
    ("movimientos_cuenta", "ck_cuenta_debe_o_haber",
     "(debe > 0 AND haber = 0) OR (haber > 0 AND debe = 0)"),
    ("movimientos_caja", "ck_caja_importe_positivo", "importe > 0"),
]


def upgrade() -> None:
    for tabla, nombre, condicion in RESTRICCIONES:
        op.drop_constraint(nombre, tabla, type_="check")
        op.create_check_constraint(
            nombre, tabla, f"({condicion}) OR origen_legado IS NOT NULL"
        )


def downgrade() -> None:
    """Vuelve a la regla estricta.

    ⚠️ Falla si hay histórico migrado cargado — y tiene que fallar: revertir la
    migración con los datos adentro dejaría filas que violan la restricción que
    se está reponiendo.
    """
    for tabla, nombre, condicion in RESTRICCIONES:
        op.drop_constraint(nombre, tabla, type_="check")
        op.create_check_constraint(nombre, tabla, condicion)
