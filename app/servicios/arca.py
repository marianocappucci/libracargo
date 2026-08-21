"""Lectura y validación de los archivos de ARCA.

Lo que hace este módulo es **rechazar en la pantalla de configuración lo que si
no fallaría recién al emitir el primer comprobante**, con un error de ARCA que
no habla de la causa. Los tres errores de armado que se ven siempre:

1. Subir el `.csr` —el pedido— en vez del `.crt` que ARCA devolvió.
2. Subir el certificado en el campo de la clave, o al revés.
3. Subir un certificado y una clave que **no son pareja**, porque se generó una
   clave nueva y se subió el certificado viejo.

Los tres se detectan leyendo los archivos, y ninguno se detecta mirando la
extensión.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.x509 import load_pem_x509_certificate


class ArchivoInvalido(ValueError):
    """El archivo no es lo que dice ser. El mensaje va tal cual a la pantalla."""


@dataclass(frozen=True)
class DatosDelCertificado:
    """Lo que se puede mostrar de un certificado sin exponer nada secreto."""

    sujeto: str
    emisor: str
    vence: datetime
    numero_de_serie: str

    @property
    def vencido(self) -> bool:
        return self.vence < datetime.now(UTC)

    @property
    def dias_para_vencer(self) -> int:
        return (self.vence - datetime.now(UTC)).days


def leer_certificado(contenido: bytes) -> DatosDelCertificado:
    """Valida que sea un X.509 PEM y devuelve sus datos legibles.

    El vencimiento es el dato que evita la falla silenciosa: los certificados de
    ARCA duran dos años y el día que vence, la facturación deja de andar sin que
    nadie haya tocado nada.
    """
    try:
        cert = load_pem_x509_certificate(contenido)
    except Exception:
        raise ArchivoInvalido(
            "no parece un certificado PEM. Tiene que ser el .crt que devuelve "
            "ARCA, no el .csr que se le manda"
        ) from None
    return DatosDelCertificado(
        sujeto=cert.subject.rfc4514_string(),
        emisor=cert.issuer.rfc4514_string(),
        vence=cert.not_valid_after_utc,
        numero_de_serie=format(cert.serial_number, "x"),
    )


def leer_clave(contenido: bytes):
    """Valida que sea una clave privada PEM **sin passphrase**.

    Sin passphrase no es una preferencia: el ticket de acceso se pide sin
    intervención de nadie, así que no hay dónde escribirla. Una clave protegida
    se acepta hoy y falla al emitir.
    """
    try:
        return serialization.load_pem_private_key(contenido, password=None)
    except TypeError:
        raise ArchivoInvalido(
            "la clave privada está protegida con contraseña. ARCA se autentica "
            "sin que haya nadie para escribirla: hay que subirla sin passphrase"
        ) from None
    except Exception:
        raise ArchivoInvalido(
            "no parece una clave privada PEM. Es el archivo que se generó junto "
            "con el pedido de certificado, no el certificado"
        ) from None


def son_pareja(certificado: bytes, clave: bytes) -> bool:
    """Si la clave privada corresponde a la pública del certificado.

    🔑 Es el chequeo que ningún nombre de archivo puede dar. Un certificado
    viejo con una clave nueva se ve perfecto en pantalla —los dos archivos son
    válidos— y ARCA rechaza la autenticación con un error genérico.
    """
    publica_del_cert = load_pem_x509_certificate(certificado).public_key()
    publica_de_la_clave = leer_clave(clave).public_key()
    formato = dict(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return publica_del_cert.public_bytes(**formato) == publica_de_la_clave.public_bytes(**formato)
