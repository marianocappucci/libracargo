"""Enums del dominio.

Todos se materializan como tipos `ENUM` de PostgreSQL: el legado los tenía
como texto libre o como banderas booleanas de las que había que derivar el
estado, y eso admite valores que nadie previó.
"""

from __future__ import annotations

import enum


class RolCuenta(enum.Enum):
    """Un mismo tercero puede tener más de una cuenta corriente.

    En el legado eran tres tablas casi idénticas. Que `ctacteprov` llevara a
    la vez `proveedor_id` y `fletero_id` es la prueba de que las entidades
    ya se cruzaban en los datos reales.
    """

    CLIENTE = "cliente"
    FLETERO = "fletero"
    PROVEEDOR = "proveedor"


class EstadoOrden(enum.Enum):
    """Estado explícito, no derivado de dos banderas."""

    PENDIENTE = "pendiente"
    FACTURADA = "facturada"
    ANULADA = "anulada"


class TipoComprobante(enum.Enum):
    FACTURA_A = "factura_a"
    FACTURA_B = "factura_b"
    FACTURA_C = "factura_c"
    NOTA_CREDITO_A = "nota_credito_a"
    NOTA_CREDITO_B = "nota_credito_b"
    NOTA_CREDITO_C = "nota_credito_c"
    #: Factura de Crédito Electrónica MiPyME (FCE): los códigos 201, 206 y 211 de
    #: ARCA.
    FCE_A = "fce_a"
    FCE_B = "fce_b"
    FCE_C = "fce_c"
    #: La nota de crédito de una FCE: 203, 208 y 213. Sólo **parcial** (por menos que el
    #: saldo): anularla entera exige que el comprador la rechace (ADR-028, migración 0014).
    NOTA_CREDITO_FCE_A = "nota_credito_fce_a"
    NOTA_CREDITO_FCE_B = "nota_credito_fce_b"
    NOTA_CREDITO_FCE_C = "nota_credito_fce_c"


class CondicionIVA(enum.Enum):
    RESPONSABLE_INSCRIPTO = "responsable_inscripto"
    MONOTRIBUTO = "monotributo"
    EXENTO = "exento"
    CONSUMIDOR_FINAL = "consumidor_final"
    NO_CATEGORIZADO = "no_categorizado"


class TipoMovimientoCaja(enum.Enum):
    INGRESO = "ingreso"
    EGRESO = "egreso"


class MedioPago(enum.Enum):
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    CHEQUE = "cheque"
    OTRO = "otro"


# `AmbienteArca` vivía acá hasta el 2026-09-02, cuando la configuración de
# ARCA pasó a `arca_config` de LibraCore. Los dos ambientes los declara ahora
# el motor (`arca_router.AMBIENTES`), que además es quien resuelve las URLs
# de WSAA y WSFE a partir de ellos: una copia acá sería un segundo lugar
# donde escribir `homologacion` mal.


class AccionAuditoria(enum.Enum):
    ALTA = "alta"
    MODIFICACION = "modificacion"
    BAJA = "baja"
