"""Un límite de tasa del registro no tira la migración: la imagen se baja con reintentos, una vez.

El CI de libracargo#351 y #352 cayó el 2026-10-10 con `Unable to find image ... locally` /
`toomanyrequests: Rate exceeded`: `docker run` baja la imagen si falta, y no reintenta. Acá se simula
el registro con un `docker` falso, así que no hace falta Docker ni red.
"""

from __future__ import annotations

import subprocess

import pytest

from migracion import cargar


class _DockerFalso:
    """Registra cada llamada; `pull` falla las primeras `fallas` veces con el error del registro."""

    def __init__(self, esta_la_imagen: bool, fallas: int = 0):
        self.esta_la_imagen = esta_la_imagen
        self.fallas = fallas
        self.llamadas: list[tuple[str, ...]] = []

    def __call__(self, *args, entrada=None, texto=True):
        self.llamadas.append(args)

        def cp(codigo=0, salida="", error=""):
            return subprocess.CompletedProcess(args, codigo, salida, error)

        if args[:2] == ("image", "inspect"):
            return cp(0 if self.esta_la_imagen else 1)
        if args[0] == "pull":
            if self.fallas > 0:
                self.fallas -= 1
                return cp(1, error="toomanyrequests: Rate exceeded")
            self.esta_la_imagen = True
            return cp()
        if args[0] == "port":
            return cp(salida="0.0.0.0:32769\n")
        if args[0] == "inspect":
            return cp(salida="true\n")
        if args[0] == "exec":
            return cp(salida="1\n")
        return cp()

    def comandos(self) -> list[str]:
        return [a[0] for a in self.llamadas]


@pytest.fixture
def sin_esperas(monkeypatch):
    pausas: list[float] = []
    monkeypatch.setattr(cargar.time, "sleep", pausas.append)
    return pausas


def test_si_la_imagen_ya_esta_no_se_toca_el_registro(monkeypatch, sin_esperas):
    falso = _DockerFalso(esta_la_imagen=True)
    monkeypatch.setattr(cargar, "_docker", falso)

    cargar.asegurar_imagen("mariadb:test")

    assert "pull" not in falso.comandos()


def test_un_limite_de_tasa_transitorio_se_reintenta_con_espera_creciente(monkeypatch, sin_esperas):
    falso = _DockerFalso(esta_la_imagen=False, fallas=2)
    monkeypatch.setattr(cargar, "_docker", falso)

    cargar.asegurar_imagen("mariadb:test")

    assert falso.comandos().count("pull") == 3
    assert sin_esperas == [5, 20]  # crece: el registro necesita aire, no golpes seguidos


def test_si_el_registro_no_cede_falla_con_el_error_del_registro(monkeypatch, sin_esperas):
    falso = _DockerFalso(esta_la_imagen=False, fallas=99)
    monkeypatch.setattr(cargar, "_docker", falso)

    with pytest.raises(RuntimeError, match="toomanyrequests"):
        cargar.asegurar_imagen("mariadb:test")

    assert falso.comandos().count("pull") == cargar.INTENTOS_DE_DESCARGA
    assert len(sin_esperas) == cargar.INTENTOS_DE_DESCARGA - 1  # no duerme después del último


def test_levantar_mariadb_asegura_la_imagen_y_corre_sin_bajarla(monkeypatch, sin_esperas):
    falso = _DockerFalso(esta_la_imagen=False, fallas=1)
    monkeypatch.setattr(cargar, "_docker", falso)

    cargar.levantar_mariadb(imagen="mariadb:test", nombre="libracargo-legado-imagen")

    run = next(a for a in falso.llamadas if a[0] == "run")
    # `--pull=never`: el `run` no le pega al registro; si la imagen falta es porque `asegurar_imagen` falló antes.
    assert "--pull=never" in run
    assert falso.comandos().index("pull") < falso.comandos().index("run")
