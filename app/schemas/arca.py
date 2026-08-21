"""Esquemas de la configuración de ARCA.

🔑 **Ningún esquema de salida tiene el certificado ni la clave.** No es un
descuido: la clave privada no tiene por qué salir de la base nunca, y un
`response_model` que la incluyera la pondría en el JSON de una pantalla que
cualquier administrador abre. Lo que sale son **datos sobre** los archivos.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AmbienteArca


class ArcaIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ambiente: AmbienteArca = AmbienteArca.HOMOLOGACION
    habilitado: bool = False


class CertificadoOut(BaseModel):
    """Lo legible de un certificado. Nada de esto es secreto."""

    nombre: str | None
    sujeto: str
    emisor: str
    #: Nulo sólo si el archivo guardado no se puede leer.
    vence: datetime | None
    vencido: bool
    dias_para_vencer: int


class ArcaOut(BaseModel):
    razon_social_id: int
    razon_social: str
    #: De `razones_sociales`: el certificado de ARCA es de un CUIT, y es este.
    cuit: str | None
    punto_venta: int
    ambiente: AmbienteArca
    habilitado: bool
    certificado: CertificadoOut | None
    tiene_clave: bool
    clave_nombre: str | None
    #: Si el certificado y la clave son pareja. `None` cuando falta alguno.
    #: 🔑 Es el dato que no se puede deducir mirando los nombres de archivo, y
    #: el error de armado más común: certificado viejo con clave nueva.
    coinciden: bool | None
