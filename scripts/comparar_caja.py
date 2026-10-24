"""Compara la caja y las cuentas corrientes ANTES y DESPUÉS de pasar la caja al motor (revisión `0032`, ADR-055).

**Sólo lee.** Abre la transacción en modo lectura (`SET TRANSACTION READ ONLY`): no puede escribir aunque se lo
pida, y se puede correr contra una instancia con clientes adentro.

Se usa en tres pasos (el procedimiento completo está en `DECISIONS.md`, ADR-055):

    # 1. ANTES de migrar: una foto de la caja propia (`movimientos_caja`) y de las cuentas.
    python -m scripts.comparar_caja foto --salida /tmp/caja-antes.json

    # 2. Se migra (`alembic upgrade head`; la `0032` copia la caja al motor).

    # 3. DESPUÉS: la misma foto sobre la caja del motor, y la comparación. Sale 0 si es idéntica, 1 si no.
    python -m scripts.comparar_caja comparar --antes /tmp/caja-antes.json

Y como segunda barrera, ya migrada la base, sin foto previa: `contra-legado` compara la caja nueva con la tabla
vieja (`movimientos_caja_legado`), que la `0032` deja en la misma base. Sólo es igual mientras no se haya cargado
ni anulado nada después de migrar.

**Qué compara** (todo exacto, en `Decimal`; nada pasa por `float`):

- **Cada movimiento**, por id: fecha, tipo, concepto, importe, medio de pago, anulado, tercero, descripción, recibo
  y origen en el legado. Una huella por fila: si algo cambia, dice qué ids.
- **La caja**: cantidad e importe por (tipo, medio de pago, anulado), y por tercero lo cobrado y lo pagado vigentes.
- **Las cuentas corrientes** (`cc_asientos`, que esta revisión no toca): por (tercero, rol) el debe, el haber y el
  saldo **calculado de las dos maneras de F4** —sumado por la base y acumulado fila por fila en Python—, y una
  huella del libro entero con el vínculo de cada asiento a su movimiento de caja.

Un importe con más de dos decimales se marca con `!` y se compara tal cual: no se redondea para que coincida.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from decimal import Decimal

from sqlalchemy import create_engine, text

VERSION = 1
CERO = Decimal("0.00")


def _dinero(valor) -> str:
    """El importe con dos decimales; con más, se marca con `!` y se deja como está (no se redondea)."""
    d = Decimal(str(valor))
    q = d.quantize(CERO)
    return str(q) if q == d else f"!{d}"


def _huella(*partes) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in partes).encode()).hexdigest()


def _existe(con, tabla: str) -> bool:
    return con.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar() is not None


def donde_esta_la_caja(con) -> str:
    """`propia` (`movimientos_caja`, antes de la `0032`) o `motor` (`caja_movimientos` + `movimientos_caja_cargo`)."""
    if _existe(con, "movimientos_caja_cargo"):
        return "motor"
    if _existe(con, "movimientos_caja"):
        return "propia"
    raise SystemExit("no encuentro la caja: ni `movimientos_caja` ni `movimientos_caja_cargo`")


_COLUMNAS = ("id", "fecha", "tipo", "concepto", "importe", "medio_pago", "anulado", "tercero_id", "descripcion",
             "recibo", "origen_legado")

_SQL_CAJA = {
    "propia": (
        "SELECT id, to_char(fecha, 'YYYY-MM-DD'), tipo::text, concepto, importe::text, medio_pago::text, "
        "CASE WHEN anulado THEN 1 ELSE 0 END, tercero_id, descripcion, recibo, origen_legado "
        "FROM movimientos_caja ORDER BY id"),
    "legado": (
        "SELECT id, to_char(fecha, 'YYYY-MM-DD'), tipo::text, concepto, importe::text, medio_pago::text, "
        "CASE WHEN anulado THEN 1 ELSE 0 END, tercero_id, descripcion, recibo, origen_legado "
        "FROM movimientos_caja_legado ORDER BY id"),
    "motor": (
        "SELECT a.id, a.fecha, a.tipo, a.concepto, a.monto::text, a.medio_pago, a.anulado, c.tercero_id, "
        "c.descripcion, c.recibo, c.origen_legado "
        "FROM caja_movimientos a JOIN movimientos_caja_cargo c ON c.movimiento_id = a.id ORDER BY a.id"),
}


def _filas_de_caja(con, donde: str) -> list[dict]:
    filas = []
    for fila in con.execute(text(_SQL_CAJA[donde])):
        f = dict(zip(_COLUMNAS, fila, strict=True))
        f["importe"] = _dinero(f["importe"])
        f["anulado"] = int(f["anulado"])
        filas.append(f)
    return filas


def _caja(filas: list[dict]) -> dict:
    por_tipo: dict[str, dict] = {}
    por_tercero: dict[str, dict] = {}
    for f in filas:
        clave = f"{f['tipo']}|{f['medio_pago']}|{'anulado' if f['anulado'] else 'vigente'}"
        acc = por_tipo.setdefault(clave, {"n": 0, "importe": CERO})
        acc["n"] += 1
        acc["importe"] += Decimal(f["importe"].lstrip("!"))
        if not f["anulado"]:
            t = por_tercero.setdefault(str(f["tercero_id"] or "-"), {"n": 0, "ingresos": CERO, "egresos": CERO})
            t["n"] += 1
            t["ingresos" if f["tipo"] == "ingreso" else "egresos"] += Decimal(f["importe"].lstrip("!"))
    for acc in por_tipo.values():
        acc["importe"] = _dinero(acc["importe"])
    for t in por_tercero.values():
        t["ingresos"], t["egresos"] = _dinero(t["ingresos"]), _dinero(t["egresos"])
    return {"por_tipo_medio_y_estado": por_tipo, "por_tercero_vigente": por_tercero}


def _cuentas(con) -> dict:
    """Las cuentas por (tercero, rol) con el saldo de F4 por los dos caminos, y la huella del libro."""
    cuentas: dict[str, dict] = {}
    libro = hashlib.sha256()
    ruta_sql = {
        (t, r): (Decimal(str(d)), Decimal(str(h)))
        for t, r, d, h in con.execute(text(
            "SELECT tercero_id, rol, coalesce(sum(debe), 0), coalesce(sum(haber), 0) "
            "FROM cc_asientos GROUP BY tercero_id, rol"))
    }
    vinculo = dict(con.execute(text(
        "SELECT asiento_id, movimiento_caja_id FROM movimientos_cuenta_cargo")).all())
    acumulado: dict[tuple, Decimal] = {}
    cantidad: dict[tuple, int] = {}
    for id_, fecha, tercero, rol, debe, haber, factura, legado in con.execute(text(
            "SELECT id, fecha, tercero_id, rol, debe, haber, factura_id, origen_legado FROM cc_asientos "
            "ORDER BY tercero_id, rol, fecha, id")):
        clave = (tercero, rol)
        acumulado[clave] = acumulado.get(clave, CERO) + Decimal(str(debe)) - Decimal(str(haber))
        cantidad[clave] = cantidad.get(clave, 0) + 1
        libro.update(_huella(id_, fecha, tercero, rol, _dinero(debe), _dinero(haber), factura, legado,
                             vinculo.get(id_)).encode())
    for clave, (debe, haber) in sorted(ruta_sql.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        por_sql = debe - haber
        recorriendo = acumulado[clave]
        cuentas[f"{clave[0]}|{clave[1]}"] = {
            "n": cantidad[clave], "debe": _dinero(debe), "haber": _dinero(haber),
            "saldo_por_la_base": _dinero(por_sql), "saldo_recorriendo": _dinero(recorriendo),
            "coinciden": por_sql == recorriendo,
        }
    return {"cuentas": cuentas, "huella_del_libro": libro.hexdigest(),
            "f4_no_coinciden": sorted(k for k, v in cuentas.items() if not v["coinciden"])}


def foto(con, donde: str | None = None) -> dict:
    """La foto de la caja y las cuentas. `donde`: `propia`, `legado` o `motor` (por omisión, donde esté la caja)."""
    con.execute(text("SET TRANSACTION READ ONLY"))
    donde = donde or donde_esta_la_caja(con)
    filas = _filas_de_caja(con, donde)
    huellas = {str(f["id"]): _huella(*(f[c] for c in _COLUMNAS))[:16] for f in filas}
    ajenas = 0
    if donde == "motor":
        ajenas = con.execute(text(
            "SELECT count(*) FROM caja_movimientos a WHERE NOT EXISTS "
            "(SELECT 1 FROM movimientos_caja_cargo c WHERE c.movimiento_id = a.id)")).scalar()
    return {
        "version": VERSION, "caja_leida_de": donde,
        "movimientos": {
            "n": len(filas), "anulados": sum(f["anulado"] for f in filas),
            "id_min": filas[0]["id"] if filas else None, "id_max": filas[-1]["id"] if filas else None,
            "huella": _huella(*huellas.items()),
        },
        "huellas_por_id": huellas,
        # Filas de `caja_movimientos` que no son de este producto (no tienen fila propia): no se comparan.
        "filas_del_motor_sin_fila_propia": ajenas,
        # Cuántas cajas tiene el motor: sin ninguna, `caja_id` queda en `NULL` (igual que en el alta del motor).
        "cajas_del_motor": con.execute(text("SELECT count(*) FROM cajas")).scalar(),
        "caja": _caja(filas),
        **_cuentas(con),
    }


def _diferencias(antes, despues, ruta: str = "") -> list[str]:
    if isinstance(antes, dict) and isinstance(despues, dict):
        salida = []
        for k in sorted(set(antes) | set(despues), key=str):
            if k not in antes:
                salida.append(f"{ruta}/{k}: sólo en DESPUÉS = {despues[k]!r}")
            elif k not in despues:
                salida.append(f"{ruta}/{k}: sólo en ANTES = {antes[k]!r}")
            else:
                salida += _diferencias(antes[k], despues[k], f"{ruta}/{k}")
        return salida
    return [] if antes == despues else [f"{ruta}: antes {antes!r} / después {despues!r}"]


#: Lo que no se compara: describe la foto, no la caja.
_NO_SE_COMPARA = ("caja_leida_de", "filas_del_motor_sin_fila_propia", "cajas_del_motor")


def comparar(antes: dict, despues: dict) -> list[str]:
    """Las diferencias entre dos fotos; vacía si la caja y las cuentas son idénticas."""
    if antes.get("version") != VERSION or despues.get("version") != VERSION:
        return [f"versión de la foto distinta: {antes.get('version')} / {despues.get('version')}"]
    a = {k: v for k, v in antes.items() if k not in _NO_SE_COMPARA}
    d = {k: v for k, v in despues.items() if k not in _NO_SE_COMPARA}
    return _diferencias(a, d)


def resumen(f: dict) -> str:
    """Lo que el operador mira a ojo: conteos y totales por tipo y medio."""
    m = f["movimientos"]
    lineas = [f"caja leída de: {f['caja_leida_de']}",
              f"movimientos: {m['n']} (anulados {m['anulados']}), ids {m['id_min']}..{m['id_max']}",
              f"cuentas: {len(f['cuentas'])}; F4 que no coinciden: {len(f['f4_no_coinciden'])}; "
              f"cajas en el motor: {f['cajas_del_motor']}"]
    for clave, v in sorted(f["caja"]["por_tipo_medio_y_estado"].items()):
        lineas.append(f"  {clave:<40} {v['n']:>6}  {v['importe']:>18}")
    if f["filas_del_motor_sin_fila_propia"]:
        lineas.append(f"aviso: {f['filas_del_motor_sin_fila_propia']} filas de caja_movimientos no son de este "
                      "producto (sin fila propia); no se comparan")
    return "\n".join(lineas)


def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("falta DATABASE_URL")
    return create_engine(url)


def _sacar(f: dict, salida: str | None) -> None:
    if salida:
        with open(salida, "w", encoding="utf-8") as archivo:
            json.dump(f, archivo, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"foto guardada en {salida}")


def _informar(difs: list[str]) -> int:
    if not difs:
        print("IGUALES: la caja, los saldos por tercero y las cuentas (F4) no cambiaron.")
        return 0
    print(f"DISTINTAS: {len(difs)} diferencias (primeras 40)")
    for d in difs[:40]:
        print("  -", d)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    p = sub.add_parser("foto", help="saca la foto de la caja y las cuentas")
    p.add_argument("--salida", help="archivo JSON donde guardarla")
    p = sub.add_parser("comparar", help="saca la foto de ahora y la compara con la de antes")
    p.add_argument("--antes", required=True, help="la foto sacada antes de migrar")
    p.add_argument("--salida", help="guardar también la foto de ahora")
    sub.add_parser("contra-legado", help="compara la caja del motor con movimientos_caja_legado, en la misma base")
    args = ap.parse_args(argv)

    with _engine().connect() as con:
        if args.orden == "foto":
            f = foto(con)
            print(resumen(f))
            _sacar(f, args.salida)
            return 0 if not f["f4_no_coinciden"] else 1
        if args.orden == "comparar":
            with open(args.antes, encoding="utf-8") as archivo:
                antes = json.load(archivo)
            ahora = foto(con)
            print("ANTES\n" + "\n".join("  " + x for x in resumen(antes).splitlines()))
            print("DESPUÉS\n" + "\n".join("  " + x for x in resumen(ahora).splitlines()))
            _sacar(ahora, args.salida)
            return _informar(comparar(antes, ahora))
        antes = foto(con, "legado")
        ahora = foto(con, "motor")
        return _informar(comparar(antes, ahora))


if __name__ == "__main__":
    sys.exit(main())
