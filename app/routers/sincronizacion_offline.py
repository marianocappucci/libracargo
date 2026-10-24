"""El central expone la sincronización del nodo offline: `/sync/v1/push`, `/pull`, `/ticket-arca` y `/carga-inicial`.

PR 9 del plan «LibraCargo y LibraClub en la versión de escritorio» (ADR-056). Es el mismo armado que VentaLibra y
LibraClub, con las operaciones de LibraCargo.

## Por qué se monta siempre, y no sólo en las instancias con nodos

El gateo está del otro lado: sin un nodo registrado **no existe ningún secreto válido**, así que en una instancia sin
nodos (Suitrans hoy) las rutas responden 401 a todo. Montarlas condicionalmente agregaría una bandera más que puede
quedar mal puesta, y el modo de fallar sería el peor posible: un nodo instalado que no puede sincronizar contra un
central que «debería» tener el endpoint.

## La conexión es por request

Se le pasa `libracore.db.core.get_connection` —la fábrica del motor— y no una conexión armada: el router abre una por
request (ver `create_sync_router` en LibraEdge). En LibraCargo el dominio y LibraCore son la misma base (ADR-054), así
que esa conexión ve `ordenes_carga`, `caja_movimientos` y `node_identity` a la vez.

## Qué se aplica

Un `Despachador` (libraedge ADR-007) con **todas** las operaciones que un nodo de LibraCargo sube
(`servicios/aplicadores.registrar_en`):

| Operación | De quién es | Qué trae |
|---|---|---|
| `caja.movimiento`, `caja.movimiento_anulado` | LibraCore | el cobro o pago de la caja, con tercero y recibo |
| `cargo.asiento` | LibraCargo | un asiento del libro de cuentas corrientes (alta, corrección o baja) |
| `cargo.orden`, `cargo.gasto`, `cargo.adjunto` | LibraCargo | la foto de la fila (id provisorio si nació en el nodo) |
| `cargo.comprobante` | LibraCargo + LibraCore | la factura con su número y CAE (`facturas_del_nodo`) y lo propio |
| `cargo.carta_porte`, `cargo.carta_porte_pdf` | LibraCargo | la CPE emitida o traída, con su PDF |
| `cargo.tercero` | LibraCargo | el cliente, fletero o proveedor dado de alta en el nodo |
| `cola.pedido` | LibraCore | el estado de un pedido de la cola de ARCA (la web consulta) |

Lo que no tiene aplicador **no se marca aplicado**: va a revisión manual
(`libraedge-central revision listar|reintentar|descartar`, con
`LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador`).

El router además controla la versión del esquema (`version_de_alembic`: 409 si el nodo no está migrado igual que el
central) y le presta al nodo el ticket de ARCA (`libracore.nodo_offline.ta_para_el_nodo`, libraedge ADR-009 y ADR-025):
la clave no sale del VPS. Para `wscpe` (la carta de porte) el par sale de `arca_credenciales_servicio` con la empresa de
este producto.
"""

from libracore.db.core import get_connection
from libracore.nodo_offline import ta_para_el_nodo
from libraedge.sync.api import create_sync_router
from libraedge.sync.despacho import Despachador
from libraedge.sync.esquema import version_de_alembic

from app.servicios import aplicadores
from app.servicios.carga_inicial import carga_inicial_del_central
from app.servicios.emision_arca import EMPRESA_ARCA


def armar_despachador() -> Despachador:
    """Las operaciones que el central de LibraCargo sabe aplicar (ver el docstring del módulo)."""
    return aplicadores.registrar_en(Despachador())


async def prestar_ticket(emisor_id, servicio: str = "wsfe") -> dict:
    """El ticket de ARCA que el central le presta al nodo: `wsfe` con el par de `arca_config` y `wscpe` con el de
    `arca_credenciales_servicio` de la empresa de este producto (libracore ADR-079)."""
    return await ta_para_el_nodo(emisor_id, servicio=servicio, empresa=EMPRESA_ARCA)


despachador = armar_despachador()

router = create_sync_router(
    get_connection, despachador=despachador, version_esquema=version_de_alembic, prestar_ticket=prestar_ticket,
    # `GET /sync/v1/carga-inicial` (libraedge ADR-023): lo que el central ya tenía de autoridad del nodo, que baja al
    # vincular. Autenticada con el secreto del nodo, como push y pull. Ver `servicios/carga_inicial.py`.
    carga_inicial=carga_inicial_del_central,
)
