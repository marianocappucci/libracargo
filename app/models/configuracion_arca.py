"""Las credenciales de ARCA de cada razón social propia."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Auditable, Base
from app.models.enums import AmbienteArca


class ConfiguracionArca(Base, Auditable):
    """Certificado, clave y ambiente para facturar electrónicamente.

    ## Por qué cuelga de la razón social y no de la instancia

    El certificado de ARCA es **de un CUIT**, y el CUIT en este modelo es de la
    razón social: `razones_sociales` ya guarda `cuit` y `punto_venta`. Una
    configuración por instancia obligaría a elegir cuál de las razones sociales
    factura, que es exactamente lo que el legado resolvía con un entero
    hardcodeado en el HTML.

    Hoy Suitrans usa una sola razón social, así que en pantalla se ve como un
    formulario y no como una lista. Que el modelo admita varias no cuesta nada
    ahora y evita la migración el día que haga falta.

    ## Por qué el certificado y la clave van en la base

    Es el mismo criterio que el logo del membrete, y por el mismo motivo: el
    backup de esta instancia es **exactamente un dump** (`directorios=[]` en
    `app/main.py`), así que lo que está en la base entra en el ZIP y lo que está
    en disco no. Con las credenciales afuera, restaurar un backup dejaría una
    instancia que **no puede facturar y no lo dice**.

    > ⚠️ La contracara, que hay que saber: el ZIP de backup que el cliente puede
    > descargar **lleva adentro la clave privada**. Es su propia clave y su
    > propio backup —que ya trae todos sus datos—, pero conviene que no viaje
    > por mail.
    """

    __tablename__ = "configuracion_arca"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razon_social_id: Mapped[int] = mapped_column(
        ForeignKey("razones_sociales.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    ambiente: Mapped[AmbienteArca] = mapped_column(
        Enum(AmbienteArca, name="ambiente_arca",
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AmbienteArca.HOMOLOGACION,
    )

    certificado: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    certificado_nombre: Mapped[str | None] = mapped_column(String(160), nullable=True)
    clave: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    clave_nombre: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: Que el par esté cargado no significa que el cliente quiera facturar con
    #: él todavía. La emisión mira esta bandera, no la presencia del archivo.
    habilitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # 🔴 Habilitado sin las dos mitades es una instancia que dice que puede
        # facturar y falla en el primer intento, con un error de ARCA que no
        # habla de la causa. El estado no se puede ni representar.
        CheckConstraint(
            "NOT habilitado OR (certificado IS NOT NULL AND clave IS NOT NULL)",
            name="ck_arca_habilitado_con_credenciales",
        ),
    )
