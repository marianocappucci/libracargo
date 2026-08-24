"""Órdenes de carga, comprobantes y gastos de proveedor — el núcleo del negocio."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Anotable, Auditable, Base
from app.models.enums import EstadoOrden, TipoComprobante


class Comprobante(Base, Auditable):
    """Factura o nota de crédito emitida por una de las razones sociales propias.

    La numeración es única por razón social, tipo y punto de venta — en el
    legado la PK era `(factura_nro, factura_razonsocial)`, que no contemplaba
    ni el tipo ni el punto de venta.
    """

    __tablename__ = "comprobantes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razon_social_id: Mapped[int] = mapped_column(
        ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[TipoComprobante] = mapped_column(
        Enum(TipoComprobante, name="tipo_comprobante",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    punto_venta: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )

    # NUMERIC, nunca float: el legado sumaba `float(10,2)` sobre 22.588
    # movimientos y arrastraba el error de redondeo a los saldos.
    neto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    anulado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    #: El CAE que devolvio ARCA. `None` es el estado normal de todo lo migrado
    #: --- 741 comprobantes de un sistema que facturaba por afuera --- y de todo
    #: lo que se registre a mano mientras la razon social no tenga ARCA activo.
    #: No es una fila incompleta.
    cae: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cae_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Cuando se le pidio, que no es la fecha del comprobante: un reintento
    #: despues de que ARCA estuvo caido deja las dos separadas.
    cae_solicitado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "razon_social_id",
            "tipo",
            "punto_venta",
            "numero",
            name="uq_comprobantes_numeracion",
        ),
        CheckConstraint("neto >= 0 AND iva >= 0 AND total >= 0", name="ck_comprobantes_signos"),
        Index("ix_comprobantes_fecha", "fecha"),
        Index("ix_comprobantes_cliente_fecha", "cliente_id", "fecha"),
        Index("ix_comprobantes_origen_legado", "origen_legado", unique=True),
    )


class OrdenCarga(Base, Auditable, Anotable):
    """Una orden de transporte: el cliente la pide, el fletero la hace.

    La comisión es la diferencia con la que vive la agencia, y por eso es una
    columna propia y no un margen que se recalcula.
    """

    __tablename__ = "ordenes_carga"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )
    origen_id: Mapped[int] = mapped_column(
        ForeignKey("localidades.id", ondelete="RESTRICT"), nullable=False
    )
    destino_id: Mapped[int] = mapped_column(
        ForeignKey("localidades.id", ondelete="RESTRICT"), nullable=False
    )
    fletero_id: Mapped[int | None] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=True
    )
    chofer_id: Mapped[int | None] = mapped_column(
        ForeignKey("choferes.id", ondelete="RESTRICT"), nullable=True
    )
    vehiculo_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehiculos.id", ondelete="RESTRICT"), nullable=True
    )
    tipo_carga_id: Mapped[int | None] = mapped_column(
        ForeignKey("tipos_carga.id", ondelete="RESTRICT"), nullable=True
    )

    remito: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # En el legado la cantidad era `varchar(20)` y no se podía totalizar.
    # `cantidad_legado` conserva el texto original cuando no parsea a número.
    cantidad: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cantidad_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    tarifa: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    alicuota_iva: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("21.00")
    )
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    comision: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    estado: Mapped[EstadoOrden] = mapped_column(
        Enum(EstadoOrden, name="estado_orden",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=EstadoOrden.PENDIENTE,
    )
    razon_social_id: Mapped[int | None] = mapped_column(
        ForeignKey("razones_sociales.id", ondelete="RESTRICT"), nullable=True
    )
    # FK real, no el número de factura copiado a mano como hacía el legado.
    comprobante_id: Mapped[int | None] = mapped_column(
        ForeignKey("comprobantes.id", ondelete="RESTRICT"), nullable=True
    )
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    comprobante: Mapped[Comprobante | None] = relationship("Comprobante", lazy="raise")

    __table_args__ = (
        # El escape por `origen_legado` es para el histórico migrado: hay 33
        # órdenes del legado que salen y llegan a la misma localidad, y son
        # viajes reales. La regla sigue rigiendo para toda alta nueva. Ver
        # ADR-015 y la migración 0003.
        CheckConstraint(
            "origen_id <> destino_id OR origen_legado IS NOT NULL",
            name="ck_ordenes_origen_distinto_destino",
        ),
        CheckConstraint("tarifa >= 0 AND total >= 0", name="ck_ordenes_importes_no_negativos"),
        CheckConstraint(
            "alicuota_iva >= 0 AND alicuota_iva <= 100", name="ck_ordenes_alicuota"
        ),
        # Una orden facturada tiene comprobante; una pendiente no puede tenerlo.
        CheckConstraint(
            "(estado = 'facturada' AND comprobante_id IS NOT NULL) "
            "OR (estado <> 'facturada' AND comprobante_id IS NULL)",
            name="ck_ordenes_facturada_con_comprobante",
        ),
        Index("ix_ordenes_fecha", "fecha"),
        Index("ix_ordenes_cliente_fecha", "cliente_id", "fecha"),
        Index("ix_ordenes_fletero_fecha", "fletero_id", "fecha"),
        Index("ix_ordenes_estado", "estado"),
        Index("ix_ordenes_comprobante", "comprobante_id"),
        Index("ix_ordenes_remito", "remito"),
        Index("ix_ordenes_origen_legado", "origen_legado", unique=True),
    )


class GastoDeProveedor(Base, Auditable):
    """Un gasto que la agencia le paga a un proveedor y le descuenta a un fletero.

    Es el bloque **COMPROBANTES PROVEEDORES** del sistema viejo, y el nombre que
    tenía ahí engañaba: no son facturas de compra. Medido sobre los 3.347
    registros del legado antes de modelar nada:

    | | |
    |---|---:|
    | Gastos (debe del proveedor) | **2.799** |
    | Imputados a un fletero | **2.799 de 2.799** |
    | Con número de comprobante | **0 de 2.799** |
    | Tipo usado | **"Remito"** en 2.806 |

    De ahí salen las tres decisiones del modelo:

    1. **El fletero es obligatorio.** No es un campo que a veces se completa: es
       la razón de ser del documento. Un gasto que no se le descuenta a nadie es
       un gasto general de la agencia y va por caja, que ya lo soporta.
    2. **El número de comprobante es opcional.** El campo existe en el legado y
       **nadie lo usó nunca**; hacerlo obligatorio sería inventar un requisito.
    3. **No es un documento fiscal**: no lleva tipo A/B/C, ni punto de venta, ni
       IVA discriminado. Cuando eso haga falta —con ARCA andando y el IVA compras
       importando— es otro documento, no este con campos agregados.

    ## Los dos asientos

    Un gasto mueve **dos cuentas en la misma transacción**: el proveedor al
    **debe** —lo que se le debe— y el fletero al **haber** —se le descuenta de
    lo que la agencia le debe—. En el legado eran dos `INSERT` sueltos, uno en
    `ctacteprov` y otro en `fleteroctacte`, y si el segundo fallaba el primero
    ya estaba grabado.

    ## Lo migrado no se convierte en gastos

    Los 2.799 del legado ya están como movimientos de cuenta, con los saldos
    validados por el gate de F6. Crearles un documento retroactivo duplicaría el
    importe salvo que además se reescribieran esos movimientos, y eso es tocar
    historia conciliada para ganar nada. **Esta tabla arranca vacía** y sólo
    tiene lo que se carga de acá en adelante.
    """

    __tablename__ = "gastos_de_proveedor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    proveedor_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )
    #: Obligatorio, ver arriba.
    fletero_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )

    #: El número del remito o la factura del proveedor, si lo tiene. `String` y
    #: no `Integer` como el legado: un remito es `0001-00012345`, no un entero.
    comprobante: Mapped[str | None] = mapped_column(String(30), nullable=True)
    #: `Text` y no `varchar(110)`: en el legado esa columna truncaba en silencio.
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)

    importe: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    anulado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Los 2.799 del legado, convertidos a documentos por la migración `0009`.
    #: No se re-asentaron: el documento apunta a los dos movimientos que ya
    #: estaban, así que los saldos no se movieron.
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint("importe > 0", name="ck_gastos_importe_positivo"),
        # Un gasto que el proveedor le cobra a la agencia para descontárselo a
        # sí mismo no significa nada, y es un error de carga fácil: los dos
        # desplegables tienen los mismos terceros adentro.
        #
        # ⚠️ Pero en los datos reales pasa **43 veces**, así que la regla se
        # condiciona a `origen_legado IS NULL`: rige para toda alta nueva y no
        # para el histórico. Mismo criterio que ADR-015.
        CheckConstraint("proveedor_id <> fletero_id OR origen_legado IS NOT NULL",
                        name="ck_gastos_partes_distintas"),
        Index("ix_gastos_origen_legado", "origen_legado", unique=True),
        Index("ix_gastos_fecha", "fecha"),
        Index("ix_gastos_proveedor_fecha", "proveedor_id", "fecha"),
        Index("ix_gastos_fletero_fecha", "fletero_id", "fecha"),
    )
