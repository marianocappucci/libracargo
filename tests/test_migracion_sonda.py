"""La espera del MariaDB efímero de la migración no puede dar por listo al temporal.

La imagen `mariadb` arranca primero un servidor TEMPORAL que sólo escucha en el
socket local (sin TCP), lo apaga, y recién después levanta el definitivo. Una sonda
por el socket puede pasar contra el temporal justo antes de que lo apaguen, y la
restauración siguiente muere con `ERROR 2002 ... mysqld.sock` (libracargo#347,
2026-10-10). Acá se simula ese servidor con un `docker` falso: no hace falta Docker,
así que corre en cualquier máquina.
"""

from __future__ import annotations

import subprocess

from migracion import cargar


class _DockerFalso:
    """Un contenedor cuyo servidor temporal contesta por socket y el definitivo, también por TCP."""

    def __init__(self, sondas_antes_del_definitivo: int):
        self.faltan = sondas_antes_del_definitivo
        self.sondas = []

    def __call__(self, *args, entrada=None, texto=True):
        def cp(codigo=0, salida=""):
            return subprocess.CompletedProcess(args, codigo, salida, "")

        if args[0] == "run":
            return cp()
        if args[0] == "port":
            return cp(salida="0.0.0.0:32769\n")
        if args[0] == "inspect":
            return cp(salida="true\n")
        if args[0] == "exec" and "SELECT 1" in args:
            por_tcp = "--protocol=tcp" in args
            self.sondas.append("tcp" if por_tcp else "socket")
            if por_tcp:
                if self.faltan > 0:        # todavía está el temporal (o el hueco)
                    self.faltan -= 1
                    return cp(1)
                return cp(salida="1\n")
            return cp(salida="1\n")        # el temporal sí contesta por el socket
        return cp()


def test_la_espera_no_da_por_listo_al_servidor_temporal(monkeypatch):
    falso = _DockerFalso(sondas_antes_del_definitivo=3)
    monkeypatch.setattr(cargar, "_docker", falso)
    monkeypatch.setattr(cargar.time, "sleep", lambda _s: None)

    contenedor, puerto = cargar.levantar_mariadb(nombre="libracargo-legado-sonda")

    assert (contenedor, puerto) == ("libracargo-legado-sonda", 32769)
    # Si volviera la sonda por socket, devolvería a la primera: el temporal contesta.
    assert falso.sondas == ["tcp"] * 4, falso.sondas
