"""Paso 4 de F6: perfilado del staging, **antes** de transformar nada.

    python -m migracion.perfilar --origen "postgresql://…/libracargo_staging" \
        > informe-perfilado.md

Esto no arregla nada ni decide nada: mide. La salida es el insumo de las
decisiones de transformación, que se toman una por una y se escriben. "El
criterio del script" no es una decisión: es una decisión que nadie revisó.

Las mediciones salen de la tabla del plan de migración
(`libracargo-diseno-y-migracion`), más tres que aparecieron leyendo el esquema:
el signo de `importe1`/`importe2`, los valores de razón social, y el saldo por
tercero que después es el gate.

> 🔑 **Un id en `0` no es un huérfano.** El legado tiene columnas `int NOT NULL`
> que usan el cero como "ninguno", así que contarlas juntas llenaría el informe
> de un problema que no existe y taparía los huérfanos de verdad. Van separadas.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

import psycopg

#: `(tabla, columna, tabla_destino, columna_destino)` — las relaciones que el
#: legado tiene en la cabeza de quien lo escribió. **No hay una sola clave
#: foránea declarada**, así que todas se asumen rotas hasta que se midan.
RELACIONES = [
    ("orden_carga", "carga_cliente_id", "clientes", "cliente_id"),
    ("orden_carga", "carga_origen_id", "origen", "origen_id"),
    ("orden_carga", "carga_destino_id", "destino", "destino_id"),
    ("orden_carga", "carga_fletero_id", "fleteros", "fletero_id"),
    ("orden_carga", "carga_chofer_id", "choferes", "chofer_id"),
    ("choferes", "chofer_flete_id", "fleteros", "fletero_id"),
    ("facturas", "factura_cliente_id", "clientes", "cliente_id"),
    ("clientectacte", "clientectacte_cliente_id", "clientes", "cliente_id"),
    ("clientectacte", "clientectacte_carga_id", "orden_carga", "carga_id"),
    ("clientectacte", "clientectacte_novedad_id", "novedades", "novedad_id"),
    ("fleteroctacte", "fletectacte_fletero_id", "fleteros", "fletero_id"),
    ("fleteroctacte", "fletectacte_carga_id", "orden_carga", "carga_id"),
    ("fleteroctacte", "fletectacte_novedad_id", "novedades", "novedad_id"),
    ("ctacteprov", "ctacteprov_proveedor_id", "proveedores", "proveedor_id"),
    ("ctacteprov", "ctacteprov_fletero_id", "fleteros", "fletero_id"),
    ("ctacteprov", "ctacteprov_novedad_id", "novedades", "novedad_id"),
    ("ctacteprov", "ctacteprov_fleteroctacte_id", "fleteroctacte", "fletectacte_id"),
    ("novedades", "novedad_cliente_id", "clientes", "cliente_id"),
    ("novedades", "novedad_fletero_id", "fleteros", "fletero_id"),
    ("novedades", "novedad_proveedor_id", "proveedores", "proveedor_id"),
    ("sucesos", "sucesos_ordencarga", "orden_carga", "carga_id"),
    ("sucesos", "sucesos_novedades", "novedades", "novedad_id"),
]

#: Las tres cuentas corrientes, con la columna que identifica al tercero.
CUENTAS = [
    ("clientectacte", "clientectacte_cliente_id", "clientectacte_importe1",
     "clientectacte_importe2", "clientes", "cliente_id", "cliente_razonsocial"),
    ("fleteroctacte", "fletectacte_fletero_id", "fletectacte_importe1",
     "fletectacte_importe2", "fleteros", "fletero_id", "fletero_razonsocial"),
    ("ctacteprov", "ctacteprov_proveedor_id", "ctacteprov_importe1",
     "ctacteprov_importe2", "proveedores", "proveedor_id", "proveedor_razonsocial"),
]

#: Los 15 importes: `(tabla, columna)`. La columna sombra es `<columna>_crudo`.
IMPORTES = [
    ("orden_carga", "carga_importe"), ("orden_carga", "carga_iva"),
    ("orden_carga", "carga_total"), ("orden_carga", "carga_comision"),
    ("facturas", "factura_neto"), ("facturas", "factura_iva"),
    ("facturas", "factura_total"),
    ("clientectacte", "clientectacte_importe1"), ("clientectacte", "clientectacte_importe2"),
    ("fleteroctacte", "fletectacte_importe1"), ("fleteroctacte", "fletectacte_importe2"),
    ("ctacteprov", "ctacteprov_importe1"), ("ctacteprov", "ctacteprov_importe2"),
    ("novedades", "novedad_importe1"), ("novedades", "novedad_importe2"),
]

#: Un id "presente": ni nulo, ni vacío, ni el cero que el legado usa como nada.
PRESENTE = "{col} IS NOT NULL AND {col} <> '' AND {col} <> '0'"

#: Texto que parece un número. Todo es `TEXT` en el espejo, así que cualquier
#: `::numeric` sin guarda revienta con la primera fila rara — que es justo la
#: fila que hay que poder contar.
NUMERICO = r"{col} ~ '^-?[0-9]+(\.[0-9]+)?$'"


def _uno(con, sql: str, parametros=None):
    # Sin parámetros se pasa None y no una tupla vacía: con una tupla, psycopg
    # interpreta el SQL como plantilla, y una condición con LIKE '0000-00-00%'
    # revienta con "only '%s' are allowed as placeholders".
    return con.execute(sql, parametros).fetchone()[0]


def conteos(con) -> str:
    filas = []
    for (tabla,) in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'legado' ORDER BY table_name").fetchall():
        filas.append((tabla, _uno(con, f"SELECT count(*) FROM legado.{tabla}")))
    cuerpo = "\n".join(f"| `{t}` | {c:,} |".replace(",", ".") for t, c in filas)
    total = sum(c for _, c in filas)
    return ("## Conteos por tabla\n\n| Tabla | Filas |\n|---|---:|\n"
            f"{cuerpo}\n| **total** | **{total:,}** |".replace(",", ".") + "\n")


def huerfanos(con) -> str:
    filas = []
    for tabla, col, destino, col_destino in RELACIONES:
        total = _uno(con, f"SELECT count(*) FROM legado.{tabla}")
        presente = PRESENTE.format(col=col)
        con_ref = _uno(con, f"SELECT count(*) FROM legado.{tabla} WHERE {presente}")
        sueltos = _uno(con, f"""
            SELECT count(*) FROM legado.{tabla} o
            WHERE {presente}
              AND NOT EXISTS (SELECT 1 FROM legado.{destino} d
                              WHERE d.{col_destino} = o.{col})""")
        marca = "🔴 " if sueltos else ""
        filas.append(f"| `{tabla}.{col}` → `{destino}` | {total} | {total - con_ref} | "
                     f"{marca}{sueltos} |")
    return ("## Huérfanos por relación implícita\n\n"
            "El legado no declara **ninguna** clave foránea. `sin referencia` son "
            "los nulos, vacíos y ceros —el cero es el \"ninguno\" del legado, no un "
            "error—; `huérfanos` son los que apuntan a un id que no existe.\n\n"
            "| Relación | Filas | Sin referencia | Huérfanos |\n|---|---:|---:|---:|\n"
            + "\n".join(filas) + "\n")


def truncados(con) -> str:
    """Las columnas `varchar(50)` que guardan una cadena concatenada.

    `fletectacte_tipo_mov` no guarda un tipo de movimiento: guarda
    `"origen - destino - cantidad - tipo - remito"`. MySQL la corta a 50 en
    silencio, así que un largo de exactamente 50 es la marca de que se perdió el
    final.
    """
    filas = []
    for tabla, col, largo in [
        ("fleteroctacte", "fletectacte_tipo_mov", 50),
        ("clientectacte", "clientectacte_tipo_mov", 50),
        ("clientectacte", "clientectacte_descripcion", 50),
        ("novedades", "novedad_descripcion", 50),
        ("ctacteprov", "ctacteprov_descripcion", 110),
    ]:
        total = _uno(con, f"SELECT count(*) FROM legado.{tabla} WHERE {col} IS NOT NULL")
        al_tope = _uno(con, f"SELECT count(*) FROM legado.{tabla} "
                            f"WHERE length({col}) = {largo}")
        pct = f"{al_tope * 100 / total:.1f}%" if total else "—"
        filas.append(f"| `{tabla}.{col}` | {largo} | {total} | "
                     f"{'🔴 ' if al_tope else ''}{al_tope} | {pct} |")
    return ("## Texto cortado por el límite de la columna\n\n"
            "Un largo **exactamente igual** al de la columna es la firma del "
            "truncamiento silencioso de MySQL.\n\n"
            "| Columna | Límite | No nulos | Al tope | |\n|---|---:|---:|---:|---:|\n"
            + "\n".join(filas) + "\n")


def cantidades(con) -> str:
    """`carga_cantidad` es `varchar(20)`: hay que ver qué entró en 4.337 filas."""
    numerico = NUMERICO.format(col="carga_cantidad")
    total = _uno(con, "SELECT count(*) FROM legado.orden_carga")
    vacias = _uno(con, "SELECT count(*) FROM legado.orden_carga "
                       "WHERE carga_cantidad IS NULL OR carga_cantidad = ''")
    numericas = _uno(con, f"SELECT count(*) FROM legado.orden_carga WHERE {numerico}")
    raras = total - vacias - numericas
    ejemplos = con.execute(
        f"SELECT carga_cantidad, count(*) FROM legado.orden_carga "
        f"WHERE carga_cantidad IS NOT NULL AND carga_cantidad <> '' AND NOT ({numerico}) "
        "GROUP BY carga_cantidad ORDER BY count(*) DESC LIMIT 15").fetchall()
    listado = "\n".join(f"| `{v}` | {c} |" for v, c in ejemplos) or "| — | — |"
    return (f"## `orden_carga.carga_cantidad` — texto libre\n\n"
            f"- Filas: **{total}**\n- Vacías o nulas: **{vacias}**\n"
            f"- Numéricas puras: **{numericas}**\n"
            f"- {'🔴 ' if raras else ''}Con algo más (unidad pegada, rangos, texto): "
            f"**{raras}**\n\n"
            "Los 15 valores no numéricos más frecuentes — de acá sale el criterio "
            "para separar `cantidad` de `unidad`, y qué va a `cantidad_legado`:\n\n"
            f"| Valor | Veces |\n|---|---:|\n{listado}\n")


def cuits(con) -> str:
    """CUITs repetidos entre los tres maestros — insumo del reporte de fusión.

    🔴 La migración **no deduplica**: los 276 registros entran como 276 terceros.
    Esto se mide para el reporte asistido posterior, que una persona aprueba de a
    uno. Fusionar durante la carga rompe las tres cuentas corrientes.
    """
    con.execute("""
        CREATE OR REPLACE TEMP VIEW todos_los_cuits AS
        SELECT 'cliente' AS rol, cliente_id AS id, cliente_cuit AS cuit,
               cliente_razonsocial AS nombre FROM legado.clientes
        UNION ALL SELECT 'fletero', fletero_id, fletero_cuit, fletero_razonsocial
                  FROM legado.fleteros
        UNION ALL SELECT 'proveedor', proveedor_id, proveedor_cuit, proveedor_razonsocial
                  FROM legado.proveedores""")
    normalizado = "regexp_replace(cuit, '[^0-9]', '', 'g')"
    total = _uno(con, "SELECT count(*) FROM todos_los_cuits")
    sin_cuit = _uno(con, f"SELECT count(*) FROM todos_los_cuits "
                         f"WHERE cuit IS NULL OR {normalizado} = ''")
    grupos = con.execute(f"""
        SELECT {normalizado} AS cuit, count(*) AS veces,
               string_agg(rol || ' #' || id, ', ' ORDER BY rol, id) AS quienes
        FROM todos_los_cuits
        WHERE cuit IS NOT NULL AND length({normalizado}) >= 10
        GROUP BY 1 HAVING count(*) > 1 ORDER BY 2 DESC, 1""").fetchall()
    listado = "\n".join(f"| `{c}` | {v} | {q} |" for c, v, q in grupos) or "| — | — | — |"
    return (f"## CUITs repetidos entre maestros\n\n"
            f"- Registros en los tres maestros: **{total}**\n"
            f"- Sin CUIT utilizable: **{sin_cuit}**\n"
            f"- CUITs que aparecen más de una vez: **{len(grupos)}**\n\n"
            "La migración **no fusiona**: esto es el insumo del reporte asistido "
            "posterior, que una persona aprueba de a uno.\n\n"
            f"| CUIT | Veces | Quiénes |\n|---|---:|---|\n{listado}\n")


def fechas(con) -> str:
    """`date NOT NULL` de MySQL admite `0000-00-00`, y eso no entra en PostgreSQL."""
    filas = []
    for tabla, col in [("orden_carga", "carga_fecha"), ("facturas", "factura_fecha"),
                       ("clientectacte", "clientectacte_fecha"),
                       ("fleteroctacte", "fletectacte_fecha"),
                       ("ctacteprov", "ctacteprov_fecha"),
                       ("novedades", "novedad_fecha"), ("sucesos", "sucesos_fecha")]:
        total = _uno(con, f"SELECT count(*) FROM legado.{tabla}")
        nulas = _uno(con, f"SELECT count(*) FROM legado.{tabla} "
                          f"WHERE {col} IS NULL OR {col} = ''")
        ceros = _uno(con, f"SELECT count(*) FROM legado.{tabla} "
                          f"WHERE {col} LIKE '0000-00-00%'")
        rango = con.execute(
            f"SELECT min({col}), max({col}) FROM legado.{tabla} "
            f"WHERE {col} > '0001-01-01'").fetchone()
        marca = "🔴 " if (nulas or ceros) else ""
        filas.append(f"| `{tabla}.{col}` | {total} | {marca}{nulas} | {marca}{ceros} | "
                     f"{rango[0] or '—'} → {rango[1] or '—'} |")
    return ("## Fechas\n\n| Columna | Filas | Nulas/vacías | `0000-00-00` | Rango real |\n"
            "|---|---:|---:|---:|---|\n" + "\n".join(filas) + "\n")


def perdida_del_float(con) -> str:
    """Cuánto se aparta el `float(10,2)` de lo que el sistema muestra.

    Cada importe entró dos veces: `x` es el valor formateado a 2 decimales —lo
    que el sistema viejo imprime— y `x_crudo` es el mismo `float` casteado a
    `DECIMAL(20,6)`, o sea lo que hay adentro. Para `1234567.89` eso da
    `1234567.88` y `1234567.875`.

    **La diferencia no se puede corregir**: lo que la persona tipeó en 2021 no
    está en ningún lado. Se mide para poder explicarla en el reporte del gate.
    """
    filas = []
    total_desvio = Decimal(0)
    for tabla, col in IMPORTES:
        crudo = f"{col}_crudo"
        guarda = f"{NUMERICO.format(col=col)} AND {NUMERICO.format(col=crudo)}"
        no_nulos = _uno(con, f"SELECT count(*) FROM legado.{tabla} WHERE {guarda}")
        distintos = _uno(con, f"""
            SELECT count(*) FROM legado.{tabla}
            WHERE {guarda} AND {col}::numeric <> {crudo}::numeric""")
        desvio = _uno(con, f"""
            SELECT coalesce(sum(abs({col}::numeric - {crudo}::numeric)), 0)
            FROM legado.{tabla} WHERE {guarda}""")
        total_desvio += Decimal(desvio)
        pct = f"{distintos * 100 / no_nulos:.1f}%" if no_nulos else "—"
        filas.append(f"| `{tabla}.{col}` | {no_nulos} | {distintos} | {pct} | {desvio} |")
    return ("## Pérdida del `float(10,2)`\n\n"
            "`float` de MySQL es **precisión simple**: no hace falta sumar para "
            "perder plata. La columna `_crudo` es lo que hay adentro del float; la "
            "otra, lo que el sistema muestra.\n\n"
            "| Importe | Con valor | Difieren | | Desvío acumulado |\n"
            "|---|---:|---:|---:|---:|\n" + "\n".join(filas) +
            f"\n\n**Desvío total sobre los 15 importes: {total_desvio}**\n")


def signo_de_los_importes(con) -> str:
    """¿`importe1` e `importe2` son debe y haber?

    El relevamiento dice "casi seguro". Esto lo mide: si fueran debe y haber,
    casi ninguna fila tendría los dos con valor a la vez.
    """
    filas = []
    for tabla, _, imp1, imp2, *_ in CUENTAS:
        def positivo(col):
            return f"({NUMERICO.format(col=col)} AND {col}::numeric <> 0)"
        total = _uno(con, f"SELECT count(*) FROM legado.{tabla}")
        solo1 = _uno(con, f"SELECT count(*) FROM legado.{tabla} "
                          f"WHERE {positivo(imp1)} AND NOT {positivo(imp2)}")
        solo2 = _uno(con, f"SELECT count(*) FROM legado.{tabla} "
                          f"WHERE {positivo(imp2)} AND NOT {positivo(imp1)}")
        ambos = _uno(con, f"SELECT count(*) FROM legado.{tabla} "
                          f"WHERE {positivo(imp1)} AND {positivo(imp2)}")
        negativos = _uno(con, f"""
            SELECT count(*) FROM legado.{tabla}
            WHERE ({NUMERICO.format(col=imp1)} AND {imp1}::numeric < 0)
               OR ({NUMERICO.format(col=imp2)} AND {imp2}::numeric < 0)""")
        filas.append(f"| `{tabla}` | {total} | {solo1} | {solo2} | "
                     f"{'🔴 ' if ambos else ''}{ambos} | "
                     f"{'🔴 ' if negativos else ''}{negativos} |")
    return ("## `importe1` / `importe2` — ¿debe y haber?\n\n"
            "Si lo fueran, un asiento movería una columna **o** la otra. Las filas "
            "con las dos, y las de importe negativo, son las que rompen esa lectura "
            "— y el modelo nuevo tiene un `CHECK` que no las va a dejar entrar.\n\n"
            "| Tabla | Filas | Sólo `importe1` | Sólo `importe2` | Las dos | Negativos |\n"
            "|---|---:|---:|---:|---:|---:|\n" + "\n".join(filas) + "\n")


def razones_sociales(con) -> str:
    """Los enteros sin tabla: `carga_razonsocial` y `factura_razonsocial`."""
    def distintos(tabla, col):
        return con.execute(
            f"SELECT coalesce({col}, '(nulo)'), count(*) FROM legado.{tabla} "
            f"GROUP BY 1 ORDER BY 2 DESC").fetchall()
    ordenes = "\n".join(f"| `orden_carga.carga_razonsocial` | `{v}` | {c} |"
                        for v, c in distintos("orden_carga", "carga_razonsocial"))
    facturas = "\n".join(f"| `facturas.factura_razonsocial` | `{v}` | {c} |"
                         for v, c in distintos("facturas", "factura_razonsocial"))
    # El cruce que en el sistema nuevo es el gate de F5: la orden facturada y su
    # factura tienen que decir la misma razón social.
    discrepan = _uno(con, """
        SELECT count(*) FROM legado.orden_carga o
        JOIN legado.facturas f ON f.factura_nro = o.carga_factura
         AND f.factura_razonsocial = o.carga_razonsocial
        WHERE o.carga_razonsocial IS DISTINCT FROM f.factura_razonsocial""")
    sin_factura = _uno(con, """
        SELECT count(*) FROM legado.orden_carga o
        WHERE o.carga_facturado = '1'
          AND NOT EXISTS (SELECT 1 FROM legado.facturas f
                          WHERE f.factura_nro = o.carga_factura
                            AND f.factura_razonsocial = o.carga_razonsocial)""")
    return ("## Razón social — los enteros sin tabla\n\n"
            "En el legado son un `<select>` de HTML: `1 = Suitrans`, `2 = Mauricio`, "
            "y un `0` que usa `bajarpendientes.php`. Cada valor distinto que aparezca "
            "acá necesita una fila en `razones_sociales` antes de migrar.\n\n"
            f"| Columna | Valor | Filas |\n|---|---|---:|\n{ordenes}\n{facturas}\n\n"
            f"- Órdenes marcadas como facturadas **sin factura que las respalde**: "
            f"{'🔴 ' if sin_factura else ''}**{sin_factura}** — cada una es una orden "
            "que el sistema nuevo no puede poner en `facturada`, porque el `CHECK` "
            "exige comprobante.\n"
            f"- Órdenes cuya razón social discrepa de la de su factura: **{discrepan}**\n")


def saldos(con) -> str:
    """El saldo viejo por tercero — el insumo del gate de F6.

    Se calcula **como lo calcula el legado**: sumando las dos columnas de la
    cuenta. No es el saldo definitivo de nadie; es el número contra el que se
    compara el del sistema nuevo, tercero por tercero.
    """
    partes = []
    for tabla, col_id, imp1, imp2, maestro, id_maestro, nombre in CUENTAS:
        filas = con.execute(f"""
            SELECT c.{col_id} AS id, m.{nombre} AS nombre, count(*) AS movimientos,
                   sum(CASE WHEN {NUMERICO.format(col=f'c.{imp1}')}
                            THEN c.{imp1}::numeric ELSE 0 END)
                 - sum(CASE WHEN {NUMERICO.format(col=f'c.{imp2}')}
                            THEN c.{imp2}::numeric ELSE 0 END) AS saldo
            FROM legado.{tabla} c
            LEFT JOIN legado.{maestro} m ON m.{id_maestro} = c.{col_id}
            GROUP BY 1, 2 ORDER BY abs(
                   sum(CASE WHEN {NUMERICO.format(col=f'c.{imp1}')}
                            THEN c.{imp1}::numeric ELSE 0 END)
                 - sum(CASE WHEN {NUMERICO.format(col=f'c.{imp2}')}
                            THEN c.{imp2}::numeric ELSE 0 END)) DESC""").fetchall()
        total = sum(f[3] or 0 for f in filas)
        cuerpo = "\n".join(
            f"| {i} | {n or '🔴 sin maestro'} | {mov} | {s} |" for i, n, mov, s in filas[:20])
        partes.append(
            f"### `{tabla}` — {len(filas)} cuentas, saldo total {total}\n\n"
            f"Las 20 de mayor saldo absoluto:\n\n"
            f"| Id | Tercero | Movimientos | Saldo viejo |\n|---|---|---:|---:|\n{cuerpo}\n")
    return ("## Saldo por tercero, calculado como lo calcula el legado\n\n"
            "Es el lado izquierdo del gate de F6: contra esto se compara el saldo "
            "del sistema nuevo, tercero por tercero. **Van a diferir** —el `float` "
            "de precisión simple ya perdió plata en 2021— y el entregable es el "
            "reporte de esas diferencias, validado por el cliente.\n\n"
            + "\n".join(partes))


SECCIONES = [conteos, huerfanos, fechas, truncados, cantidades, cuits,
             perdida_del_float, signo_de_los_importes, razones_sociales, saldos]


def informe(con) -> str:
    partes = ["# Perfilado del legado de Suitrans\n",
              "Generado por `migracion/perfilar.py` sobre el staging. **Mide, no "
              "arregla**: cada caso raro que aparezca acá se decide y se documenta "
              "antes de transformar nada.\n"]
    partes += [seccion(con) for seccion in SECCIONES]
    return "\n".join(partes)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Perfila el staging del legado")
    p.add_argument("--origen", required=True, help="URL del PostgreSQL de staging")
    p.add_argument("--salida", help="archivo .md (por defecto, la salida estándar)")
    args = p.parse_args(argv)

    with psycopg.connect(args.origen) as con:
        texto = informe(con)
    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"informe en {args.salida}")
    else:
        print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
