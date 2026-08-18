"""Lo que el esquema nuevo impide y el viejo dejaba pasar.

Cada test acá corresponde a un defecto medido en el sistema legado de
Suitrans, no a una regla inventada.
"""

from __future__ import annotations

import struct
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Comprobante,
    CondicionIVA,
    EstadoOrden,
    Localidad,
    MovimientoCuenta,
    OrdenCarga,
    RazonSocial,
    RolCuenta,
    Tercero,
    TipoComprobante,
)


def _cliente(sesion, nombre="ACOPIO SUR SA"):
    t = Tercero(razon_social=nombre, es_cliente=True,
                condicion_iva=CondicionIVA.RESPONSABLE_INSCRIPTO)
    sesion.add(t)
    sesion.commit()
    return t


def _localidades(sesion):
    a = Localidad(nombre="SUIPACHA")
    b = Localidad(nombre="BAHIA BLANCA")
    sesion.add_all([a, b])
    sesion.commit()
    return a, b


# --------------------------------------------------------------- el dinero

def _como_float_mysql(x: float) -> float:
    """Lo que le pasa a un número al guardarse en un `FLOAT` de MySQL.

    `float(10,2)` **no** es decimal de 10 dígitos con 2 decimales: es un
    float de **precisión simple**, 4 bytes, ~7 dígitos significativos.
    """
    return struct.unpack("f", struct.pack("f", x))[0]


@pytest.mark.parametrize(
    "importe",
    ["1234567.89", "987654.32", "1500000.55", "250000.10"],
)
def test_un_importe_realista_se_guarda_exacto(sesion, importe):
    """El defecto central del legado, y no es el que parecía.

    No hace falta sumar nada para perder plata: con `float(10,2)` de MySQL
    —precisión simple— un importe de siete dígitos **ya entra mal a la base**.
    $1.500.000,55 se guarda como $1.500.000,50: cinco centavos perdidos en
    una sola fila, antes de cualquier cuenta corriente.
    """
    valor = Decimal(importe)
    cliente = _cliente(sesion)
    sesion.add(MovimientoCuenta(
        fecha=date(2026, 1, 1), tercero_id=cliente.id, rol=RolCuenta.CLIENTE,
        concepto="flete", debe=valor, haber=Decimal("0"),
    ))
    sesion.commit()

    guardado = sesion.execute(select(MovimientoCuenta.debe)).scalar_one()
    assert guardado == valor, "NUMERIC tiene que devolver el importe intacto"

    # Y la contraprueba: el mismo importe por el tipo del legado se corrompe.
    degradado = round(_como_float_mysql(float(importe)), 2)
    assert degradado != float(importe), (
        f"{importe} sobrevivió a float32; elegir otro caso para el test"
    )


def test_la_suma_de_una_cuenta_corriente_no_deriva(sesion):
    """Y encima de la pérdida por fila, el error se acumula al sumar.

    Mil asientos de $0,10 tienen que dar exactamente $100,00. Por el camino
    del legado dan $99,999046..., que es lo que arrastra un saldo calculado
    sobre los 22.588 movimientos de la base real.
    """
    cliente = _cliente(sesion)
    for _ in range(1000):
        sesion.add(MovimientoCuenta(
            fecha=date(2026, 1, 1), tercero_id=cliente.id, rol=RolCuenta.CLIENTE,
            concepto="prueba", debe=Decimal("0.10"), haber=Decimal("0"),
        ))
    sesion.commit()

    total = sesion.execute(
        select(func.sum(MovimientoCuenta.debe)).where(
            MovimientoCuenta.tercero_id == cliente.id
        )
    ).scalar_one()
    assert total == Decimal("100.00")
    assert isinstance(total, Decimal)

    acumulado = 0.0
    for _ in range(1000):
        acumulado = _como_float_mysql(acumulado + 0.10)
    assert acumulado != 100.0
    assert abs(acumulado - 100.0) > Decimal("0.0009")


def test_un_asiento_mueve_debe_o_haber_pero_no_los_dos(sesion):
    cliente = _cliente(sesion)
    sesion.add(MovimientoCuenta(
        fecha=date(2026, 1, 1), tercero_id=cliente.id, rol=RolCuenta.CLIENTE,
        concepto="mal", debe=Decimal("10"), haber=Decimal("10"),
    ))
    with pytest.raises(IntegrityError, match="ck_cuenta_debe_o_haber"):
        sesion.commit()


def test_un_asiento_en_cero_tampoco_entra(sesion):
    cliente = _cliente(sesion)
    sesion.add(MovimientoCuenta(
        fecha=date(2026, 1, 1), tercero_id=cliente.id, rol=RolCuenta.CLIENTE,
        concepto="vacio", debe=Decimal("0"), haber=Decimal("0"),
    ))
    with pytest.raises(IntegrityError, match="ck_cuenta_debe_o_haber"):
        sesion.commit()


# ------------------------------------------------- integridad referencial

def test_un_movimiento_no_puede_quedar_huerfano(sesion):
    """El legado no tenía una sola FK: nada impedía un movimiento sin tercero."""
    sesion.add(MovimientoCuenta(
        fecha=date(2026, 1, 1), tercero_id=99999, rol=RolCuenta.CLIENTE,
        concepto="huerfano", debe=Decimal("10"), haber=Decimal("0"),
    ))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_un_tercero_necesita_al_menos_un_rol(sesion):
    sesion.add(Tercero(razon_social="SIN ROL"))
    with pytest.raises(IntegrityError, match="ck_terceros_al_menos_un_rol"):
        sesion.commit()


