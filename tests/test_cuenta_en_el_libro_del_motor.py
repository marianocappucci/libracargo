"""La revisión `0017`: la cuenta corriente pasa al libro de terceros del motor (ADR-031).

Se arma una base en la `0016`, con su tabla `movimientos_cuenta`: asientos de las
tres cuentas, uno con su comprobante, uno de un cobro de caja y uno del legado con
las dos columnas en cero. Después se sube y se mira que los saldos y los vínculos
no se movieron.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import MovimientoCuenta
from app.models.enums import RolCuenta
from app.servicios import cuentas
from tests.test_comprobantes_en_facturas import _alembic


def _sql(con, sentencia: str, **params):
    return con.execute(text(sentencia), params)


@pytest.fixture
def base_de_antes(engine, sesion):
    _alembic("0016")
    try:
        with engine.begin() as con:
            _sql(con, "INSERT INTO terceros (id, razon_social, condicion_iva, es_cliente, es_fletero, "
                      "es_proveedor, activo) VALUES (1, 'ACOPIO SUR SA', 'responsable_inscripto', "
                      "true, false, false, true), (2, 'TRANSPORTES DEL OESTE', "
                      "'responsable_inscripto', false, true, true, true)")
            _sql(con, "INSERT INTO movimientos_caja (id, fecha, tipo, concepto, tercero_id, importe, "
                      "medio_pago) VALUES (1, '2026-08-20', 'ingreso', 'Cobro', 1, 500, 'efectivo')")
            asientos = [
                # id, fecha, tercero, rol, debe, haber, caja, legado
                (1, "2026-08-01", 1, "cliente", "1210.00", "0", None, None),
                (2, "2026-08-20", 1, "cliente", "0", "500.00", 1, None),
                (3, "2026-08-05", 2, "fletero", "0", "4000.00", None, None),
                (4, "2026-08-05", 2, "proveedor", "1500.00", "0", None, None),
                (5, "2023-08-01", 1, "cliente", "0", "0", None, "clientectacte:9"),
            ]
            for id_, fecha, tercero, rol, debe, haber, caja, legado in asientos:
                _sql(con, "INSERT INTO movimientos_cuenta (id, fecha, tercero_id, rol, concepto, debe, "
                          "haber, movimiento_caja_id, origen_legado) VALUES (:id, :fecha, :tercero, "
                          ":rol, 'c', :debe, :haber, :caja, :legado)",
                     id=id_, fecha=fecha, tercero=tercero, rol=rol, debe=debe, haber=haber, caja=caja,
                     legado=legado)
            _sql(con, "SELECT setval(pg_get_serial_sequence('movimientos_cuenta', 'id'), 5)")
        yield engine
    finally:
        sesion.rollback()
        with engine.begin() as con:
            for tabla in ("movimientos_cuenta_cargo", "cc_asientos", "movimientos_cuenta_legado",
                          "movimientos_cuenta", "movimientos_caja", "terceros"):
                if con.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar():
                    _sql(con, f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")
        # Siempre de vuelta a `head` (no hace nada si ya está).
        _alembic("head")


def _saldos(con, tabla):
    return _sql(con, f"SELECT tercero_id, rol::text, sum(debe) - sum(haber) FROM {tabla} "
                     "GROUP BY 1, 2 ORDER BY 1, 2").all()


def test_la_0017_pasa_la_cuenta_al_libro_del_motor_sin_mover_un_saldo(base_de_antes, sesion):
    with base_de_antes.connect() as con:
        antes = _saldos(con, "movimientos_cuenta")
    # Hasta la `0017`: la `0018` borra `movimientos_cuenta_legado`, que acá se mira.
    _alembic("0017", subir=True)

    with base_de_antes.connect() as con:
        assert _saldos(con, "cc_asientos") == antes
        assert _sql(con, "SELECT count(*) FROM movimientos_cuenta_legado").scalar() == 5
        assert _sql(con, "SELECT array_agg(id ORDER BY id) FROM cc_asientos").scalar() == [1, 2, 3, 4, 5]
        assert _sql(con, "SELECT fecha, rol FROM cc_asientos WHERE id = 2").one() == ("2026-08-20", "cliente")
        assert _sql(con, "SELECT movimiento_caja_id FROM movimientos_cuenta_cargo "
                         "WHERE asiento_id = 2").scalar() == 1
        assert _sql(con, "SELECT nextval(pg_get_serial_sequence('cc_asientos', 'id'))").scalar() == 6

    # El producto lee como antes, y escribe por el motor.
    sesion.expire_all()
    m = sesion.get(MovimientoCuenta, 2)
    assert (m.rol, m.haber, m.movimiento_caja_id, m.fecha.isoformat()) == (
        RolCuenta.CLIENTE, Decimal("500.00"), 1, "2026-08-20")
    assert cuentas.saldo(sesion, 1, RolCuenta.CLIENTE) == Decimal("710.00")
    assert cuentas.saldo(sesion, 1, RolCuenta.CLIENTE) == cuentas.saldo_recorriendo(sesion, 1, RolCuenta.CLIENTE)
    nuevo = cuentas.asentar(sesion, fecha=m.fecha, tercero_id=1, rol=RolCuenta.CLIENTE,
                            concepto="Factura", debe=Decimal("90.00"))
    assert nuevo.id == 7  # el 6 lo tomó el `nextval` de arriba: la secuencia siguió
    sesion.commit()
    assert cuentas.saldo(sesion, 1, RolCuenta.CLIENTE) == Decimal("800.00")


def test_la_0017_se_niega_sin_el_libro_del_motor(base_de_antes):
    """Una instancia con el motor viejo no tiene `cc_asientos`: no se toca nada."""
    with base_de_antes.begin() as con:
        _sql(con, "ALTER TABLE cc_asientos RENAME TO cc_asientos_aparte")
    try:
        with pytest.raises(RuntimeError, match="cc_asientos"):
            _alembic("head")
        with base_de_antes.connect() as con:
            assert _sql(con, "SELECT to_regclass('movimientos_cuenta')").scalar() is not None
    finally:
        with base_de_antes.begin() as con:
            _sql(con, "ALTER TABLE cc_asientos_aparte RENAME TO cc_asientos")
