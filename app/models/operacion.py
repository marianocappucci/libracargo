"""Órdenes de carga, comprobantes y gastos de proveedor — el núcleo del negocio."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    TypeDecorator,
    func,
    join,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column

from app.models.base import Anotable, Auditable, Base
from app.models.enums import CODIGO_ARCA, TIPO_DE_CODIGO, EstadoOrden, EtapaOrden, TipoComprobante

# ── El comprobante vive en `facturas`, la tabla del motor ──────────────────
#
# Hasta la revisión `0016` este producto tenía su propia tabla `comprobantes`.
# Desde ahí el comprobante es **el de la familia**: una fila de `facturas` de
# LibraCore (diseño `libracargo-modelo-normalizado-diseno`, etapa 3b, ADR-030).
# Lo que sólo usa este producto —el tercero con su FK, la marca
# de anulado, el origen en el legado— va en `comprobantes_cargo`, una fila por
# comprobante con el **mismo id**.
#
# `Comprobante` sigue siendo la clase que leen los reportes, el control F5 y las
# pantallas, mapeada sobre la unión de las dos tablas: las consultas de este
# producto no cambiaron. **Lo que cambió es quién escribe `facturas`**: el motor,
# con las funciones que aceptan `conn=` (ADR-025 de LibraCore), dentro de la
# transacción de la sesión. Ver `app/servicios/comprobantes.py`.

#: Las tablas del motor que este producto lee con su ORM, **en un `MetaData`
#: aparte**: las crea y las migra `libracore-migrar`, así que ni `create_all` ni
#: la cadena de Alembic de acá las tocan. Se declaran sólo las columnas que este
#: producto usa.
MOTOR = MetaData()


class _CodigoDeTipo(TypeDecorator):
    """El tipo del comprobante: en `facturas` es el código de ARCA (1, 6, 201...)."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else CODIGO_ARCA[TipoComprobante(value)]

    def process_result_value(self, value, dialect):
        return None if value is None else TIPO_DE_CODIGO[value]


