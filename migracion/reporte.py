"""Paso 6 de F6: el reporte de diferencias — **el gate de la migración**.

    python -m migracion.reporte \
        --legado "postgresql://…/libracargo_staging" \
        --nuevo  "postgresql://…/libracargo_migrado" \
        --salida reporte-diferencias.md

Compara, **tercero por tercero**, el saldo que da el sistema viejo contra el que
da el sistema nuevo. Los conteos por tabla también, pero el gate es el saldo: una
migración puede tener los 52.615 registros y estar mal.

> 🔴 **Que difieran no es un fallo de la migración.** El `float(10,2)` del legado
> es de precisión simple y ya perdió plata en 2021 — el perfilado midió **$83,68**
> de desvío acumulado sobre los 15 importes. Lo que este reporte tiene que
> mostrar es que la diferencia **se explica por eso y no por otra cosa**: si
> apareciera un tercero con una diferencia de otro orden de magnitud, el problema
> es la migración.
>
> El entregable es este reporte **validado por el cliente**, no un número que
> cuadre a la fuerza.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

import psycopg

CERO = Decimal("0.00")

#: `(tabla del legado, columna del tercero, debe, haber, rol)`. El saldo viejo se
#: calcula **como lo calcula el legado**: sumando las dos columnas, sin tocar el
#: signo. Si se aplicara acá la normalización de ADR-009, los dos lados harían la
#: misma cuenta y el reporte no compararía nada.
CUENTAS = [
    ("clientectacte", "clientectacte_cliente_id", "clientectacte_importe1",
     "clientectacte_importe2", "cliente"),
    ("fleteroctacte", "fletectacte_fletero_id", "fletectacte_importe1",
     "fletectacte_importe2", "fletero"),
    ("ctacteprov", "ctacteprov_proveedor_id", "ctacteprov_importe1",
     "ctacteprov_importe2", "proveedor"),
]

NUMERICO = r"{col} ~ '^-?[0-9]+(\.[0-9]+)?$'"

#: Conteos que tienen que dar igual de los dos lados. `sucesos` → `auditoria` y
#: las tres cuentas → una sola tabla, así que la comparación es por suma.
EQUIVALENCIAS = [
    ("terceros", ["clientes", "fleteros", "proveedores"], "terceros"),
    ("choferes", ["choferes"], "choferes"),
    ("órdenes de carga", ["orden_carga"], "ordenes_carga"),
    ("movimientos de caja", ["novedades"], "movimientos_caja"),
    ("movimientos de cuenta", ["clientectacte", "fleteroctacte", "ctacteprov"],
     "movimientos_cuenta"),
    ("auditoría", ["sucesos"], "auditoria"),
]


def saldos_viejos(legado) -> dict[tuple[str, str], tuple[Decimal, int]]:
    """`{(rol, id_legado): (saldo, movimientos)}`, calculado como el legado."""
    salida = {}
    for tabla, columna, imp1, imp2, rol in CUENTAS:
        filas = legado.execute(f"""
            SELECT {columna}, count(*),
                   sum(CASE WHEN {NUMERICO.format(col=imp1)} THEN {imp1}::numeric ELSE 0 END)
                 - sum(CASE WHEN {NUMERICO.format(col=imp2)} THEN {imp2}::numeric ELSE 0 END)
            FROM legado.{tabla} GROUP BY 1""").fetchall()
        for id_legado, movimientos, saldo in filas:
            salida[(rol, id_legado)] = (Decimal(saldo or 0).quantize(CERO), movimientos)
    return salida


def saldos_nuevos(nuevo) -> dict[tuple[str, str], tuple[Decimal, int, str]]:
    """Lo mismo desde el sistema migrado, con la clave del legado en la mano.

    Se agrupa por `(tercero, rol)` —la cuenta del modelo nuevo— y se traduce al
    id viejo por `origen_legado`, que es justamente para lo que existe esa
    columna.
    """
    filas = nuevo.execute("""
        SELECT t.origen_legado, m.rol::text, count(*),
               coalesce(sum(m.debe), 0) - coalesce(sum(m.haber), 0), t.razon_social
        FROM movimientos_cuenta m
        JOIN terceros t ON t.id = m.tercero_id
        GROUP BY 1, 2, 5""").fetchall()
    salida = {}
    for origen_legado, rol, movimientos, saldo, nombre in filas:
        _, id_legado = (origen_legado or ":").split(":", 1)
        salida[(rol, id_legado)] = (Decimal(saldo).quantize(CERO), movimientos, nombre)
    return salida


def saldos_por_el_float(legado) -> dict[tuple[str, str], Decimal]:
    """El mismo saldo viejo, pero sumando lo que hay **adentro** del `float`.

    Las columnas `_crudo` del staging son cada importe casteado a
    `DECIMAL(20,6)`: lo que el `float(10,2)` guarda de verdad, contra lo que la
    pantalla del legado muestra redondeado a dos decimales.
    """
    salida = {}
    for tabla, columna, imp1, imp2, rol in CUENTAS:
        filas = legado.execute(f"""
            SELECT {columna},
                   sum(CASE WHEN {NUMERICO.format(col=imp1 + '_crudo')}
                            THEN {imp1}_crudo::numeric ELSE 0 END)
                 - sum(CASE WHEN {NUMERICO.format(col=imp2 + '_crudo')}
                            THEN {imp2}_crudo::numeric ELSE 0 END)
            FROM legado.{tabla} GROUP BY 1""").fetchall()
        for id_legado, saldo in filas:
            salida[(rol, id_legado)] = Decimal(saldo or 0)
    return salida


def perdida_del_float(legado) -> str:
    """La otra diferencia: lo que el legado muestra contra lo que el legado suma.

    🔑 **Ésta es la que el cliente puede llegar a ver**, y no aparece en la tabla
    de arriba. La migración copia los importes **como los muestra** el sistema
    viejo, así que contra esa lectura da cero. Pero el PHP viejo suma los `float`
    directamente en MySQL, y un `float` de precisión simple no guarda lo que
    muestra: sumar 22.645 de esos no da lo mismo que sumar lo que se ve en
    pantalla.

    No hay nada que corregir —lo que la persona tipeó en 2021 no está en ningún
    lado— pero el número tiene que estar escrito antes de que alguien lo
    encuentre solo.
    """
    mostrado, adentro = saldos_viejos(legado), saldos_por_el_float(legado)
    filas, total = [], CERO
    for clave, (saldo_mostrado, _) in sorted(mostrado.items()):
        saldo_float = adentro.get(clave, CERO)
        diferencia = (saldo_mostrado - saldo_float).quantize(Decimal("0.000001"))
        total += diferencia
        if abs(diferencia) >= Decimal("0.005"):
            filas.append((abs(diferencia), clave, saldo_mostrado, saldo_float, diferencia))
    filas.sort(reverse=True)
    cuerpo = "\n".join(
        f"| {rol} | {id_legado} | {mostrado_} | {float_} | **{dif}** |"
        for _, (rol, id_legado), mostrado_, float_, dif in filas[:15]) or "| — | — | — | — | — |"
    return (
        "## La otra diferencia: lo que el legado muestra contra lo que el legado suma\n\n"
        "La tabla de arriba compara contra los importes **como los muestra** el "
        "sistema viejo. Pero el PHP suma los `float` en MySQL, y un `float` de "
        "precisión simple no guarda lo que muestra. Esta es la brecha entre las dos "
        "lecturas del **mismo** sistema viejo — no la mete la migración, ya estaba.\n\n"
        f"- Cuentas donde la brecha llega a un centavo: **{len(filas)}**\n"
        f"- Brecha total: **{total.quantize(Decimal('0.000001'))}**\n\n"
        "Las 15 más grandes:\n\n"
        "| Rol | Id viejo | Saldo como se muestra | Saldo sumando los float | Brecha |\n"
        "|---|---:|---:|---:|---:|\n" + cuerpo + "\n")


def conteos(legado, nuevo) -> tuple[str, bool]:
    filas, todo_bien = [], True
    for etiqueta, tablas_viejas, tabla_nueva in EQUIVALENCIAS:
        viejo = sum(
            legado.execute(f"SELECT count(*) FROM legado.{t}").fetchone()[0]
            for t in tablas_viejas)
        actual = nuevo.execute(f"SELECT count(*) FROM {tabla_nueva}").fetchone()[0]
        coincide = viejo == actual
        todo_bien &= coincide
        filas.append(f"| {etiqueta} | {' + '.join(tablas_viejas)} | {viejo} | {actual} | "
                     f"{'✅' if coincide else '🔴'} |")
    return ("## Conteos\n\n| Qué | Tablas del legado | Legado | Migrado | |\n"
            "|---|---|---:|---:|---:|\n" + "\n".join(filas) + "\n", todo_bien)


def diferencias(legado, nuevo) -> tuple[str, bool]:
    viejos, actuales = saldos_viejos(legado), saldos_nuevos(nuevo)
    claves = sorted(set(viejos) | set(actuales))

    filas, peor, suma_dif, cuentas_con_dif = [], CERO, CERO, 0
    faltantes = []
    for clave in claves:
        rol, id_legado = clave
        viejo, movimientos_viejos = viejos.get(clave, (CERO, 0))
        actual, movimientos_nuevos, nombre = actuales.get(clave, (CERO, 0, "—"))
        if clave not in actuales or clave not in viejos:
            faltantes.append(f"{rol} #{id_legado}")
        diferencia = actual - viejo
        suma_dif += diferencia
        if diferencia or movimientos_viejos != movimientos_nuevos:
            cuentas_con_dif += 1
            peor = max(peor, abs(diferencia))
            filas.append(
                f"| {rol} | {id_legado} | {nombre} | {movimientos_viejos} | "
                f"{movimientos_nuevos} | {viejo} | {actual} | **{diferencia}** |")

    cuerpo = "\n".join(filas) or "| — | — | — | — | — | — | — | — |"
    limpio = not faltantes and peor <= Decimal("1.00")
    encabezado = (
        f"## Saldo por tercero\n\n"
        f"- Cuentas comparadas: **{len(claves)}**\n"
        f"- Cuentas con alguna diferencia: **{cuentas_con_dif}**\n"
        f"- Diferencia acumulada: **{suma_dif}**\n"
        f"- Mayor diferencia en una cuenta: **{peor}**\n"
        f"- Cuentas que están de un solo lado: "
        f"{'🔴 ' + ', '.join(faltantes) if faltantes else '**ninguna**'}\n\n")
    if peor > Decimal("1.00"):
        encabezado += (
            "🔴 **Hay una cuenta que difiere en más de un peso.** El desvío del "
            "`float` medido en el perfilado es de $83,68 repartido en 52.615 "
            "filas: una diferencia de este tamaño en una sola cuenta no se "
            "explica por ahí. Revisar antes de dar la migración por buena.\n\n")
    return (encabezado +
            "| Rol | Id viejo | Tercero | Mov. viejos | Mov. nuevos | Saldo viejo | "
            "Saldo nuevo | Diferencia |\n|---|---:|---|---:|---:|---:|---:|---:|\n"
            + cuerpo + "\n", limpio)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Reporte de diferencias de la migración")
    p.add_argument("--legado", required=True)
    p.add_argument("--nuevo", required=True)
    p.add_argument("--salida")
    args = p.parse_args(argv)

    with psycopg.connect(args.legado) as legado, psycopg.connect(args.nuevo) as nuevo:
        tabla_conteos, conteos_ok = conteos(legado, nuevo)
        tabla_saldos, saldos_ok = diferencias(legado, nuevo)
        tabla_float = perdida_del_float(legado)

    texto = "\n".join([
        "# Reporte de diferencias — migración de Suitrans a LibraCargo\n",
        "Comparación **tercero por tercero** entre el saldo que da el sistema "
        "viejo y el que da el migrado. Los saldos viejos se calculan como los "
        "calcula el legado —sumando las dos columnas, sin tocar el signo—, así "
        "que los dos lados no comparten la cuenta.\n",
        "> Este reporte es el **gate de F6**: lo que cierra la migración es que "
        "el cliente lo valide, no que los números den cero.\n",
        tabla_conteos, tabla_saldos, tabla_float,
    ])
    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"reporte en {args.salida}")
    else:
        print(texto)
    return 0 if (conteos_ok and saldos_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
