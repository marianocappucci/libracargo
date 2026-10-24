"""La revisión `0032`: la caja pasa a `caja_movimientos` del motor, con lo propio en `movimientos_caja_cargo` (ADR-055).

Se arma una base en la `0031`, con su tabla `movimientos_caja`, con **datos sintéticos parecidos a los de Suitrans**:
varios terceros con distintos roles (uno es cliente y fletero a la vez), movimientos de las cuatro formas de pago,
ingresos y egresos, anulados con su contraasiento, gastos generales de la agencia sin tercero, filas del legado sin
importe, un recibo repetido, importes con centavos y uno enorme, ids con un salto, y la cuenta corriente atada a la
caja. Después se sube a la `0032` y se mira que **no se movió un id, un importe, un saldo por caja ni por tercero ni
el control F4**.

Cada barrera de abajo está probada también al revés: ver `test_la_comparacion_muerde`, que rompe a propósito la caja
ya migrada y exige que `scripts.comparar_caja` lo diga.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import MovimientoCaja
from app.models.enums import MedioPago, RolCuenta, TipoMovimientoCaja
from app.servicios import cuentas
from app.servicios import reportes as servicio_de_reportes
from scripts import comparar_caja
from tests.conftest import RAIZ, URL, rearmar_en
from tests.test_comprobantes_en_facturas import _alembic
from tests.test_cuenta_en_el_libro_del_motor import _sql

CERO = Decimal("0.00")
LEGADO = "movimientos_caja_legado"   # la caja propia, ya renombrada por la `0032`

#: (id, rol de su cuenta o None, tercero) — los terceros: 1 cliente; 2 fletero y proveedor; 3 cliente y fletero;
#: 4 proveedor. El 5 existe pero no tiene un solo movimiento.
TERCEROS = [
    (1, "ACOPIO SUR SA", True, False, False),
    (2, "TRANSPORTES DEL OESTE", False, True, True),
    (3, "AGRO NORTE SRL", True, True, False),
    (4, "TALLER EL CAMPO", False, False, True),
    (5, "SIN MOVIMIENTOS SA", True, False, False),
]
MEDIOS = ["efectivo", "transferencia", "cheque", "otro"]


def _movimientos() -> list[dict]:
    """Los movimientos de la base de antes. Determinista: ningún azar, ningún reloj."""
    filas = []
    importes = [
        Decimal("1210.00"), Decimal("0.01"), Decimal("99999.99"), Decimal("500000.50"), Decimal("0.10"),
        Decimal("0.20"), Decimal("33333.33"), Decimal("123456789012.34"), Decimal("7.07"), Decimal("1000.00"),
    ]
    # (tercero, rol, tipo): cobranza y devolución de un cliente; pago y devolución de un fletero y un proveedor.
    pares = [(1, "cliente", "ingreso"), (3, "cliente", "ingreso"), (1, "cliente", "egreso"),
             (2, "fletero", "egreso"), (3, "fletero", "egreso"), (2, "proveedor", "egreso"),
             (4, "proveedor", "egreso"), (2, "fletero", "ingreso"), (None, None, "egreso"), (None, None, "ingreso")]
    for i in range(1, 41):
        tercero, rol, tipo = pares[i % len(pares)]
        filas.append({
            "id": i, "fecha": date(2026, 7, 1) + timedelta(days=i), "tipo": tipo,
            "concepto": f"Movimiento {i}", "descripcion": None if i % 3 else f"Línea 1\nLínea 2 · ñandú {i}",
            "tercero": tercero, "rol": rol, "importe": importes[i % len(importes)],
            "medio": MEDIOS[i % len(MEDIOS)], "recibo": f"R-{i // 4:04d}" if i % 2 else None,  # el recibo se repite
            "anulado": i % 9 == 0, "legado": None,
        })
    # Del legado: sin importe cargado (la `CHECK` los deja pasar), con su origen. Y el salto de ids.
    filas.append({"id": 45, "fecha": date(2023, 8, 1), "tipo": "egreso", "concepto": "Personales",
                  "descripcion": "Sin importe en el sistema viejo", "tercero": None, "rol": None,
                  "importe": CERO, "medio": "otro", "recibo": None, "anulado": False, "legado": "novedad:45"})
    filas.append({"id": 5000, "fecha": date(2026, 9, 30), "tipo": "ingreso", "concepto": "Cobro grande",
                  "descripcion": None, "tercero": 1, "rol": "cliente", "importe": Decimal("250000.00"),
                  "medio": "transferencia", "recibo": "R-5000", "anulado": False, "legado": "novedad:5000"})
    return filas


def _sembrar(con) -> list[dict]:
    for id_, razon, cliente, fletero, proveedor in TERCEROS:
        _sql(con, "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, es_fletero, es_proveedor, "
                  "activo) VALUES (:id, :r, 'responsable_inscripto', :c, :f, :p, true)",
             id=id_, r=razon, c=cliente, f=fletero, p=proveedor)
    movimientos = _movimientos()
    asiento = 100
    for m in movimientos:
        _sql(con, "INSERT INTO movimientos_caja (id, fecha, tipo, concepto, descripcion, tercero_id, importe, "
                  "medio_pago, recibo, anulado, origen_legado) VALUES (:id, :fecha, :tipo, :concepto, "
                  ":descripcion, :tercero, :importe, :medio, :recibo, :anulado, :legado)", **m)
        if m["tercero"] is None:
            continue
        # Un cobro de cliente y un pago de fletero van al haber (la convención de `servicios/caja.va_al_haber`).
        al_haber = (m["tipo"] == "ingreso") == (m["rol"] == "cliente")
        debe, haber = (CERO, m["importe"]) if al_haber else (m["importe"], CERO)
        if m["importe"] == CERO:
            continue
        asientos = [(debe, haber, m["concepto"])]
        if m["anulado"]:
            asientos.append((haber, debe, f"Anulación {m['concepto']}"))
        for d, h, concepto in asientos:
            asiento += 1
            _sql(con, "INSERT INTO cc_asientos (id, fecha, tercero_id, rol, concepto, debe, haber) "
                      "VALUES (:id, :f, :t, :r, :c, :d, :h)",
                 id=asiento, f=m["fecha"].isoformat(), t=m["tercero"], r=m["rol"], c=concepto, d=d, h=h)
            _sql(con, "INSERT INTO movimientos_cuenta_cargo (asiento_id, movimiento_caja_id) VALUES (:a, :m)",
                 a=asiento, m=m["id"])
    # Un asiento que no es de caja (una factura): la cuenta no es sólo caja.
    _sql(con, "INSERT INTO cc_asientos (id, fecha, tercero_id, rol, concepto, debe, haber) "
              "VALUES (900, '2026-08-01', 1, 'cliente', 'Factura', 1210.00, 0)")
    _sql(con, "INSERT INTO movimientos_cuenta_cargo (asiento_id) VALUES (900)")
    _sql(con, "SELECT setval(pg_get_serial_sequence('movimientos_caja', 'id'), 5000)")
    _sql(con, "SELECT setval(pg_get_serial_sequence('cc_asientos', 'id'), 900)")
    return movimientos


@pytest.fixture
def base_de_antes(engine, sesion):
    """Una base en la `0031`, con la caja propia llena. Siempre vuelve a `head`."""
    rearmar_en("0031")
    # 🔴 Las conexiones del pool recuerdan sentencias preparadas contra los tipos (`ENUM`) de la base que se acaba
    # de tirar: sin esto, el segundo test muere con «cache lookup failed for type».
    engine.dispose()
    try:
        with engine.begin() as con:
            movimientos = _sembrar(con)
        yield engine, movimientos
    finally:
        sesion.rollback()
        # Si el test dejó la base a medias (se rompió en la `0032`), se la vuelve a armar entera.
        with engine.begin() as con:
            en_el_motor = _sql(con, "SELECT to_regclass('movimientos_caja_cargo')").scalar()
        if en_el_motor is None and _versión_actual(engine) != "0031":
            rearmar_en("head")
        else:
            with engine.begin() as con:
                for tabla in ("movimientos_cuenta_cargo", "cc_asientos", "movimientos_caja_cargo",
                              "caja_movimientos", "movimientos_caja_legado", "movimientos_caja", "terceros"):
                    if con.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar():
                        _sql(con, f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")
            _alembic("head")
        engine.dispose()


def _versión_actual(engine) -> str | None:
    with engine.connect() as con:
        try:
            return _sql(con, "SELECT version_num FROM alembic_version_libracargo").scalar()
        except Exception:
            return None


def _foto(engine, donde=None) -> dict:
    with engine.connect() as con:
        return comparar_caja.foto(con, donde)


def _esperado(movimientos: list[dict]) -> dict:
    """Lo que dice la caja, calculado desde la siembra y no desde la base."""
    caja = {}
    for m in movimientos:
        clave = (m["tipo"], m["medio"], bool(m["anulado"]))
        n, total = caja.get(clave, (0, CERO))
        caja[clave] = (n + 1, total + m["importe"])
    return caja


# ── La migración ────────────────────────────────────────────────────────────


def test_la_0032_pasa_la_caja_al_motor_sin_mover_un_id_un_importe_ni_un_saldo(base_de_antes, sesion):
    engine, movimientos = base_de_antes
    antes = _foto(engine)
    assert antes["caja_leida_de"] == "propia"
    assert antes["movimientos"]["n"] == 42
    assert antes["movimientos"]["anulados"] == 4          # 9, 18, 27, 36
    assert antes["f4_no_coinciden"] == []
    assert len(antes["cuentas"]) >= 6

    _alembic("0032", subir=True)

    despues = _foto(engine)
    assert despues["caja_leida_de"] == "motor"
    # Lo central: la misma caja, el mismo libro, el mismo F4. Cualquier diferencia se nombra.
    assert comparar_caja.comparar(antes, despues) == []

    with engine.connect() as con:
        # Los ids se conservan, todos.
        assert [r[0] for r in _sql(con, "SELECT id FROM caja_movimientos ORDER BY id")] == sorted(
            m["id"] for m in movimientos)
        assert _sql(con, "SELECT count(*) FROM movimientos_caja_cargo c JOIN caja_movimientos a "
                         "ON a.id = c.movimiento_id").scalar() == 42
        # La fila del motor dice lo que el motor espera: fecha ISO, texto, entero y el importe exacto.
        fila = _sql(con, "SELECT fecha, tipo, concepto, monto::text, medio_pago, anulado, referencia, turno_id "
                         "FROM caja_movimientos WHERE id = 1").one()
        assert fila[0] == "2026-07-02" and fila[2] == "Movimiento 1" and fila[6] == "" and fila[7] is None
        assert _sql(con, "SELECT monto::text FROM caja_movimientos WHERE concepto = 'Movimiento 7'"
                    ).scalar() == "123456789012.34"
        assert _sql(con, "SELECT monto::text FROM caja_movimientos WHERE id = 45").scalar() == "0.00"
        # Lo propio quedó en la fila propia, con el recibo repetido y el origen del legado.
        assert _sql(con, "SELECT descripcion FROM movimientos_caja_cargo WHERE movimiento_id = 3"
                    ).scalar() == "Línea 1\nLínea 2 · ñandú 3"
        assert _sql(con, "SELECT count(*) FROM movimientos_caja_cargo WHERE recibo = 'R-0001'").scalar() == 2
        assert _sql(con, "SELECT origen_legado FROM movimientos_caja_cargo WHERE movimiento_id = 5000"
                    ).scalar() == "novedad:5000"
        # La secuencia siguió: el próximo id no choca con el 5000.
        assert _sql(con, "SELECT nextval(pg_get_serial_sequence('caja_movimientos', 'id'))").scalar() == 5001
        # La tabla vieja queda de sólo lectura, con lo mismo.
        assert _sql(con, "SELECT count(*) FROM movimientos_caja_legado").scalar() == 42
        assert _sql(con, "SELECT to_regclass('movimientos_caja')").scalar() is None
        # La cuenta corriente apunta al movimiento del motor: la FK es nueva, y vale.
        with pytest.raises(IntegrityError):
            with con.begin_nested():
                _sql(con, "INSERT INTO movimientos_cuenta_cargo (asiento_id, movimiento_caja_id) VALUES (900, 4444)")

    # Y la segunda barrera, sin foto previa: la caja nueva contra la tabla vieja de la misma base.
    assert comparar_caja.comparar(_foto(engine, "legado"), _foto(engine, "motor")) == []

    # El producto lee como antes: el ORM sobre la unión, los saldos por los dos caminos de F4 y los reportes.
    sesion.expire_all()
    m = sesion.get(MovimientoCaja, 7)
    assert (m.id, m.importe, m.fecha, m.tipo, m.medio_pago, m.anulado) == (
        7, Decimal("123456789012.34"), date(2026, 7, 8), TipoMovimientoCaja.INGRESO, MedioPago.OTRO, False)
    assert m.tercero_id == 2 and m.recibo == "R-0001"
    assert sesion.get(MovimientoCaja, 9).anulado is True
    for tercero, rol in ((1, "cliente"), (2, "fletero"), (2, "proveedor"), (3, "cliente"), (3, "fletero"),
                         (4, "proveedor")):
        rol = RolCuenta(rol)
        assert cuentas.saldo(sesion, tercero, rol) == cuentas.saldo_recorriendo(sesion, tercero, rol)
        asientos = antes["cuentas"][f"{tercero}|{rol.value}"]
        assert cuentas.saldo(sesion, tercero, rol) == Decimal(asientos["saldo_por_la_base"])

    # El reporte de caja del producto da lo que dice la siembra, anulados afuera.
    por_reporte = {(r["tipo"].value, r["medio_pago"].value): (r["movimientos"], r["importe"])
                   for r in servicio_de_reportes.caja(sesion, None, None)}
    vigentes = {(tipo, medio): v for (tipo, medio, anulado), v in _esperado(movimientos).items() if not anulado}
    assert por_reporte == vigentes


def test_la_0032_es_idempotente_y_completa_una_base_a_medias(base_de_antes):
    engine, _ = base_de_antes
    antes = _foto(engine)
    _alembic("0032", subir=True)

    migracion = _cargar_migracion()
    with engine.begin() as con:
        # Correrla de nuevo sobre lo ya migrado no copia nada, no duplica y no cambia un solo dato.
        assert migracion.copiar_a_motor(con, LEGADO) == {"movimientos": 42, "copiados": 0, "ya_estaban": 42}
    assert comparar_caja.comparar(antes, _foto(engine)) == []

    # Una base a medias: se pierden unas filas (sin tercero, que ninguna cuenta referencia) de la copia nueva.
    with engine.begin() as con:
        perdidas = [8, 45]
        _sql(con, "DELETE FROM movimientos_caja_cargo WHERE movimiento_id = ANY(:i)", i=perdidas)
        _sql(con, "DELETE FROM caja_movimientos WHERE id = ANY(:i)", i=perdidas)
    with engine.begin() as con:
        assert migracion.copiar_a_motor(con, LEGADO) == {"movimientos": 42, "copiados": 2, "ya_estaban": 40}
    assert comparar_caja.comparar(antes, _foto(engine)) == []
    with engine.begin() as con:
        assert migracion.copiar_a_motor(con, LEGADO)["copiados"] == 0


def test_la_0032_se_niega_si_un_id_esta_ocupado_y_no_toca_nada(base_de_antes):
    engine, _ = base_de_antes
    with engine.begin() as con:
        # Otra fila del motor ocupa el id 7: no es la copia de nada.
        _sql(con, "INSERT INTO caja_movimientos (id, fecha, tipo, concepto, monto) "
                  "VALUES (7, '2026-01-01', 'ingreso', 'De otro', 1)")
    antes = _foto(engine)

    with pytest.raises(RuntimeError, match=r"1 ids de movimientos_caja ya están ocupados.*\[7\]"):
        _alembic("0032", subir=True)

    with engine.connect() as con:
        assert _sql(con, "SELECT to_regclass('movimientos_caja_cargo')").scalar() is None
        assert _sql(con, "SELECT to_regclass('movimientos_caja_legado')").scalar() is None
        assert _sql(con, "SELECT count(*) FROM caja_movimientos").scalar() == 1
    assert comparar_caja.comparar(antes, _foto(engine)) == []   # sigue en la `0031`, igual que antes


def test_la_0032_se_niega_sin_la_caja_del_motor(base_de_antes):
    """Una instancia con el motor viejo (sin el `origen` de la caja del nodo) no se toca."""
    engine, _ = base_de_antes
    with engine.begin() as con:
        _sql(con, "DROP INDEX idx_caja_movimientos_origen")
        _sql(con, "ALTER TABLE caja_movimientos DROP COLUMN origen")
    try:
        with pytest.raises(RuntimeError, match="origen"):
            _alembic("0032", subir=True)
        with engine.connect() as con:
            assert _sql(con, "SELECT to_regclass('movimientos_caja')").scalar() is not None
            assert _sql(con, "SELECT to_regclass('movimientos_caja_cargo')").scalar() is None
    finally:   # como estaba, para que el resto de la suite (y el cierre de este fixture) suban a `head`
        with engine.begin() as con:
            _sql(con, "ALTER TABLE caja_movimientos ADD COLUMN origen TEXT")
            _sql(con, "CREATE UNIQUE INDEX idx_caja_movimientos_origen ON caja_movimientos (origen, origen_id) "
                      "WHERE origen IS NOT NULL")


def test_la_0032_se_baja_si_la_caja_no_cambio_y_se_niega_si_cambio(base_de_antes):
    engine, _ = base_de_antes
    antes = _foto(engine)
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    previo = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    try:
        command.upgrade(cfg, "0032")
        # Anular algo después de migrar: lo nuevo no está en la tabla vieja, no hay vuelta honesta.
        with engine.begin() as con:
            _sql(con, "UPDATE caja_movimientos SET anulado = 1 WHERE id = 1")
        with pytest.raises(RuntimeError, match="corregidos o anulados"):
            command.downgrade(cfg, "0031")
        with engine.begin() as con:
            _sql(con, "UPDATE caja_movimientos SET anulado = 0 WHERE id = 1")
            # Y uno cargado después tampoco.
            _sql(con, "INSERT INTO caja_movimientos (fecha, tipo, concepto, monto) "
                      "VALUES ('2026-10-01', 'ingreso', 'Nuevo', 5)")
            nuevo = _sql(con, "SELECT max(id) FROM caja_movimientos").scalar()
            _sql(con, "INSERT INTO movimientos_caja_cargo (movimiento_id) VALUES (:i)", i=nuevo)
        with pytest.raises(RuntimeError, match="cargados después"):
            command.downgrade(cfg, "0031")
        with engine.begin() as con:
            _sql(con, "DELETE FROM movimientos_caja_cargo WHERE movimiento_id = :i", i=nuevo)
            _sql(con, "DELETE FROM caja_movimientos WHERE id = :i", i=nuevo)
        # Sin cambios: baja, y deja la caja propia idéntica a la de antes.
        command.downgrade(cfg, "0031")
    finally:
        if previo is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previo
    assert _foto(engine)["caja_leida_de"] == "propia"
    assert comparar_caja.comparar(antes, _foto(engine)) == []
    with engine.connect() as con:
        assert _sql(con, "SELECT count(*) FROM caja_movimientos").scalar() == 0   # el motor quedó como estaba


# ── La comparación, al revés: tiene que ponerse roja ───────────────────────


@pytest.mark.parametrize("rotura, quedo", [
    ("UPDATE caja_movimientos SET monto = monto + 0.01 WHERE id = 3", "importe"),
    ("UPDATE caja_movimientos SET anulado = 1 - anulado WHERE id = 2", "anulado"),
    ("UPDATE caja_movimientos SET fecha = '2026-07-31' WHERE id = 4", "fecha"),
    ("UPDATE caja_movimientos SET medio_pago = 'cheque' WHERE id = 5 AND medio_pago <> 'cheque'", "medio_pago"),
    ("UPDATE movimientos_caja_cargo SET tercero_id = 4 WHERE movimiento_id = 1", "tercero_id"),
    ("UPDATE movimientos_caja_cargo SET recibo = 'OTRO' WHERE movimiento_id = 1", "recibo"),
    ("UPDATE movimientos_cuenta_cargo SET movimiento_caja_id = NULL WHERE asiento_id = 102", "vínculo"),
    ("UPDATE cc_asientos SET haber = haber + 0.01 WHERE id = 101", "libro"),
    ("DELETE FROM movimientos_caja_cargo WHERE movimiento_id = 8", "falta una fila"),
    ("UPDATE caja_movimientos SET monto = 1.005 WHERE id = 2", "sub-centavo"),
])
def test_la_comparacion_muerde(base_de_antes, rotura, quedo):
    """Si la migración perdiera o cambiara cualquiera de estas cosas, `comparar` lo diría. Sin esto el
    «iguales» de arriba podría ser un control que nunca mira."""
    engine, _ = base_de_antes
    antes = _foto(engine)
    _alembic("0032", subir=True)
    assert comparar_caja.comparar(antes, _foto(engine)) == []
    with engine.begin() as con:
        con.execute(text(rotura))
    diferencias = comparar_caja.comparar(antes, _foto(engine))
    assert diferencias, f"la rotura «{quedo}» no se notó"


def test_el_cli_foto_comparar_y_contra_legado(base_de_antes, tmp_path, capsys):
    engine, _ = base_de_antes
    archivo = tmp_path / "caja-antes.json"
    assert comparar_caja.main(["foto", "--salida", str(archivo)]) == 0
    assert json.loads(archivo.read_text())["caja_leida_de"] == "propia"

    _alembic("0032", subir=True)
    capsys.readouterr()
    assert comparar_caja.main(["comparar", "--antes", str(archivo), "--salida", str(tmp_path / "despues.json")]) == 0
    salida = capsys.readouterr().out
    assert "IGUALES" in salida and "caja leída de: motor" in salida and "caja leída de: propia" in salida
    assert comparar_caja.main(["contra-legado"]) == 0

    with engine.begin() as con:
        _sql(con, "UPDATE caja_movimientos SET monto = monto + 1 WHERE id = 3")
    assert comparar_caja.main(["comparar", "--antes", str(archivo)]) == 1
    assert "DISTINTAS" in capsys.readouterr().out
    assert comparar_caja.main(["contra-legado"]) == 1


def test_la_foto_no_puede_escribir(base_de_antes):
    """La herramienta del operador abre la transacción de sólo lectura: ni a propósito escribe."""
    engine, _ = base_de_antes
    with engine.connect() as con:
        comparar_caja.foto(con)
        with pytest.raises(Exception, match="read-only"):
            _sql(con, "DELETE FROM movimientos_caja")


def _cargar_migracion():
    """La revisión `0032` como módulo (su nombre empieza con un número: no se puede importar a secas)."""
    import importlib.util

    ruta = RAIZ / "migrations" / "versions" / "0032_caja_en_el_motor.py"
    spec = importlib.util.spec_from_file_location("migracion_0032", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo
