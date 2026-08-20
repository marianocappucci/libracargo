"""Paso 5 de F6: del staging al schema de LibraCargo.

    python -m migracion.transformar \
        --origen  "postgresql://…/libracargo_staging" \
        --destino "postgresql://…/libracargo_migrado"

Cada decisión de este archivo está escrita en `DECISIONS.md` (ADR-009 a ADR-015)
y sale del perfilado sobre los datos reales, no del criterio del script. Donde
hay una elección, el comentario dice cuál ADR la respalda.

**Los ids se asignan acá, no en la base.** Se numera cada tabla desde 1 con un
contador propio y se cargan con `COPY`, y recién al final se adelantan las
secuencias. Es lo que permite armar en memoria el mapa `id viejo → id nuevo`
antes de escribir las tablas que lo necesitan: sin eso habría que insertar fila
por fila con `RETURNING` para 52.000 filas.

**Todo entra en una sola transacción.** Una migración a medias es peor que una
que falló: la que falló se vuelve a correr.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
CERO = Decimal("0.00")

#: Los 75 clientes, 186 fleteros y 15 proveedores dicen todos lo mismo. El mapa
#: existe igual para que un valor nuevo no entre como "responsable inscripto"
#: por descuido.
CONDICION_IVA = {
    "responsable inscripto": "responsable_inscripto",
    "monotributo": "monotributo",
    "monotributista": "monotributo",
    "exento": "exento",
    "consumidor final": "consumidor_final",
}

#: `sucesos_tipo` → `(entidad, accion)`. Son los 6 valores que existen.
SUCESOS = {
    "Alta Orden de Carga": ("orden_carga", "alta"),
    "Modificar Orden de Carga": ("orden_carga", "modificacion"),
    "Elimina Orden de Carga": ("orden_carga", "baja"),
    "Alta de Novedad": ("movimiento_caja", "alta"),
    "Modifica Novedad": ("movimiento_caja", "modificacion"),
    "Elimina Novedades": ("movimiento_caja", "baja"),
}

#: `novedad_tipo` → `(tipo de caja, rol del tercero)`. Los "Personales" son
#: gastos de la agencia: no mueven la cuenta de nadie.
NOVEDADES = {
    "Ingresos por Pagos de Clientes": ("ingreso", "cliente"),
    "Egresos por Pagos a Fleteros": ("egreso", "fletero"),
    "Pago a Proveedores": ("egreso", "proveedor"),
    "Ingresos Personales": ("ingreso", None),
    "Egresos Personales": ("egreso", None),
}


#: Los enlaces explícitos entre un asiento y su contrapartida:
#: `(tabla, id, fecha, prefijo, columna de enlace, tabla enlazada, su id, su fecha,
#: su prefijo)`. Se usan para que las dos mitades de una misma operación no
#: terminen con fechas distintas cuando hay que inferirlas (ADR-012).
ENLACES = [
    ("clientectacte", "clientectacte_id", "clientectacte_fecha", "clientectacte",
     "clientectacte_novedad_id", "novedades", "novedad_id", "novedad_fecha", "novedad"),
    ("fleteroctacte", "fletectacte_id", "fletectacte_fecha", "fleteroctacte",
     "fletectacte_novedad_id", "novedades", "novedad_id", "novedad_fecha", "novedad"),
    ("ctacteprov", "ctacteprov_id", "ctacteprov_fecha", "ctacteprov",
     "ctacteprov_novedad_id", "novedades", "novedad_id", "novedad_fecha", "novedad"),
    ("ctacteprov", "ctacteprov_id", "ctacteprov_fecha", "ctacteprov",
     "ctacteprov_fleteroctacte_id", "fleteroctacte", "fletectacte_id",
     "fletectacte_fecha", "fleteroctacte"),
]


def numero(valor: str | None) -> Decimal | None:
    """`Decimal` o `None`. Todo el staging es `TEXT`: no hay conversión implícita."""
    if valor is None or not valor.strip():
        return None
    try:
        return Decimal(valor.strip())
    except Exception:
        return None


def importe(valor: str | None) -> Decimal:
    return (numero(valor) or CERO).quantize(CERO)


def texto(valor: str | None, largo: int | None = None) -> str | None:
    """Limpia y recorta. Un vacío es ausencia, no `''` — ver `_vacio_es_nulo`."""
    if valor is None:
        return None
    v = valor.strip()
    if not v:
        return None
    return v[:largo] if largo else v


def solo_digitos(cuit: str | None) -> str | None:
    """El CUIT se normaliza sacándole guiones y espacios (ADR-014).

    Dos de los 276 maestros traen un CUIT de más de 13 caracteres; sin
    normalizar, recortarlos a 13 los dejaría cortados por la mitad.
    """
    if not cuit:
        return None
    limpio = re.sub(r"[^0-9]", "", cuit)
    return limpio[:13] or None


def fecha(valor: str | None, inferidas: dict[str, date], clave: str) -> date | None:
    """`0000-00-00` no es una fecha: se reemplaza por la inferida (ADR-012)."""
    if not valor or valor.startswith("0000"):
        return inferidas.get(clave)
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        return inferidas.get(clave)


def asiento(imp1: str | None, imp2: str | None) -> tuple[Decimal, Decimal, str | None]:
    """`(debe, haber, nota)` — invierte la columna cuando el importe es negativo.

    ADR-009: un haber de −X es un debe de +X. El saldo del tercero queda idéntico
    —invertir columna y signo es la identidad sobre `debe − haber`— y el `CHECK`
    se cumple sin relajarlo. La nota deja escrito qué se movió.
    """
    debe, haber = importe(imp1), importe(imp2)
    if debe < 0:
        debe, haber = CERO, -debe
        return debe, haber, f"signo normalizado: debe {imp1}"
    if haber < 0:
        haber, debe = CERO, -haber
        return debe, haber, f"signo normalizado: haber {imp2}"
    return debe, haber, None


class Contador:
    """Ids consecutivos por tabla, asignados acá y no por la secuencia."""

    def __init__(self) -> None:
        self.siguiente: dict[str, int] = defaultdict(lambda: 1)

    def __call__(self, tabla: str) -> int:
        valor = self.siguiente[tabla]
        self.siguiente[tabla] = valor + 1
        return valor


def copiar(destino, tabla: str, columnas: list[str], filas: list[tuple]) -> int:
    if not filas:
        return 0
    lista = ", ".join(f'"{c}"' for c in columnas)
    with destino.cursor().copy(f"COPY {tabla} ({lista}) FROM STDIN") as copia:
        for fila in filas:
            copia.write_row(fila)
    return len(filas)


def leer(origen, tabla: str) -> list[dict]:
    cur = origen.execute(f"SELECT * FROM legado.{tabla}")
    nombres = [d.name for d in cur.description]
    return [dict(zip(nombres, fila, strict=True)) for fila in cur.fetchall()]


#: Las referencias que en el modelo nuevo son **`NOT NULL`**: si el legado trae
#: una rota, no hay dónde poner la fila. Las opcionales no entran acá — un
#: `carga_fletero_id` que no resuelve queda en nulo y se ve.
OBLIGATORIAS = [
    ("orden_carga", "carga_cliente_id", "clientes", "cliente_id"),
    ("orden_carga", "carga_origen_id", "origen", "origen_id"),
    ("orden_carga", "carga_destino_id", "destino", "destino_id"),
    ("facturas", "factura_cliente_id", "clientes", "cliente_id"),
    ("clientectacte", "clientectacte_cliente_id", "clientes", "cliente_id"),
    ("fleteroctacte", "fletectacte_fletero_id", "fleteros", "fletero_id"),
    ("ctacteprov", "ctacteprov_proveedor_id", "proveedores", "proveedor_id"),
]


def verificar_integridad(origen) -> list[str]:
    """Los huérfanos que el modelo nuevo no puede recibir.

    El perfilado midió **cero** sobre el dump del 2026-08-18, así que sobre esos
    datos esta función no encuentra nada. Existe para el dump del corte real: si
    aparece uno, la migración **se planta y lo nombra** en vez de inventarle un
    tercero o saltearse la fila. Qué hacer con un huérfano es una decisión, y las
    decisiones de esta migración están escritas en `DECISIONS.md`, no acá.
    """
    problemas = []
    for tabla, columna, destino, id_destino in OBLIGATORIAS:
        sueltos = origen.execute(f"""
            SELECT {columna}, count(*) FROM legado.{tabla} o
            WHERE NOT EXISTS (SELECT 1 FROM legado.{destino} d
                              WHERE d.{id_destino} = o.{columna})
            GROUP BY 1 ORDER BY 2 DESC""").fetchall()
        for valor, cuantas in sueltos:
            problemas.append(
                f"{tabla}.{columna} = {valor!r} no existe en {destino} ({cuantas} filas)")
    return problemas


def migrar(origen, destino, inferidas: dict[str, date]) -> dict[str, int]:  # noqa: C901
    """Todo el traspaso, en orden de dependencias. Devuelve los conteos."""
    rotas = verificar_integridad(origen)
    if rotas:
        raise SystemExit(
            "🔴 El legado tiene referencias que el modelo nuevo no puede recibir:\n  "
            + "\n  ".join(rotas)
            + "\nCada una necesita una decisión escrita antes de migrar. La migración "
              "no inventa un tercero ni saltea la fila.")
    id_de = Contador()
    conteos: dict[str, int] = {}

    # ---------------------------------------------------------- razón social
    # ADR-013: una sola. El `2 = Mauricio` del `<select>` no aparece en ninguna
    # fila de ninguna tabla del legado.
    razon_social_id = id_de("razones_sociales")
    conteos["razones_sociales"] = copiar(
        destino, "razones_sociales",
        ["id", "nombre", "cuit", "condicion_iva", "punto_venta", "activa", "codigo_legado"],
        [(razon_social_id, "Suitrans", None, "responsable_inscripto", 1, True, 1)],
    )

    # --------------------------------------------------------------- terceros
    # ADR-003: **no se deduplica**. Los 276 entran como 276, cada uno con su rol
    # y su cuenta. Fusionar por CUIT durante la carga rompe las cuentas
    # corrientes; la fusión es un reporte asistido posterior.
    tercero_de: dict[tuple[str, str], int] = {}
    filas_terceros = []
    fuentes = [
        ("cliente", "clientes", "cliente"),
        ("fletero", "fleteros", "fletero"),
        ("proveedor", "proveedores", "proveedor"),
    ]
    # ADR-011: los 19 que nunca hicieron un viaje entran como terceros normales,
    # marcados en `observaciones`. No se inventa una categoría.
    con_viaje = {
        f[0] for f in origen.execute(
            "SELECT DISTINCT carga_fletero_id FROM legado.orden_carga").fetchall()}

    for rol, tabla, prefijo in fuentes:
        for f in leer(origen, tabla):
            id_legado = f[f"{prefijo}_id"]
            nuevo = id_de("terceros")
            tercero_de[(rol, id_legado)] = nuevo
            correo = f.get(f"{prefijo}_email") or f.get(f"{prefijo}_mail")
            notas = [texto(f.get(f"{prefijo}_observaciones"))]
            if rol == "fletero" and id_legado not in con_viaje:
                notas.append(
                    "Cuenta sin ningún viaje en el legado: puede ser una cuenta "
                    "interna (ADR-011).")
            filas_terceros.append((
                nuevo, texto(f[f"{prefijo}_razonsocial"], 120),
                solo_digitos(f.get(f"{prefijo}_cuit")),
                CONDICION_IVA.get(
                    (f.get(f"{prefijo}_condicion_iva") or "").strip().lower(),
                    "no_categorizado"),
                rol == "cliente", rol == "fletero", rol == "proveedor",
                texto(f.get(f"{prefijo}_direccion"), 160),
                texto(f.get(f"{prefijo}_cp"), 12), texto(f.get(f"{prefijo}_localidad"), 80),
                None, texto(f.get(f"{prefijo}_tel"), 40), texto(f.get(f"{prefijo}_cel"), 40),
                texto(correo, 120), texto(f.get(f"{prefijo}_contacto"), 80),
                True, " ".join(n for n in notas if n) or None,
                f"{rol}:{id_legado}",
            ))
    conteos["terceros"] = copiar(
        destino, "terceros",
        ["id", "razon_social", "cuit", "condicion_iva", "es_cliente", "es_fletero",
         "es_proveedor", "direccion", "codigo_postal", "localidad", "provincia",
         "telefono", "celular", "email", "contacto", "activo", "observaciones",
         "origen_legado"],
        filas_terceros)

    # ------------------------------------------------------------ localidades
    # Una sola tabla: 26 de los 47 orígenes existen también como destino.
    localidad_de: dict[tuple[str, str], int] = {}
    por_nombre: dict[str, int] = {}
    filas_localidades = []
    for tabla, prefijo in (("origen", "origen"), ("destino", "destino")):
        for f in leer(origen, tabla):
            nombre = texto(f[f"{prefijo}_nombre"], 80) or "(sin nombre)"
            clave = nombre.upper()
            if clave not in por_nombre:
                nuevo = id_de("localidades")
                por_nombre[clave] = nuevo
                filas_localidades.append((nuevo, nombre, None, True))
            localidad_de[(tabla, f[f"{prefijo}_id"])] = por_nombre[clave]
    conteos["localidades"] = copiar(
        destino, "localidades", ["id", "nombre", "provincia", "activa"], filas_localidades)

    # --------------------------------------------------------------- choferes
    chofer_de: dict[str, int] = {}
    filas_choferes, equipos = [], {}
    for f in leer(origen, "choferes"):
        nuevo = id_de("choferes")
        chofer_de[f["chofer_id"]] = nuevo
        fletero = tercero_de.get(("fletero", f.get("chofer_flete_id")))
        filas_choferes.append((
            nuevo, texto(f["chofer_nombre"], 120), texto(f.get("chofer_dni"), 15),
            texto(f.get("chofer_telefono"), 40), fletero, True, None,
            f"chofer:{f['chofer_id']}"))
        # El chasis y el acoplado salen de `choferes` y pasan a ser un vehículo
        # propio: un chofer maneja distintos equipos y un equipo lo manejan
        # distintos choferes.
        chasis = texto((f.get("chofer_chasis") or "").upper(), 12)
        if chasis:
            acoplado = texto((f.get("chofer_acoplado") or "").upper(), 12)
            equipos.setdefault((chasis, acoplado), fletero)
    conteos["choferes"] = copiar(
        destino, "choferes",
        ["id", "nombre", "dni", "telefono", "fletero_id", "activo", "observaciones",
         "origen_legado"], filas_choferes)

    conteos["vehiculos"] = copiar(
        destino, "vehiculos",
        ["id", "patente_chasis", "patente_acoplado", "fletero_id", "activo"],
        [(id_de("vehiculos"), chasis, acoplado, fletero, True)
         for (chasis, acoplado), fletero in equipos.items()])

    # ----------------------------------------------------------- tipos de carga
    tipo_de: dict[str, int] = {}
    filas_tipos = []
    for (valor,) in origen.execute(
            "SELECT DISTINCT carga_tipo FROM legado.orden_carga ORDER BY 1").fetchall():
        nombre = texto(valor, 80)
        if nombre:
            nuevo = id_de("tipos_carga")
            tipo_de[valor] = nuevo
            filas_tipos.append((nuevo, nombre, None, True))
    conteos["tipos_carga"] = copiar(
        destino, "tipos_carga", ["id", "nombre", "unidad_default", "activo"], filas_tipos)

    # ------------------------------------------------------------ comprobantes
    comprobante_de: dict[tuple[str, str], int] = {}
    filas_comprobantes = []
    for f in leer(origen, "facturas"):
        nuevo = id_de("comprobantes")
        comprobante_de[(f["factura_nro"], f["factura_razonsocial"])] = nuevo
        filas_comprobantes.append((
            nuevo, razon_social_id, "factura_a", 1, int(f["factura_nro"]),
            fecha(f["factura_fecha"], inferidas, f"factura:{f['factura_nro']}"),
            tercero_de[("cliente", f["factura_cliente_id"])],
            importe(f["factura_neto"]), importe(f["factura_iva"]),
            importe(f["factura_total"]), False,
            f"factura:{f['factura_nro']}:{f['factura_razonsocial']}"))

    # ADR-010: las 17 órdenes de agosto 2023 marcadas facturadas y sin factura
    # entran bajo un comprobante de apertura, con la numeración en cero.
    huerfanas = origen.execute("""
        SELECT o.carga_id, o.carga_cliente_id, o.carga_importe, o.carga_iva, o.carga_total,
               o.carga_fecha
        FROM legado.orden_carga o
        WHERE o.carga_facturado = '1'
          AND NOT EXISTS (SELECT 1 FROM legado.facturas f
                          WHERE f.factura_nro = o.carga_factura
                            AND f.factura_razonsocial = o.carga_razonsocial)
        ORDER BY o.carga_id::int""").fetchall()
    apertura_id = None
    if huerfanas:
        apertura_id = id_de("comprobantes")
        filas_comprobantes.append((
            apertura_id, razon_social_id, "factura_a", 0, 0,
            min(date.fromisoformat(h[5][:10]) for h in huerfanas),
            tercero_de[("cliente", huerfanas[0][1])],
            sum(importe(h[2]) for h in huerfanas), sum(importe(h[3]) for h in huerfanas),
            sum(importe(h[4]) for h in huerfanas), False, "apertura"))
    apertura_de = {h[0] for h in huerfanas}
    conteos["comprobantes"] = copiar(
        destino, "comprobantes",
        ["id", "razon_social_id", "tipo", "punto_venta", "numero", "fecha", "cliente_id",
         "neto", "iva", "total", "anulado", "origen_legado"], filas_comprobantes)

    # ------------------------------------------------------------------ órdenes
    orden_de: dict[str, int] = {}
    filas_ordenes = []
    for f in leer(origen, "orden_carga"):
        nuevo = id_de("orden_carga")
        orden_de[f["carga_id"]] = nuevo
        comprobante = comprobante_de.get((f.get("carga_factura"), f.get("carga_razonsocial")))
        if comprobante is None and f["carga_id"] in apertura_de:
            comprobante = apertura_id
        # ADR-014: la cantidad que no es un número va a `cantidad_legado`, con
        # `cantidad` en nulo. Interpretar "832.23 x 6988.46" sería adivinar.
        cantidad = numero(f.get("carga_cantidad"))
        filas_ordenes.append((
            nuevo, fecha(f["carga_fecha"], inferidas, f"carga:{f['carga_id']}"),
            tercero_de[("cliente", f["carga_cliente_id"])],
            localidad_de[("origen", f["carga_origen_id"])],
            localidad_de[("destino", f["carga_destino_id"])],
            tercero_de.get(("fletero", f.get("carga_fletero_id"))),
            chofer_de.get(f.get("carga_chofer_id")), None,
            tipo_de.get(f.get("carga_tipo")),
            texto(f.get("carga_remito"), 30),
            cantidad, None,
            None if cantidad is not None else texto(f.get("carga_cantidad"), 40),
            importe(f["carga_importe"]), Decimal("21.00"), importe(f["carga_iva"]),
            importe(f["carga_total"]), importe(f["carga_comision"]),
            "facturada" if comprobante else "pendiente",
            # ADR-013: el `0` no crea una segunda razón social. Las que no están
            # facturadas y lo llevan entran sin razón social, que el modelo admite.
            razon_social_id if (f.get("carga_razonsocial") == "1" or comprobante) else None,
            comprobante, None, f"carga:{f['carga_id']}"))
    conteos["orden_carga"] = copiar(
        destino, "ordenes_carga",
        ["id", "fecha", "cliente_id", "origen_id", "destino_id", "fletero_id", "chofer_id",
         "vehiculo_id", "tipo_carga_id", "remito", "cantidad", "unidad", "cantidad_legado",
         "tarifa", "alicuota_iva", "iva", "total", "comision", "estado", "razon_social_id",
         "comprobante_id", "observaciones", "origen_legado"], filas_ordenes)

    # --------------------------------------------------------------------- caja
    # El tercero de cada novedad **no se adivina por el tipo**: sale de la fila
    # de cuenta corriente que la referencia. Los tres punteros de `novedades`
    # están siempre completos —el `1` es relleno, no un cliente—, así que leerlos
    # directo daría el tercero equivocado en la mayoría de las filas.
    dueño: dict[str, tuple[str, str]] = {}
    for tabla, prefijo, rol in (
        ("clientectacte", "clientectacte", "cliente"),
        ("fleteroctacte", "fletectacte", "fletero"),
        ("ctacteprov", "ctacteprov", "proveedor"),
    ):
        for id_novedad, id_tercero in origen.execute(
                f"SELECT {prefijo}_novedad_id, {prefijo}_"
                f"{'cliente_id' if rol == 'cliente' else rol + '_id'} "
                f"FROM legado.{tabla} WHERE {prefijo}_novedad_id IS NOT NULL "
                f"AND {prefijo}_novedad_id <> '0'").fetchall():
            dueño.setdefault(id_novedad, (rol, id_tercero))

    caja_de: dict[str, int] = {}
    filas_caja = []
    for f in leer(origen, "novedades"):
        nuevo = id_de("movimientos_caja")
        caja_de[f["novedad_id"]] = nuevo
        tipo, rol_esperado = NOVEDADES.get(f.get("novedad_tipo") or "", ("egreso", None))
        valor = importe(f.get("novedad_importe1")) or importe(f.get("novedad_importe2"))
        if valor < 0:  # mismo criterio que ADR-009: el signo indica el otro lado
            tipo = "ingreso" if tipo == "egreso" else "egreso"
            valor = -valor
        rol, id_tercero = dueño.get(f["novedad_id"], (None, None))
        tercero = tercero_de.get((rol, id_tercero)) if rol else None
        if rol_esperado is None:
            tercero = None  # "Personales": gasto de la agencia, no mueve cuentas
        filas_caja.append((
            nuevo, fecha(f["novedad_fecha"], inferidas, f"novedad:{f['novedad_id']}"),
            tipo, texto(f.get("novedad_tipo"), 120) or "Movimiento",
            texto(f.get("novedad_descripcion")), tercero, valor,
            "efectivo" if f.get("novedad_efectivo") == "1" else "otro",
            texto(f.get("novedad_recibo"), 30), f"novedad:{f['novedad_id']}"))
    conteos["novedades"] = copiar(
        destino, "movimientos_caja",
        ["id", "fecha", "tipo", "concepto", "descripcion", "tercero_id", "importe",
         "medio_pago", "recibo", "origen_legado"], filas_caja)

    # ---------------------------------------------------------- cuentas corrientes
    filas_cuenta = []
    cuentas = [
        ("clientectacte", "clientectacte", "cliente", "clientectacte_cliente_id"),
        ("fleteroctacte", "fletectacte", "fletero", "fletectacte_fletero_id"),
        ("ctacteprov", "ctacteprov", "proveedor", "ctacteprov_proveedor_id"),
    ]
    for tabla, prefijo, rol, columna_tercero in cuentas:
        for f in leer(origen, tabla):
            debe, haber, nota = asiento(f.get(f"{prefijo}_importe1"), f.get(f"{prefijo}_importe2"))
            partes = [texto(f.get(f"{prefijo}_descripcion")), nota]
            id_legado = f[f"{prefijo}_id"]
            filas_cuenta.append((
                id_de("movimientos_cuenta"),
                fecha(f[f"{prefijo}_fecha"], inferidas, f"{tabla}:{id_legado}"),
                tercero_de[(rol, f[columna_tercero])], rol,
                texto(f.get(f"{prefijo}_tipo_mov") or f.get(f"{prefijo}_tipo"), 120)
                or "Movimiento",
                " · ".join(p for p in partes if p) or None,
                debe, haber,
                orden_de.get(f.get(f"{prefijo}_carga_id")),
                comprobante_de.get((f.get(f"{prefijo}_factura"), "1")),
                caja_de.get(f.get(f"{prefijo}_novedad_id")),
                f"{tabla}:{id_legado}"))
    conteos["movimientos_cuenta"] = copiar(
        destino, "movimientos_cuenta",
        ["id", "fecha", "tercero_id", "rol", "concepto", "descripcion", "debe", "haber",
         "orden_id", "comprobante_id", "movimiento_caja_id", "origen_legado"], filas_cuenta)

    # --------------------------------------------------------------- auditoría
    filas_auditoria = []
    for f in leer(origen, "sucesos"):
        entidad, accion = SUCESOS.get(f.get("sucesos_tipo") or "", ("desconocido", "modificacion"))
        dia = fecha(f["sucesos_fecha"], inferidas, f"suceso:{f['sucesos_id']}")
        hora = time.fromisoformat((f.get("sucesos_hora") or "00:00:00")[:8])
        # El puntero apunta al id VIEJO; se traduce, y si no existe queda en
        # nulo. `sucesos` es la única tabla del legado con punteros rotos: 30 de
        # 15.884.
        entidad_id = (orden_de.get(f.get("sucesos_ordencarga")) if entidad == "orden_carga"
                      else caja_de.get(f.get("sucesos_novedades")))
        filas_auditoria.append((
            id_de("auditoria"),
            datetime.combine(dia or date(2023, 8, 1), hora, tzinfo=TZ),
            None, texto(f.get("sucesos_usuario"), 120), entidad, entidad_id, accion,
            None, None))
    conteos["sucesos"] = copiar(
        destino, "auditoria",
        ["id", "ts", "usuario_id", "usuario_nombre", "entidad", "entidad_id", "accion",
         "datos_antes", "datos_despues"], filas_auditoria)

    # ------------------------------------------------------------- secuencias
    # Los ids los puso el contador, así que la secuencia sigue en 1: el primer
    # alta del sistema nuevo chocaría contra la clave primaria de la fila 1.
    for tabla in ("razones_sociales", "terceros", "localidades", "choferes", "vehiculos",
                  "tipos_carga", "comprobantes", "ordenes_carga", "movimientos_caja",
                  "movimientos_cuenta", "auditoria"):
        destino.execute(
            f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
            f"coalesce((SELECT max(id) FROM {tabla}), 1))")
    return conteos


def fechas_inferidas(origen) -> dict[str, date]:
    """ADR-012: las 4 fechas `0000-00-00`, tomadas del id vecino.

    Los ids de estas tablas son cronológicos, así que el vecino de abajo y el de
    arriba acotan la fecha; cuando los dos coinciden, no hay ambigüedad. Se
    calcula sobre los datos y no se escribe una constante: si el próximo dump
    trae otra fila en cero, sale sola.
    """
    inferidas: dict[str, date] = {}
    tablas = [
        ("orden_carga", "carga_id", "carga_fecha", "carga"),
        ("facturas", "factura_nro", "factura_fecha", "factura"),
        ("clientectacte", "clientectacte_id", "clientectacte_fecha", "clientectacte"),
        ("fleteroctacte", "fletectacte_id", "fletectacte_fecha", "fleteroctacte"),
        ("ctacteprov", "ctacteprov_id", "ctacteprov_fecha", "ctacteprov"),
        ("novedades", "novedad_id", "novedad_fecha", "novedad"),
        ("sucesos", "sucesos_id", "sucesos_fecha", "suceso"),
    ]
    for tabla, columna_id, columna_fecha, prefijo in tablas:
        # Se compara con left(fecha, 4) en vez de con un LIKE: la consulta de
        # abajo lleva un parametro, y cuando los hay psycopg parsea todo el
        # texto -- el signo de porcentaje de un LIKE revienta con
        # "only '%s' are allowed as placeholders".
        rotas = origen.execute(
            f"SELECT {columna_id} FROM legado.{tabla} WHERE left({columna_fecha}, 4) = '0000'"
        ).fetchall()
        for (id_roto,) in rotas:
            vecina = origen.execute(f"""
                SELECT {columna_fecha} FROM legado.{tabla}
                WHERE left({columna_fecha}, 4) <> '0000'
                ORDER BY abs({columna_id}::int - %s) LIMIT 1""", (int(id_roto),)).fetchone()
            if vecina:
                inferidas[f"{prefijo}:{id_roto}"] = date.fromisoformat(vecina[0][:10])

    # 🔑 **La contrapartida manda sobre el vecino.** Las 4 filas rotas son 2
    # operaciones con su asiento espejo, y el id vecino les daba fechas
    # distintas a cada mitad: `clientectacte:328` quedaba en 2023-10-24 y su
    # novedad 483 en 2023-10-23; `ctacteprov:1856` en 2025-01-22 y el
    # `fleteroctacte:6705` que la origina, en 2025-01-06. Un mismo movimiento
    # con dos fechas descuadra cualquier corte, y el enlace es explícito en el
    # legado — así que se usa.
    for tabla, columna_id, columna_fecha, prefijo, enlace, destino, id_destino, \
            fecha_destino, prefijo_destino in ENLACES:
        rotas = origen.execute(
            f"SELECT {columna_id}, {enlace} FROM legado.{tabla} "
            f"WHERE left({columna_fecha}, 4) = '0000' "
            f"AND {enlace} IS NOT NULL AND {enlace} <> '0'").fetchall()
        for id_roto, id_enlazado in rotas:
            fila = origen.execute(
                f"SELECT {fecha_destino} FROM legado.{destino} "
                f"WHERE {id_destino} = %s", (id_enlazado,)).fetchone()
            if not fila:
                continue
            if fila[0].startswith("0000"):
                referida = inferidas.get(f"{prefijo_destino}:{id_enlazado}")
            else:
                referida = date.fromisoformat(fila[0][:10])
            if referida:
                inferidas[f"{prefijo}:{id_roto}"] = referida
    return inferidas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Transforma el staging al schema de LibraCargo")
    p.add_argument("--origen", required=True)
    p.add_argument("--destino", required=True)
    args = p.parse_args(argv)

    with psycopg.connect(args.origen) as origen, psycopg.connect(args.destino) as destino:
        cargadas = destino.execute("SELECT count(*) FROM terceros").fetchone()[0]
        if cargadas:
            print(f"🔴 el destino ya tiene {cargadas} terceros. La migración corre sobre "
                  "una base vacía: vaciala o apuntá a otra.", file=sys.stderr)
            return 1

        inferidas = fechas_inferidas(origen)
        for clave, valor in sorted(inferidas.items()):
            print(f"fecha inferida — {clave}: {valor}")

        conteos = migrar(origen, destino, inferidas)
        # Un solo `commit`, al final. Una migración a medias es peor que una que
        # falló: la que falló se vuelve a correr.
        destino.commit()

    for tabla, cantidad in conteos.items():
        print(f"  {tabla}: {cantidad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
