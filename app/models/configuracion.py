"""Los datos de la empresa que usa la instancia."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Auditable, Base


class ConfiguracionEmpresa(Base, Auditable):
    """Una sola fila: quién es la empresa que usa esta instancia.

    Es lo que va en el encabezado de la orden de carga impresa y de los
    comprobantes, y el nombre que se ve debajo del producto en la barra lateral.
    Cada instancia de cliente tiene la suya —es lo que distingue la de Suitrans
    de la de cualquier otro— y por eso vive en la base y no en el `.env`: el
    cliente la edita, no se redespliega para cambiarle el teléfono.

    > 🔑 **`id` fijo en 1, con un `CHECK`.** Sin eso, dos altas dejan dos
    > configuraciones y la aplicación tiene que elegir una: la que quede primera
    > por orden de inserción, que es una forma elegante de que el papel salga con
    > los datos de ayer.
    """

    __tablename__ = "configuracion_empresa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    razon_social: Mapped[str] = mapped_column(String(120), nullable=False)
    nombre_fantasia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cuit: Mapped[str | None] = mapped_column(String(13), nullable=True)
    condicion_iva: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ingresos_brutos: Mapped[str | None] = mapped_column(String(30), nullable=True)
    inicio_actividades: Mapped[str | None] = mapped_column(String(10), nullable=True)

    domicilio: Mapped[str | None] = mapped_column(String(160), nullable=True)
    localidad: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provincia: Mapped[str | None] = mapped_column(String(60), nullable=True)
    codigo_postal: Mapped[str | None] = mapped_column(String(12), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sitio_web: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: Pie de los papeles impresos: condiciones, aclaraciones, lo que el cliente
    #: quiera. Sin límite de largo — la lección del `varchar(50)` del legado.
    pie_de_impresion: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: 🔑 El logo va **en la base y no en el disco del contenedor**: el
    #: contenedor se recrea en cada despliegue y un archivo suelto adentro se
    #: pierde sin que nadie lo note hasta que sale un remito sin logo. Acá viaja
    #: con el `pg_dump` como cualquier otro dato.
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_tipo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    logo_nombre: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_configuracion_una_sola_fila"),
    )
