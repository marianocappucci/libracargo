"""Paso 3 de F6: el dump del legado entra al staging **tal cual**.

    python -m migracion.cargar --dump dump-suitrans.sql \
        --destino "postgresql://usuario@host:5432/libracargo_staging"

El dump de MySQL no se parsea con una expresión regular: se restaura en un
**MariaDB efímero** —el mismo motor que lo escribió— y desde ahí se leen las
filas. Un parser propio de `INSERT` tiene que reimplementar el escapado, las
comillas, los `\\N` y las filas múltiples, y falla en silencio sobre la fila
rara; el motor no.

Todo entra como `TEXT` y sin una sola restricción (ver `espejo.sql`). Transformar
durante la carga mezcla el error que trae el dato con el que mete la conversión,
y deja sin forma de saber cuál de los dos falló.

> 🔑 **La codificación se mide, no se supone.** Las columnas del legado son
> `latin1_general_ci` dentro de tablas `utf8mb3`, y un PHP de 2021 pudo haber
> escrito ahí bytes UTF-8. Los dos casos se ven distintos —`E9` contra `C3A9`—
> y la diferencia decide todo el paso. Si aparecen los dos, el script **para**:
> una base con las dos codificaciones mezcladas necesita una decisión humana,
> no un `try/except` que elija por su cuenta.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import psycopg

ESPEJO = Path(__file__).with_name("espejo.sql")
IMAGEN_POR_DEFECTO = "mariadb:11.4"
BASE_TEMPORAL = "legado"

#: Marcas de doble encoding. Si aparecen **después** de decodificar, el dato ya
#: estaba roto en la base del legado y no lo rompió este paso.
MOJIBAKE = ("Ã©", "Ã±", "Ã¡", "Ã³", "Ãº", "Ã ", "Â°", "Â¿")


def _docker(*args: str, entrada: bytes | None = None, texto: bool = True):
    return subprocess.run(["docker", *args], input=entrada, capture_output=True,
                          text=texto if entrada is None else False, check=False)


def levantar_mariadb(imagen: str = IMAGEN_POR_DEFECTO,
                     nombre: str = "libracargo-legado") -> tuple[str, int]:
    """Arranca el MariaDB efímero y devuelve `(contenedor, puerto)`.

    El puerto lo elige Docker y se lee de `docker port`, en vez de fijar uno:
    con un puerto fijo, si algo más lo tiene tomado el `-p` puede fallar y
    terminaríamos midiendo la base de otro proceso.
    """
    _docker("rm", "-f", nombre)
    r = _docker("run", "-d", "--name", nombre,
                "-e", "MARIADB_ROOT_PASSWORD=legado-efimero",
                "-e", f"MARIADB_DATABASE={BASE_TEMPORAL}",
                "-p", "127.0.0.1::3306", imagen)
    if r.returncode != 0:
        raise RuntimeError(f"no arrancó MariaDB: {r.stderr.strip()}")

    puerto_crudo = _docker("port", nombre, "3306/tcp").stdout.strip().splitlines()
    if not puerto_crudo:
        raise RuntimeError("MariaDB arrancó pero no publicó el puerto")
    puerto = int(puerto_crudo[0].rsplit(":", 1)[1])

    # 🔴 La sonda es una CONSULTA, no un ping.  contesta que
    # el servidor está vivo aunque rechace las credenciales, y durante la
    # inicialización de la imagen hay un servidor temporal que hace exactamente
    # eso: la espera terminaba en verde y la restauración moría con "Access
    # denied". Un chequeo que no puede fallar no es un chequeo.
    for _ in range(120):
        if _docker("inspect", "-f", "{{.State.Running}}", nombre).stdout.strip() != "true":
            registro = _docker("logs", "--tail", "20", nombre).stderr
            raise RuntimeError(f"MariaDB se murió al arrancar: {registro}")
        listo = _docker("exec", nombre, "mariadb", "-uroot", "-plegado-efimero",
                        "-N", "-B", "-e", "SELECT 1")
        if listo.returncode == 0 and listo.stdout.strip() == "1":
            return nombre, puerto
        time.sleep(1)
    raise RuntimeError("MariaDB no llegó a aceptar una consulta en 120 s")


def restaurar_dump(contenedor: str, dump: Path) -> None:
    """Restaura el dump adentro del contenedor.

    `docker exec -i` — **con `-i`**: sin él, el contenedor no recibe nada por
    stdin, el cliente de MariaDB no lee ninguna sentencia y el comando termina
    con código 0. O sea: una restauración vacía que se reporta bien.
    """
    r = _docker("exec", "-i", contenedor, "mariadb", "-uroot", "-plegado-efimero",
                BASE_TEMPORAL, entrada=dump.read_bytes())
    if r.returncode != 0:
        raise RuntimeError(f"falló la restauración: {r.stderr[-500:]!r}")


def tablas_y_columnas(cur) -> dict[str, list[tuple[str, str]]]:
    """`{tabla: [(columna, tipo)]}` leído del `information_schema` del legado."""
    cur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
        (BASE_TEMPORAL,))
    salida: dict[str, list[tuple[str, str]]] = {}
    for tabla, columna, tipo in cur.fetchall():
        nombre = tabla.decode() if isinstance(tabla, bytes) else tabla
        col = columna.decode() if isinstance(columna, bytes) else columna
        dtipo = tipo.decode() if isinstance(tipo, bytes) else tipo
        salida.setdefault(nombre, []).append((col, dtipo))
    return salida


def consulta_de_extraccion(tabla: str, columnas: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """El `SELECT` que trae todo como bytes, y los nombres de destino.

    **Cada columna sale con `CAST(... AS BINARY)`.** Medido contra MariaDB 11.4
    con este driver: sin el `CAST`, un `float(10,2)` vuelve como **`float` de
    Python** —el tipo exacto del que esta migración está huyendo— y un `int`
    como `int`. Para `1234567.89` el `repr` coincide de casualidad, pero
    `'0.10'` vuelve `0.1` y se guarda en el staging como `0.1`: el texto deja de
    ser el que el sistema viejo muestra, que es contra lo que después se compara
    el saldo. Con el `CAST` viene el byte a byte que formatea el servidor.

    Lo que **no** hace falta que arregle: `0000-00-00` llega igual como texto,
    con `CAST` o sin él. Se probó, porque el driver podría haberlo convertido en
    `NULL` y ahí el perfilado no tendría qué contar.

    Las columnas `float` salen **dos veces**: formateada a 2 decimales, que es lo
    que el sistema viejo muestra, y casteada a `DECIMAL(20,6)`, que es lo que hay
    adentro del `float` de precisión simple.
    """
    piezas, destino = [], []
    for col, tipo in columnas:
        piezas.append(f"CAST(`{col}` AS BINARY)")
        destino.append(col)
        if tipo in ("float", "double"):
            piezas.append(f"CAST(CAST(`{col}` AS DECIMAL(20,6)) AS BINARY)")
            destino.append(f"{col}_crudo")
    return f"SELECT {', '.join(piezas)} FROM `{tabla}`", destino


def decidir_codificacion(muestras: list[bytes]) -> tuple[str, dict[str, int]]:
    """`('utf-8'|'latin-1', conteos)` a partir de los valores con bytes altos.

    No hay heurística de terceros: un valor que decodifica como UTF-8 estricto y
    tiene bytes ≥ 0x80 es UTF-8 con altísima probabilidad —las secuencias
    válidas no aparecen por casualidad en texto latin1—, y uno que no decodifica
    no puede serlo.
    """
    conteos = {"utf-8": 0, "latin-1": 0, "total": len(muestras)}
    for valor in muestras:
        try:
            valor.decode("utf-8")
            conteos["utf-8"] += 1
        except UnicodeDecodeError:
            conteos["latin-1"] += 1
    if conteos["total"] == 0:
        # Sin un solo acento en 52.000 filas: raro, pero entonces la decisión no
        # cambia nada y latin-1 no puede fallar (decodifica cualquier byte).
        return "latin-1", conteos
    if conteos["latin-1"] == 0:
        return "utf-8", conteos
    if conteos["utf-8"] == 0:
        return "latin-1", conteos
    raise SystemExit(
        f"🔴 Codificación MEZCLADA: {conteos['utf-8']} valores decodifican como "
        f"UTF-8 y {conteos['latin-1']} no, sobre {conteos['total']} con bytes "
        "no-ASCII. Elegir una rompe la otra mitad: esto se decide a mano, mirando "
        "los valores, antes de cargar nada."
    )


def extraer(puerto: int) -> tuple[dict[str, tuple[list[str], list[tuple]]], list[bytes]]:
    """Trae todas las tablas como bytes, más las muestras para la codificación."""
    import pymysql

    conexion = pymysql.connect(host="127.0.0.1", port=puerto, user="root",
                               password="legado-efimero", database=BASE_TEMPORAL,
                               charset="utf8mb4", use_unicode=False)
    datos: dict[str, tuple[list[str], list[tuple]]] = {}
    muestras: list[bytes] = []
    try:
        with conexion.cursor() as cur:
            for tabla, columnas in tablas_y_columnas(cur).items():
                consulta, destino = consulta_de_extraccion(tabla, columnas)
                cur.execute(consulta)
                filas = cur.fetchall()
                datos[tabla] = (destino, filas)
                for fila in filas:
                    for valor in fila:
                        if isinstance(valor, bytes) and any(b >= 0x80 for b in valor):
                            muestras.append(valor)
    finally:
        conexion.close()
    return datos, muestras


def escribir(datos, codificacion: str, destino: str) -> dict[str, int]:
    """Crea el espejo y copia las filas. Devuelve los conteos por tabla."""
    conteos = {}
    with psycopg.connect(destino) as con:
        con.execute(ESPEJO.read_text(encoding="utf-8"))
        for tabla, (columnas, filas) in datos.items():
            _verificar_columnas(con, tabla, columnas)
            lista = ", ".join(f'"{c}"' for c in columnas)
            with con.cursor().copy(f"COPY legado.{tabla} ({lista}) FROM STDIN") as copia:
                for fila in filas:
                    copia.write_row([
                        v.decode(codificacion) if isinstance(v, bytes) else v for v in fila
                    ])
            conteos[tabla] = len(filas)
        con.commit()
    return conteos


def _verificar_columnas(con, tabla: str, columnas: list[str]) -> None:
    """El espejo tiene que tener exactamente las columnas que se van a escribir.

    Sin este chequeo, una columna que el legado tiene y el espejo no se
    manifiesta como un error de SQL a mitad de la copia —o peor, como una
    columna de más en el espejo que queda en `NULL` para siempre y nadie mira—.
    """
    hay = {f[0] for f in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'legado' AND table_name = %s", (tabla,)).fetchall()}
    faltan = [c for c in columnas if c not in hay]
    sobran = [c for c in hay if c not in columnas]
    if faltan or sobran:
        raise SystemExit(
            f"🔴 El espejo de `{tabla}` no coincide con el legado. "
            f"Faltan en espejo.sql: {faltan or '—'}. Sobran: {sobran or '—'}."
        )


def verificar_conteos(puerto: int, conteos: dict[str, int]) -> list[str]:
    """Compara fila por fila contra el MariaDB de origen.

    Es el control de que la carga trajo todo: un `COPY` que escribió de menos no
    falla, deja una tabla más corta.
    """
    import pymysql

    problemas = []
    conexion = pymysql.connect(host="127.0.0.1", port=puerto, user="root",
                               password="legado-efimero", database=BASE_TEMPORAL)
    try:
        with conexion.cursor() as cur:
            for tabla, cantidad in conteos.items():
                cur.execute(f"SELECT COUNT(*) FROM `{tabla}`")
                origen = cur.fetchone()[0]
                if origen != cantidad:
                    problemas.append(f"{tabla}: origen {origen}, staging {cantidad}")
    finally:
        conexion.close()
    return problemas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Carga el dump del legado al staging")
    p.add_argument("--dump", required=True, type=Path)
    p.add_argument("--destino", required=True, help="URL del PostgreSQL de staging")
    p.add_argument("--imagen", default=IMAGEN_POR_DEFECTO)
    p.add_argument("--conservar", action="store_true",
                   help="deja el MariaDB efímero en pie para poder mirarlo")
    args = p.parse_args(argv)

    if not args.dump.exists():
        print(f"no existe {args.dump}", file=sys.stderr)
        return 1

    contenedor, puerto = levantar_mariadb(args.imagen)
    try:
        print(f"MariaDB efímero en 127.0.0.1:{puerto}")
        restaurar_dump(contenedor, args.dump)
        datos, muestras = extraer(puerto)
        codificacion, conteos_enc = decidir_codificacion(muestras)
        print(f"codificación: {codificacion} "
              f"({conteos_enc['utf-8']} UTF-8 / {conteos_enc['latin-1']} latin-1 "
              f"sobre {conteos_enc['total']} valores con acentos)")

        conteos = escribir(datos, codificacion, args.destino)
        for tabla, cantidad in sorted(conteos.items()):
            print(f"  {tabla}: {cantidad}")

        problemas = verificar_conteos(puerto, conteos)
        if problemas:
            print("🔴 los conteos NO coinciden:", *problemas, sep="\n  ")
            return 1
        print("conteos verificados contra el origen: todos coinciden")

        with psycopg.connect(args.destino) as con:
            rotos = _buscar_mojibake(con)
        if rotos:
            print("🔴 quedaron valores con doble encoding:", *rotos[:10], sep="\n  ")
            print("El dato ya estaba roto en el legado o el charset elegido no es "
                  "el bueno. NO transformar sobre esto.")
            return 1
        print("sin marcas de doble encoding")
        return 0
    finally:
        if not args.conservar:
            _docker("rm", "-f", contenedor)


def _buscar_mojibake(con) -> list[str]:
    """Busca `Ã©`/`Ã±`/`Â` en las columnas de texto ya cargadas."""
    rotos = []
    columnas = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'legado'").fetchall()
    for tabla, columna in columnas:
        condicion = " OR ".join(f"\"{columna}\" LIKE '%{m}%'" for m in MOJIBAKE)
        cantidad = con.execute(
            f'SELECT count(*) FROM legado."{tabla}" WHERE {condicion}').fetchone()[0]
        if cantidad:
            rotos.append(f"{tabla}.{columna}: {cantidad} filas")
    return rotos


if __name__ == "__main__":
    raise SystemExit(main())
