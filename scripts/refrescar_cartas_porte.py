#!/usr/bin/env python3
"""Refresca solas las Cartas de Porte abiertas, consultando su estado a ARCA. Lo corre el cron del host (ADR-051).

    docker exec libracargo-<instancia> python /app/scripts/refrescar_cartas_porte.py

Trae lo mismo que el botón «Actualizar abiertas»: estado, kilos de descarga y fecha de la última consulta, con el
certificado de la instancia. El trabajo lo hace `app.servicios.refresco_cpe`; este archivo sólo lo arranca.

🔴 **Sólo consulta. No emite ni anula nada**, y no depende de «Emitir Cartas de Porte reales».

🔴 **Apagado por omisión, y por dos llaves.** Instalar la línea del cron no alcanza: además un administrador tiene que
prender «Refrescar solas las cartas de porte abiertas» en Configuración / ARCA. Con el interruptor apagado (o en una
demo, o sin certificado) la corrida termina sin tocar nada y lo dice en una línea. Ver el interruptor es ver si el cron
existe: la pantalla muestra cuándo corrió por última vez.

Cada media hora alcanza: una CPE tarda horas en descargarse, y la corrida toma por lote sólo las que hace más de 15
minutos que no se consultan.

    */30 * * * * docker exec libracargo-<instancia> python /app/scripts/refrescar_cartas_porte.py \
        >> /var/log/libracargo_cpe_refresco.log 2>&1

⚠️ Un cron nuevo lleva su log a `/etc/logrotate.d/libra-crons` (lista explícita, no un glob), y se verifica por las tres
capas que describe el README de LibraClub: a mano, con el `env -i` del cron, y viéndolo disparar solo.

Sale con 0 si corrió, se omitió o había otra corrida en curso (los tres son normales); con 1 si algo se rompió.
"""
from __future__ import annotations

import os
import sys

# 🔴 Corre POR RUTA desde el cron, así que `sys.path[0]` es `/app/scripts` y no `/app`: sin esto no encuentra `app`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libracore.db import core as libracore_core  # noqa: E402

from app import db  # noqa: E402
from app.config import Config  # noqa: E402
from app.servicios import refresco_cpe  # noqa: E402
from app.tiempo import ahora  # noqa: E402


def main() -> int:
    config = Config.desde_entorno()
    db.inicializar(config)
    # El certificado de `wscpe` está en la base de LibraCore, que es otra conexión que la del dominio.
    libracore_core.configure(config.database_url_core)

    with db.fabrica_de_sesiones()() as sesion:
        resultado = refresco_cpe.correr(sesion)

    # Una línea por corrida, con fecha: un script silencioso es indistinguible de uno que no está en el crontab.
    detalle = resultado["motivo"] or refresco_cpe.texto_del_resumen(resultado)
    print(f"[{ahora():%d-%m-%Y %H:%M:%S}] cpe-refresco · {resultado['estado']} · {detalle}")
    for e in resultado["errores"]:
        print(f"    CTG {e['ctg']}: {e['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
