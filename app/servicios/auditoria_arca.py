"""Quién tocó las credenciales de ARCA, conectado al hook del motor.

El router de ARCA es de [[libracore]] desde el 2026-09-02, y con él se fue el
registro que el router propio de este producto escribía en cada alta, upload y
borrado. `build_arca_router` acepta `al_cambiar` desde `v1.74.0` justamente para
que no se pierda: esto es la punta de este lado.

## 🔴 Este asiento NO va en la misma transacción que el cambio

`app/servicios/auditoria.py` abre diciendo que el asiento va en la **misma**
transacción que la modificación, y que si la auditoría falla tiene que fallar la
operación. Es la regla correcta para las tablas de este producto, y **acá no se
puede cumplir**: el cambio es un archivo escrito en `CERTS_DIR` y una fila en la
base de LibraCore, las dos cosas ya consumadas cuando el hook corre. Fallar
después dejaría al operador creyendo que la subida no salió, con el certificado
puesto.

Así que esto abre su propia sesión y commitea aparte. El peor caso pasa a ser
**un cambio aplicado sin su registro** —que el motor loguea con `exception`— y
nunca un registro sin cambio, que es la mitad que rompería el log como
evidencia. Está escrito acá y no sólo en el motor porque quien lea la tabla de
auditoría tiene que saber que estas cuatro filas son best-effort y el resto no.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models.enums import AccionAuditoria
from app.servicios import auditoria

#: La entidad con la que quedan los asientos. No es una tabla de este producto
#: —vive en la base de LibraCore— y por eso no lleva `entidad_id`: el `id` de
#: `arca_config` es de otra base y ponerlo acá invitaría a joinear contra algo
#: que no está.
ENTIDAD = "arca_config"

#: Qué es cada acción del motor en el vocabulario de esta tabla. Borrar el par
#: es una baja; el resto modifica la configuración.
ACCIONES = {
    "configurar":  AccionAuditoria.MODIFICACION,
    "certificado": AccionAuditoria.MODIFICACION,
    "clave":       AccionAuditoria.MODIFICACION,
    "borrar":      AccionAuditoria.BAJA,
}


def construir_hook(fabrica_de_sesiones: Callable[[], Any]):
    """El `al_cambiar` que espera `build_arca_router`.

    Toma la fábrica y no una sesión: el router lo llama en cada request, y una
    sesión de larga vida capturada al armar la app se pudre —o se lleva una
    conexión del pool para siempre—.
    """

    def al_cambiar(accion: str, detalle: dict, usuario: Any) -> None:
        # 🔑 Una acción que no conocemos se registra igual, como modificación.
        # El motor puede sumar una quinta antes de que este mapa se entere, y
        # perder el asiento por no tener la clave sería el peor de los dos
        # errores posibles: la fila de más se lee, la que falta no.
        que = ACCIONES.get(accion, AccionAuditoria.MODIFICACION)
        with fabrica_de_sesiones() as sesion:
            auditoria.registrar(
                sesion, usuario if isinstance(usuario, dict) else None,
                ENTIDAD, None, que,
                # `despues` solo: no hay un "antes" que tomar sin volver a leer
                # la configuración desde el motor, y el dato que importa —qué
                # certificado quedó puesto— está en el detalle.
                despues={"accion": accion, **detalle},
            )
            sesion.commit()

    return al_cambiar