class _Fecha(TypeDecorator):
    """Una fecha que el motor guarda como texto. `''` es «no tiene», igual que `NULL`.

    Lee las dos formas que hay en `facturas`: la ISO (`2026-10-05`) y la de ARCA
    (`20261005`), que es como llega el vencimiento del CAE. Escribe la ISO.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.isoformat() if isinstance(value, date) else value

    def process_result_value(self, value, dialect):
        if not value:
            return None
        if len(value) == 8 and value.isdigit():
            return date(int(value[:4]), int(value[4:6]), int(value[6:]))
        return date.fromisoformat(value[:10])


class _Texto(TypeDecorator):
    """Texto del motor, donde `''` quiere decir «no tiene»: acá se lee `None`."""

    impl = Text
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value or None


class _Dinero(TypeDecorator):
    """Un importe del motor (`NUMERIC` sin escala desde su ADR-024), a dos decimales.

    Sin escala, `1210` y `1210.00` son el mismo número pero no el mismo texto: la
    API y la cuenta corriente siempre mostraron dos decimales.
    """

    impl = Numeric
    cache_ok = True

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value).quantize(Decimal("0.01"))


facturas = Table(
    "facturas", MOTOR,
    Column("id", BigInteger, primary_key=True),
    Column("tipo", _CodigoDeTipo, nullable=False),
    Column("punto_venta", Integer, nullable=False),
    Column("numero", Integer, nullable=False),
    Column("fecha", _Fecha, nullable=False),
    Column("subtotal", _Dinero, nullable=False),
    Column("iva_amount", _Dinero, nullable=False),
    Column("total", _Dinero, nullable=False),
    Column("cae", _Texto),
    Column("cae_vto", _Fecha),
    Column("observaciones", _Texto),
    Column("fch_vto_pago", _Fecha),
    Column("fce_cbu", _Texto),
    Column("fce_transmision", _Texto),
    Column("ambiente", Text),
    Column("emisor_id", Integer),
    Column("anulada_en", _Texto),
)


#: La bandeja de comprobantes por facturar del motor, donde vive la pre factura (ADR-030 de
#: LibraCore). Sólo el `id`: lo propio de la pre factura va en `pre_facturas_cargo`, y lo demás
#: (ítems, cliente, estado) lo lee y lo escribe `libracore.pre_facturas`.
comprobantes_pendientes = Table(
    "comprobantes_pendientes", MOTOR,
    Column("id", BigInteger, primary_key=True),
)


class ComprobanteCargo(Base, Auditable):
    """Lo que sólo este producto sabe de un comprobante. Una fila por cada fila de `facturas`.

    🔑 **`anulado` no es el `anulada_en` del motor**, y por eso se queda acá. En
    este producto un comprobante también queda anulado cuando sus notas de
    crédito lo acreditan entero (ADR-028): sale de los totales de acá, pero
    **sigue en el libro IVA**, junto a sus notas, porque ARCA tiene las dos cosas.
    `anulada_en` sí lo saca de los libros, así que se marca sólo cuando se anula
    un comprobante **sin CAE** (`servicios.comprobantes.anular`).
    """

    __tablename__ = "comprobantes_cargo"

    factura_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(facturas.c.id, ondelete="RESTRICT", name="fk_comprobantes_cargo_factura"),
        primary_key=True, autoincrement=False,
    )
    #: El tercero con su FK. En `facturas` quedan además sus datos fiscales
    #: copiados al emitir, que son los que valen para el libro IVA.
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )
    anulado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Cuándo se le pidió el CAE, que no es la fecha del comprobante: un reintento
    #: después de que ARCA estuvo caído deja las dos separadas.
    cae_solicitado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: A qué comprobante acredita esta nota de crédito. `NULL` en todo lo que no
    #: es una nota. En `facturas` va además como `cbte_asoc_*`, que es lo que
    #: viaja a ARCA; acá es la FK exacta, sin depender de la terna.
    comprobante_asociado_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(facturas.c.id, ondelete="RESTRICT", name="fk_comprobantes_cargo_asociado"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_comprobantes_cargo_asociado", "comprobante_asociado_id"),
        Index("ix_comprobantes_cargo_cliente", "cliente_id"),
        Index("ix_comprobantes_cargo_origen_legado", "origen_legado", unique=True),
    )


_cargo = ComprobanteCargo.__table__


class Comprobante(Base):
    """Factura o nota de crédito emitida por la empresa de la instancia.

    Es la unión de `facturas` (el comprobante de la familia) y `comprobantes_cargo`
    (lo propio). Se **lee** como antes; se **crea, se le guarda el CAE y se
    anula** por `app/servicios/comprobantes.py`, que lo hace con el motor.

    La numeración es única por emisor, ambiente, tipo y punto de venta: la
    garantiza el índice `idx_facturas_numeracion` del motor.
    """

    __table__ = join(facturas, _cargo, facturas.c.id == _cargo.c.factura_id)

    id = column_property(facturas.c.id, _cargo.c.factura_id)
    #: Los nombres de siempre de este producto sobre las columnas del motor.
    neto = column_property(facturas.c.subtotal)
    iva = column_property(facturas.c.iva_amount)
    cae_vencimiento = column_property(facturas.c.cae_vto)
    #: Por qué se emitió la nota. Sólo las notas lo tienen.
    motivo = column_property(facturas.c.observaciones)

    __mapper_args__ = {
        # Los datos de ARCA del comprobante los escribe el motor, no el ORM.
        "exclude_properties": ["ambiente", "anulada_en"],
    }


class PreFacturaCargo(Base):
    """Lo que sólo este producto sabe de una pre factura: el tercero.

    La pre factura vive en `comprobantes_pendientes` del motor (ADR-030 de LibraCore), que guarda al
    cliente como foto y al emisor como el `arca_config` del CUIT de la empresa, o `NULL` si la instancia
    todavía no tiene uno. El tercero es una FK de este producto, que la bandeja del motor no conoce.
    Una fila por pre factura, con el **mismo id**, como `comprobantes_cargo` con `facturas`.
    """

    __tablename__ = "pre_facturas_cargo"

    pre_factura_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(comprobantes_pendientes.c.id, ondelete="RESTRICT",
                   name="fk_pre_facturas_cargo_pre_factura"),
        primary_key=True, autoincrement=False,
    )
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (Index("ix_pre_facturas_cargo_cliente", "cliente_id"),)


class PreFacturaOrden(Base):
    """La reserva de una orden en una pre factura abierta (pendiente, enviada o aceptada).

    🔑 **`orden_id` es la clave primaria**: una orden está en a lo sumo una pre factura abierta, y lo
    dice la base y no sólo el código. La fila existe **mientras la pre factura está abierta**: anular
    la pre factura o facturarla la borra. Así una orden que vuelve a pendientes (porque se anuló el
    comprobante que la facturó) no queda ligada a una pre factura ya cerrada, y se puede reservar de
    nuevo. Qué órdenes tuvo una pre factura cerrada lo dicen sus ítems (`orden_id`) y, si se facturó,
    `ordenes_carga.comprobante_id`.
    """

    __tablename__ = "pre_factura_ordenes"

    orden_id: Mapped[int] = mapped_column(
        ForeignKey("ordenes_carga.id", ondelete="RESTRICT"), primary_key=True, autoincrement=False
    )
    pre_factura_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(comprobantes_pendientes.c.id, ondelete="RESTRICT",
                   name="fk_pre_factura_ordenes_pre_factura"),
        nullable=False,
    )

    __table_args__ = (Index("ix_pre_factura_ordenes_pre_factura", "pre_factura_id"),)


#: El comprobante de apertura del legado (ADR-010): **no es fiscal**, así que no
#: entra en `facturas` (decisión 5 del diseño). Agrupa las órdenes de 2023 que el
#: sistema viejo marcaba facturadas sin factura. Hay uno solo, en Suitrans.
class ComprobanteDeApertura(Base, Auditable):
    __tablename__ = "comprobante_de_apertura"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("terceros.id", ondelete="RESTRICT"), nullable=False
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    neto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    origen_legado: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)


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
    #: La etapa del viaje (ADR-037), aparte del estado de facturación. Nace «asignada»; la `0022` dejó en
    #: «cerrada» todo lo que ya existía, que son viajes hechos.
    etapa: Mapped[EtapaOrden] = mapped_column(
        Enum(EtapaOrden, name="etapa_orden", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=EtapaOrden.ASIGNADA, server_default=EtapaOrden.ASIGNADA.value,
    )
    #: Kilos de la pesada al cargar y del ticket del puerto al descargar (ADR-037). Enteros, como en la CPE.
    #: El neto se guarda porque a veces es lo único que se sabe; si están bruto y tara, el servidor lo calcula.
    kg_bruto_carga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kg_tara_carga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kg_neto_carga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kg_bruto_descarga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kg_tara_descarga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kg_neto_descarga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Los km del viaje y la tarifa por tonelada pactada para este viaje (ADR-038). La tarifa se propone desde el
    #: tarifario de referencia y varía por viaje; **todavía no liquida**: `tarifa` sigue siendo el importe.
    km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tarifa_tonelada: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # FK real, no el número de factura copiado a mano como hacía el legado. Desde
    # la revisión `0016` apunta a `facturas` del motor, donde vive el comprobante.
    comprobante_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey(facturas.c.id, ondelete="RESTRICT",
                               name="fk_ordenes_carga_comprobante"),
        nullable=True,
    )
    #: Las 17 órdenes de 2023 que el legado daba por facturadas sin factura van al
    #: comprobante de apertura, que no es fiscal y no está en `facturas` (ADR-010).
    apertura_id: Mapped[int | None] = mapped_column(
        ForeignKey("comprobante_de_apertura.id", ondelete="RESTRICT"), nullable=True
    )
    origen_legado: Mapped[str | None] = mapped_column(String(40), nullable=True)

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
        # Una orden facturada tiene comprobante —o, si es del legado, el de
        # apertura—; una pendiente no puede tener ninguno de los dos.
        CheckConstraint(
            "(estado = 'facturada' AND (comprobante_id IS NOT NULL) <> (apertura_id IS NOT NULL)) "
            "OR (estado <> 'facturada' AND comprobante_id IS NULL AND apertura_id IS NULL)",
            name="ck_ordenes_facturada_con_comprobante",
        ),
        CheckConstraint(
            "COALESCE(kg_bruto_carga, 0) >= 0 AND COALESCE(kg_tara_carga, 0) >= 0 AND COALESCE(kg_neto_carga, 0) >= 0"
            " AND COALESCE(kg_bruto_descarga, 0) >= 0 AND COALESCE(kg_tara_descarga, 0) >= 0"
            " AND COALESCE(kg_neto_descarga, 0) >= 0",
            name="ck_ordenes_kilos_no_negativos",
        ),
        CheckConstraint("COALESCE(km, 1) >= 1 AND COALESCE(tarifa_tonelada, 0) >= 0",
                        name="ck_ordenes_km_y_tarifa_tonelada"),
        Index("ix_ordenes_fecha", "fecha"),
        Index("ix_ordenes_cliente_fecha", "cliente_id", "fecha"),
        Index("ix_ordenes_fletero_fecha", "fletero_id", "fecha"),
        Index("ix_ordenes_estado", "estado"),
        Index("ix_ordenes_etapa", "etapa"),
        Index("ix_ordenes_comprobante", "comprobante_id"),
        Index("ix_ordenes_apertura", "apertura_id"),
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


class AdjuntoDeOrden(Base):
    """Un archivo adjunto a una orden: la foto del ticket de descarga, un remito escaneado (ADR-037).

    🔑 **En la base y no en el disco**, como el certificado de ARCA y el PDF de la CPE: así entra en el respaldo
    de la instancia sin un paso aparte. Tiene tope de tamaño (`servicios.adjuntos.TAMANIO_MAXIMO`).
    """

    __tablename__ = "ordenes_adjuntos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_carga.id", ondelete="CASCADE"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo_contenido: Mapped[str] = mapped_column(String(100), nullable=False)
    tamanio: Mapped[int] = mapped_column(Integer, nullable=False)
    contenido: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_ordenes_adjuntos_orden", "orden_id"),)
