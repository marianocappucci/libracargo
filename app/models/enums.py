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


class AmbienteArca(enum.Enum):
    """Los dos ambientes de ARCA.

    Homologacion no emite comprobantes fiscales: es donde se prueba el armado
    sin consecuencias. El default de una instancia nueva es este, para que
    habilitar produccion sea siempre un acto deliberado.
    """

    HOMOLOGACION = "homologacion"
    PRODUCCION = "produccion"


class AccionAuditoria(enum.Enum):
    ALTA = "alta"
    MODIFICACION = "modificacion"
    BAJA = "baja"
