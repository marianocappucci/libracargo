"""`libraauth-migrar` tiene que encontrar SU base con el entorno real del contenedor.

El 2026-09-16 la adopción de la cadena de LibraAuth tiró el `-dev`:
`libraauth-migrar --prefijo libracargo --base dominio` salió con `SinURL`, porque
`DATABASE_URL` a secas no figuraba en los nombres que conoce
`libracore.db.url_de_instancia`. Los tests de declaración pasaban: miraban la
tupla, no a dónde resolvía. Éste resuelve con los nombres de variable que
**declara el `docker-compose.yml`**, así que un renombre de un lado o del otro
lo pone en rojo.

No se conecta a nada: `url_de_auth` y `url_de_core` sólo leen el entorno.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import requiere_core_en_el_dominio

PREFIJO = "libracargo"
COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _entorno_del_compose() -> dict[str, str]:
    """Las variables de base del servicio `-dev`, con la base real de su URL y
    un host de mentira. Se leen del archivo, no se copian acá."""
    texto = COMPOSE.read_text(encoding="utf-8")
    entorno = {}
    for nombre, url in re.findall(r"^\s*-\s*([A-Z_]*DATABASE_URL)=(.+?)\s*$", texto, re.M):
        # la URL trae `${...:?hay que definirla en el .env}`, con espacios
        base = url.rsplit("/", 1)[-1]
        entorno[nombre] = f"postgresql://u:p@h/{base}"
    return entorno


def test_el_compose_declara_UNA_sola_variable_de_base():
    """Desde la ADR-054 el compose de dev no lleva la variable del core: el schema
    del motor vive en la base del dominio (ADR-029) y `DATABASE_URL` alcanza."""
    entorno = _entorno_del_compose()
    assert set(entorno) == {"DATABASE_URL"}
    assert entorno["DATABASE_URL"].endswith(f"/{PREFIJO}")


def test_libraauth_migrar_resuelve_la_base_del_DOMINIO():
    """Las seis tablas de auth viven en el dominio (medido el 2026-09-16)."""
    from libraauth.migrar import url_de_auth

    url = url_de_auth(PREFIJO, "dominio", entorno=_entorno_del_compose())
    assert url.rsplit("/", 1)[-1] == PREFIJO


@requiere_core_en_el_dominio
def test_libracore_migrar_resuelve_la_base_del_dominio_con_el_entorno_del_compose():
    """`libracore-migrar` toma la base del dominio cuando no hay variable del core
    (`libracargo` en `_UNA_SOLA_BASE`, libracore >= v1.190.1). Con el entorno que
    declara el compose —sin la variable— resuelve `DATABASE_URL`, no otra base."""
    from libracore.migrar import url_de_core

    url = url_de_core(PREFIJO, entorno=_entorno_del_compose())
    assert url.rsplit("/", 1)[-1] == PREFIJO


def test_la_variable_del_core_puesta_gana_sobre_el_dominio():
    """Control, y es la forma de Suitrans: con la variable puesta (igual a la del
    dominio) `libracore-migrar` la usa, con cualquier libracore."""
    from libracore.migrar import url_de_core

    entorno = {"DATABASE_URL": f"postgresql://u:p@h/{PREFIJO}",
               f"{PREFIJO.upper()}_LIBRACORE_DATABASE_URL": f"postgresql://u:p@h/{PREFIJO}"}
    assert url_de_core(PREFIJO, entorno=entorno).rsplit("/", 1)[-1] == PREFIJO


def test_el_command_de_dev_migra_auth_con_base_dominio():
    texto = COMPOSE.read_text(encoding="utf-8")
    assert f"libraauth-migrar upgrade --prefijo {PREFIJO} --base dominio" in texto
