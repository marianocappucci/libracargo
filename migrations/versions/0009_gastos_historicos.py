"""Los gastos del legado, como documentos.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-21

La pantalla de comprobantes de proveedores abría **vacía** aunque el cliente
tiene 2.799 gastos: entraron en la migración de F6 como **movimientos de
cuenta**, y el documento que los explica no existía. Lo noté el humano al
abrirla.

🔑 **Esta migración no inserta ni un peso.** Crea el documento y le **apunta los
dos asientos que ya están** (`gasto_id`), en vez de asentar de nuevo. Por eso
los saldos no se mueven: no se agrega plata, se le pone nombre a la que ya
estaba. Es la razón por la que la conversión es posible sin tocar el gate de F6.

## De dónde sale el par

Un gasto viejo dejaba dos asientos —`ctacteprov` al debe del proveedor y
`fleteroctacte` al haber del fletero— y **el vínculo entre ellos quedó sólo en
el legado**, en `ctacteprov_fleteroctacte_id`. Está extraído a
`migrations/datos/pares_gastos_legado.json`, que va versionado: adivinar el par
por (fecha, importe) sería una heurística, no una reconstrucción.

## El `CHECK` se relaja para lo migrado, como ADR-015

`ck_gastos_partes_distintas` exigía proveedor ≠ fletero, pensando que el mismo
tercero en las dos partes era un error de carga. En los datos reales pasa **43
veces**. Se condiciona a `origen_legado IS NULL`: rige para toda alta nueva y no
para el histórico, que es el criterio que este repo ya usa.
"""
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CHECK = "ck_gastos_partes_distintas"
PARES = Path(__file__).resolve().parent.parent / "datos" / "pares_gastos_legado.json"


def upgrade() -> None:
    op.add_column("gastos_de_proveedor",
                  sa.Column("origen_legado", sa.String(length=40), nullable=True))
    op.create_index("ix_gastos_origen_legado", "gastos_de_proveedor",
                    ["origen_legado"], unique=True)

    op.drop_constraint(CHECK, "gastos_de_proveedor", type_="check")
    op.create_check_constraint(
        CHECK, "gastos_de_proveedor",
        "proveedor_id <> fletero_id OR origen_legado IS NOT NULL")

    conexion = op.get_bind()
    pares = json.loads(PARES.read_text(encoding="utf-8"))["pares"]

    # Los asientos que ya están, indexados por su origen en el legado.
    filas = conexion.execute(sa.text(
        "SELECT id, origen_legado, tercero_id, fecha, descripcion, concepto, debe, haber "
        "FROM movimientos_cuenta WHERE origen_legado IS NOT NULL")).mappings().all()
    por_origen = {f["origen_legado"]: f for f in filas}

    creados = sin_par = ya_estaba = 0
    for ctacteprov_id, fleteroctacte_id in pares.items():
        proveedor = por_origen.get(f"ctacteprov:{ctacteprov_id}")
        fletero = por_origen.get(f"fleteroctacte:{fleteroctacte_id}")
        # Sin las dos patas no hay documento que crear: dejarlo a medias seria
        # un comprobante que explica una sola cuenta.
        if proveedor is None or fletero is None or proveedor["debe"] <= 0:
            sin_par += 1
            continue

        marca = f"ctacteprov:{ctacteprov_id}"
        if conexion.execute(
            sa.text("SELECT 1 FROM gastos_de_proveedor WHERE origen_legado = :m"),
            {"m": marca},
        ).first():
            ya_estaba += 1
            continue

        nuevo = conexion.execute(sa.text("""
            INSERT INTO gastos_de_proveedor
                (fecha, proveedor_id, fletero_id, comprobante, descripcion, importe,
                 anulado, origen_legado)
            VALUES (:fecha, :proveedor, :fletero, NULL, :descripcion, :importe,
                    false, :marca)
            RETURNING id"""), {
            # La fecha y el importe salen del ASIENTO y no del legado crudo: son
            # los que la migracion de F6 ya normalizo y contra los que cuadro el
            # gate. Tomarlos del dump podria dar un numero distinto al que hoy
            # muestra la cuenta corriente.
            "fecha": proveedor["fecha"],
            "proveedor": proveedor["tercero_id"],
            "fletero": fletero["tercero_id"],
            "descripcion": proveedor["descripcion"] or proveedor["concepto"],
            "importe": proveedor["debe"],
            "marca": marca,
        }).scalar_one()

        conexion.execute(
            sa.text("UPDATE movimientos_cuenta SET gasto_id = :g WHERE id IN (:a, :b)"),
            {"g": nuevo, "a": proveedor["id"], "b": fletero["id"]})
        creados += 1

    # Se imprime porque es una migracion de datos y el numero ES el resultado:
    # "corrio bien" no distingue haber convertido 2.799 de no haber convertido
    # ninguna porque el archivo de pares no estaba en la imagen.
    print(f"[0009] gastos del legado: {len(pares)} pares — creados: {creados}, "
          f"sin asientos: {sin_par}, ya estaban: {ya_estaba}")


def downgrade() -> None:
    conexion = op.get_bind()
    # Primero se sueltan los asientos, que apuntan a los documentos por FK.
    conexion.execute(sa.text(
        "UPDATE movimientos_cuenta SET gasto_id = NULL WHERE gasto_id IN "
        "(SELECT id FROM gastos_de_proveedor WHERE origen_legado IS NOT NULL)"))
    conexion.execute(sa.text(
        "DELETE FROM gastos_de_proveedor WHERE origen_legado IS NOT NULL"))

    op.drop_constraint(CHECK, "gastos_de_proveedor", type_="check")
    op.create_check_constraint(CHECK, "gastos_de_proveedor",
                               "proveedor_id <> fletero_id")
    op.drop_index("ix_gastos_origen_legado", table_name="gastos_de_proveedor")
    op.drop_column("gastos_de_proveedor", "origen_legado")