def test_el_mismo_tercero_puede_ser_fletero_y_proveedor(sesion):
    """`ctacteprov` del legado llevaba a la vez proveedor_id y fletero_id."""
    t = Tercero(razon_social="TRANSPORTES DEL OESTE", es_fletero=True, es_proveedor=True)
    sesion.add(t)
    sesion.commit()

    for rol in (RolCuenta.FLETERO, RolCuenta.PROVEEDOR):
        sesion.add(MovimientoCuenta(
            fecha=date(2026, 1, 1), tercero_id=t.id, rol=rol,
            concepto="flete", debe=Decimal("0"), haber=Decimal("1000.50"),
        ))
    sesion.commit()

    saldos = dict(sesion.execute(
        select(MovimientoCuenta.rol, func.sum(MovimientoCuenta.haber))
        .where(MovimientoCuenta.tercero_id == t.id)
        .group_by(MovimientoCuenta.rol)
    ).all())
    # Dos cuentas separadas para un mismo tercero, que es justo lo que el
    # modelo viejo no podía representar.
    assert saldos == {RolCuenta.FLETERO: Decimal("1000.50"),
                      RolCuenta.PROVEEDOR: Decimal("1000.50")}


# ---------------------------------------------------------------- órdenes

def _orden(sesion, **extra):
    cliente = _cliente(sesion)
    origen, destino = _localidades(sesion)
    datos = dict(fecha=date(2026, 5, 4), cliente_id=cliente.id,
                 origen_id=origen.id, destino_id=destino.id,
                 tarifa=Decimal("100000.00"), iva=Decimal("21000.00"),
                 total=Decimal("121000.00"), comision=Decimal("15000.00"))
    datos.update(extra)
    return OrdenCarga(**datos)


def test_una_orden_no_puede_ir_de_un_lugar_a_si_mismo(sesion):
    cliente = _cliente(sesion)
    origen, _ = _localidades(sesion)
    sesion.add(OrdenCarga(fecha=date(2026, 5, 4), cliente_id=cliente.id,
                          origen_id=origen.id, destino_id=origen.id))
    with pytest.raises(IntegrityError, match="ck_ordenes_origen_distinto_destino"):
        sesion.commit()


def test_una_orden_facturada_exige_comprobante(sesion):
    """En el legado el estado se derivaba de dos banderas sueltas y el
    'número de factura' era un entero copiado a mano, sin FK."""
    sesion.add(_orden(sesion, estado=EstadoOrden.FACTURADA))
    with pytest.raises(IntegrityError, match="ck_ordenes_facturada_con_comprobante"):
        sesion.commit()


def test_una_orden_pendiente_no_puede_tener_comprobante(sesion):
    rs = RazonSocial(nombre="Suitrans", punto_venta=1, codigo_legado=1)
    sesion.add(rs)
    sesion.commit()
    cliente = _cliente(sesion, "OTRO CLIENTE")
    comp = Comprobante(razon_social_id=rs.id, tipo=TipoComprobante.FACTURA_A,
                       punto_venta=1, numero=1, fecha=date(2026, 5, 4),
                       cliente_id=cliente.id, neto=Decimal("1"),
                       iva=Decimal("0.21"), total=Decimal("1.21"))
    sesion.add(comp)
    sesion.commit()

    sesion.add(_orden(sesion, estado=EstadoOrden.PENDIENTE, comprobante_id=comp.id))
    with pytest.raises(IntegrityError, match="ck_ordenes_facturada_con_comprobante"):
        sesion.commit()


def test_la_numeracion_de_comprobantes_no_se_repite(sesion):
    """La PK vieja era `(factura_nro, factura_razonsocial)`: no contemplaba
    ni el tipo de comprobante ni el punto de venta."""
    rs = RazonSocial(nombre="Suitrans", punto_venta=1, codigo_legado=1)
    sesion.add(rs)
    sesion.commit()
    cliente = _cliente(sesion)

    def comp(numero):
        return Comprobante(razon_social_id=rs.id, tipo=TipoComprobante.FACTURA_A,
                           punto_venta=1, numero=numero, fecha=date(2026, 5, 4),
                           cliente_id=cliente.id, neto=Decimal("100"),
                           iva=Decimal("21"), total=Decimal("121"))

    sesion.add(comp(1))
    sesion.commit()
    sesion.add(comp(1))
    with pytest.raises(IntegrityError, match="uq_comprobantes_numeracion"):
        sesion.commit()


# ------------------------------------------------------------ el texto largo

def test_la_descripcion_no_se_trunca(sesion):
    """`fletectacte_tipo_mov` era `varchar(50)` y guardaba
    'origen - destino - cantidad - tipo - remito' concatenado.
    MySQL lo truncaba en silencio."""
    cliente = _cliente(sesion)
    larga = "SUIPACHA - BAHIA BLANCA - 30000 - CEREAL A GRANEL - 0001-00012345"
    assert len(larga) > 50

    sesion.add(MovimientoCuenta(
        fecha=date(2026, 1, 1), tercero_id=cliente.id, rol=RolCuenta.CLIENTE,
        concepto="flete", descripcion=larga,
        debe=Decimal("0"), haber=Decimal("1"),
    ))
    sesion.commit()

    guardada = sesion.execute(select(MovimientoCuenta.descripcion)).scalar_one()
    assert guardada == larga
