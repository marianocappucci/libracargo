"""Completa la provincia de las localidades donde no hay ninguna duda.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-20

El maestro de localidades venía del legado con **la provincia en nulo en las
121 filas**: en el sistema viejo `origen` y `destino` eran dos tablas con una
sola columna de nombre. Con el catálogo de LibraCore ya se puede decir de qué
provincia es cada una — cuando el nombre no es ambiguo.

## Qué toca, y qué no

Sólo escribe donde **el nombre matchea exactamente una localidad del catálogo**,
comparando normalizado (sin acentos, sin puntos de abreviatura). Medido sobre la
instancia del cliente el 2026-08-20:

| | |
|---|---:|
| Provincia completada sin ambigüedad | **63** |
| El nombre existe en 2 o más provincias | **17** |
| Sin match — abreviaturas, duplicados y basura | **41** |

Las 58 que quedan **no se tocan**. Las ambiguas porque elegir por la agencia
sería inventar: `San Pedro` está en ocho provincias y `25 de Mayo` en cuatro.
Las que no matchean porque son abreviaturas (`Cnel. Bogado`, `Gral. Rodriguez`),
duplicados del propio maestro (`Gral Paz` **y** `Gral. Paz`) o entradas que no
son localidades (`Campo`, `Shap`, `(sin nombre)`). Las resuelve una persona
desde la pantalla, que ahora tiene el desplegable.

🔑 **Y sólo escribe donde `provincia IS NULL`.** Una provincia cargada a mano
por alguien vale más que una deducida acá, aunque no coincida.

## Por qué el `downgrade` no deshace

Poner en nulo lo que esta migración escribió borraría también lo que una persona
haya cargado después: no hay forma de distinguirlos. Es una migración de datos
que **agrega información y no destruye ninguna**, así que su reverso correcto es
no hacer nada.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from libracore.geografia import buscar, normalizar

    conexion = op.get_bind()
    filas = conexion.execute(
        sa.text("SELECT id, nombre FROM localidades WHERE provincia IS NULL")
    ).fetchall()

    completadas = ambiguas = sin_match = 0
    for id_, nombre in filas:
        if not nombre or not normalizar(nombre):
            sin_match += 1
            continue
        encontradas = buscar(nombre)
        if len(encontradas) == 1:
            conexion.execute(
                sa.text("UPDATE localidades SET provincia = :provincia WHERE id = :id"),
                {"provincia": encontradas[0]["provincia"], "id": id_},
            )
            completadas += 1
        elif encontradas:
            ambiguas += 1
        else:
            sin_match += 1

    # Se imprime a propósito: es una migración de datos y el número es el
    # resultado. Sin esto, "corrió bien" no distingue haber completado 63 de
    # haber completado ninguna porque el catálogo no estaba.
    print(f"[0005] localidades sin provincia: {len(filas)} — completadas: {completadas}, "
          f"ambiguas: {ambiguas}, sin match: {sin_match}")


def downgrade() -> None:
    """No deshace. Ver el encabezado: no se puede distinguir lo que escribió
    esta migración de lo que cargó una persona después."""
