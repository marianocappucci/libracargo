"""La costura de LibraCargo con LibraEdge: lo único del nodo sin conexión que es de este producto (ADR-056).

El nodo es la instancia de LibraCargo que corre en la PC de la oficina y sincroniza con el central (el VPS) por
LibraEdge.
Decisión del humano (2026-10-22): **la oficina con nodo opera y la web consulta.** Órdenes, caja, asientos, facturas y
CPE
se escriben **sólo en el nodo**; en el central esas escrituras contestan 409 `solo_en_el_nodo`. Sin internet el nodo
consulta todo, carga órdenes, opera la caja y las cuentas corrientes, y deja las facturas y las CPE en una cola que se
emite sola al volver la conexión. Lo genérico es de los motores (el aprovisionamiento y el transporte son de LibraEdge,
la
cola de ARCA y la caja del nodo son de LibraCore); acá queda lo declarativo y las costuras.

| Pieza | Qué aporta este producto |
|---|---|
| `aprovisionamiento` | el reparto de autoridad (qué manda el central y qué espeja el nodo) y la oficina como sucursal |
| `GANCHOS_DE_CAJA` | la caja del nodo (alta y anulación) sube como `caja.movimiento`, con lo propio en `extra` |
| `cola()` / `emisores` | las facturas y las CPE sin red: la cola de ARCA, con el ticket prestado del central |
| `encolar_operacion` | las operaciones `cargo.*` (`app/servicios/subida.py` las arma, `aplicadores.py` las aplica) |
| `solo_en_el_nodo` | la guarda del central: 409 si la instancia tiene un nodo vinculado |
| `solo_en_el_central` | la guarda del nodo: los maestros y la configuración los manda el central |

## 🔑 Dos casos que no se pueden confundir

- **Una instancia sin nodo** (Suitrans hoy, la demo, el desarrollo): `nodo()` es `None` y no hay una fila activa en
  `node_identity`. **Nada cambia**: la web opera como siempre, sin 409 y sin outbox. Lo fijan
  `tests/test_nodo_fuera_de_un_nodo.py` y la suite entera.
- **El central de una instancia con nodo vinculado**: `nodo()` es `None` pero `node_identity` tiene un nodo activo. Ahí
  la web consulta, y escribir órdenes, caja, asientos, facturas o CPE da 409 `solo_en_el_nodo`.

## Identidad: `LIBRAEDGE_NODE_ID` (y `LIBRACARGO_EDGE_NODE_ID`)

`nodo()` es `libraedge.identidad.nodo_actual("LIBRACARGO")`: la identidad del nodo, que escribe el instalador. LibraEdge
está incluido en todos los planes (libraedge ADR-014): no hay guarda comercial al registrar (`sin_guarda`). **Hay un
solo
nodo por instancia**: la oficina es la única sucursal que ofrece `listar_sucursales`, y LibraEdge se niega a registrar
un
segundo nodo activo en la misma sucursal.

## Aprovisionar (en el central)

    LIBRAEDGE_APROVISIONAMIENTO=app.offline:aprovisionamiento libraedge-central nodo publicar
    libraedge-central nodo sucursales | registrar <node_id> | estado | dar-de-baja <id>
    LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador libraedge-central revision listar ...
    LIBRAEDGE_CARGA_INICIAL=app.servicios.carga_inicial:aplicar_carga_inicial   (la define el instalador del nodo)
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from libracore.cola_arca import ColaDeArca
from libracore.ganchos_de_caja import GanchosDeCaja
from libracore.nodo_offline import (
    VARIABLE_ESTADO,
    ConexionDelNodo,
    RechazoDelCentral,
    SinConexion,
    esta_en_linea,
    guarda_solo_en_el_central,
)
from libraedge.altas import AltaEnNodo
from libraedge.identidad import nodo_actual

_log = logging.getLogger(__name__)

#: El prefijo de las variables del producto (`LIBRACARGO_DATABASE_URL`, `LIBRACARGO_EDGE_NODE_ID`).
PREFIJO = "LIBRACARGO"

#: El `origen_producto` de la cola de comprobantes (libracore ADR-079) y del candado de cada pedido.
PRODUCTO = "libracargo"

#: La versión de las operaciones propias (`cargo.*`) y de la cola. Una forma nueva de un payload sube esta y registra un
#: manejador más en el `Despachador`; el central no entiende lo que no registró y lo manda a revisión manual.
SCHEMA_VERSION = 1

#: Las operaciones de LibraCargo. La caja usa las del motor (`caja.movimiento`, `caja.movimiento_anulado`) y la cola la
#: suya (`cola.pedido`); todo lo demás es `cargo.<entidad>` y trae la foto de la fila.
TIPO_COLA_PEDIDO = "cola.pedido"
TIPO_CAJA_MOVIMIENTO = "caja.movimiento"
TIPO_CAJA_ANULADO = "caja.movimiento_anulado"

#: La única «sucursal» de la instancia: la oficina. LibraCargo no tiene sucursales (el nodo es **el** puesto de la
#: agencia), pero LibraEdge ata cada nodo a una; ofrecer una sola es lo que hace que la guarda del segundo nodo valga
#: para toda la instancia.
SUCURSAL_UNICA = {"id": "1", "nombre": "Oficina", "activa": True}

#: El reparto de autoridad: qué tablas manda el central y el nodo sólo espeja. **Sólo los nombres**: la clave la lee
#: LibraEdge de la base. Lo que el **nodo** genera —órdenes y sus adjuntos, gastos, comprobantes (`facturas` y
#: `comprobantes_cargo`), la caja (`caja_movimientos` y `movimientos_caja_cargo`), los asientos (`cc_asientos` y
#: `movimientos_cuenta_cargo`), las cartas de porte, la cola de ARCA y la auditoría— **no se publica**: sube como
#: operaciones, y lo que el central tenía al vincular baja una sola vez por la carga inicial
#: (`app/servicios/carga_inicial.py`).
#:
#: 🔴 NO están, a propósito:
#: - `arca_credenciales_servicio` ni ningún certificado o clave: **el ticket de ARCA lo presta el central** (libracore
#:   ADR-074 y ADR-079); la clave privada no sale del VPS. `arca_config` sí: lleva el CUIT, el punto de venta, el
#:   ambiente y las *rutas* de los archivos (que en el nodo no existen ni se usan), no los archivos.
#: - `secretos_instancia` (el almacén cifrado de claves de la instancia), `auth_log` y `envios_email`.
#: - Lo del motor que este producto no usa (`clients`, `productos`, `ventas`, `egresos`...).
TABLAS_DE_REFERENCIA = frozenset({
    # Quién entra y qué ve: los usuarios son los del central (libraauth ADR-027), con la aceptación de los Términos y el
    # gate de módulos; y las cajas del motor (la caja por defecto, a la que apuntan los movimientos).
    "usuarios", "aceptaciones_terminos", "modulos", "cajas",
    # Con qué se emite: la empresa y la configuración de ARCA (CUIT, punto de venta, ambiente).
    "configuracion_empresa", "arca_config",
    # Los maestros: los manda el central.
    "terceros", "localidades", "choferes", "vehiculos", "tipos_carga", "tarifarios", "tarifas_referencia",
    "titulares_cpe", "catalogo_cpe",
})

#: Los maestros que el nodo **no escribe**: LibraEdge les instala una guarda en la base del nodo y un intento de
#: escribirlos da un error claro en vez de pisarse con el espejo en el próximo ciclo. No están `usuarios` ni
#: `aceptaciones_terminos` (el arranque y la aceptación de los Términos hacen un upsert idempotente), `cajas` (el motor
#: asegura una por defecto) ni `catalogo_cpe` (una copia de consulta que se llena sola).
TABLAS_SOLO_LECTURA = frozenset({
    "configuracion_empresa", "arca_config", "modulos", "terceros", "localidades", "choferes", "vehiculos",
    "tipos_carga", "tarifarios", "tarifas_referencia", "titulares_cpe",
})

#: Las altas que el nodo da con un id provisorio negativo y el central reescribe (libraedge ADR-021): los **terceros**
#: (un cliente nuevo que llama a la oficina sin internet). El central le asigna su id (deduplicando por CUIT) y lo baja
#: por el espejo; LibraEdge reapunta lo que lo referenciaba. Las claves foráneas hacia `terceros` las encuentra solo
#: en el catálogo de la base (órdenes, gastos, comprobantes, `cc_asientos`, `movimientos_caja_cargo`...): no hay
#: ninguna referencia sin FK que declarar. Lo demás que nace en el nodo (órdenes, gastos, adjuntos, cartas de porte)
#: tiene su id negativo pero no se espeja: el mapeo lo lleva el central (`servicios/aplicadores.py`).
ALTAS_EN_EL_NODO = (AltaEnNodo("terceros"),)


# ── La identidad y la conexión del nodo ───────────────────────────────────────────────────────────────────────────────


def nodo() -> str | None:
    """El id de este nodo, o `None` si la instancia no es un nodo (el central, o una instalación común).

    Se lee en cada llamada: activar el nodo no exige reiniciar nada y la suite no depende del orden de los tests."""
    return nodo_actual(PREFIJO)


def en_linea() -> bool:
    """Si el nodo ve al central: lo que dice el archivo de estado del proceso del nodo (`LIBRAEDGE_ESTADO`).

    Es la de libracore (ADR-074): el último ciclo sincronizó y la última sincronización buena es reciente. Sin archivo,
    viejo o ilegible, sin conexión. La ruta se lee en cada llamada."""
    return esta_en_linea((os.environ.get(VARIABLE_ESTADO) or "").strip() or None)


#: Lo que LibraCore pregunta antes de salir a ARCA. Fuera de un nodo, nada cambia. Las dos funciones se llaman por
#: nombre en cada pregunta (no se atan al construirla): así un test puede cambiarlas.
CONEXION = ConexionDelNodo(nodo=lambda: nodo(), en_linea=lambda: en_linea())


# ── Quién escribe qué ─────────────────────────────────────────────────────────────────────────────────────────────────

CODIGO_SOLO_EN_EL_NODO = "solo_en_el_nodo"
MENSAJE_SOLO_EN_EL_NODO = (
    "Esta instancia tiene un equipo de escritorio vinculado: esto se carga en el equipo de la oficina "
    "y acá se consulta."
)


class SoloEnElNodo(Exception):
    """La función existe sólo en el nodo: en el central de una instancia con nodo vinculado se consulta. La API la
    contesta 409 con `detalle()`, con la misma forma que `SoloEnElCentral` del motor."""

    codigo = CODIGO_SOLO_EN_EL_NODO

    def __init__(self, mensaje: str = MENSAJE_SOLO_EN_EL_NODO):
        super().__init__(mensaje)
        self.mensaje = mensaje

    def detalle(self) -> dict:
        """El `detail` de la respuesta: `{"codigo", "mensaje"}` (la pantalla muestra `mensaje`)."""
        return {"codigo": self.codigo, "mensaje": self.mensaje}


def hay_nodo_vinculado() -> bool:
    """Si esta instancia tiene un nodo activo registrado (`node_identity`): lo que vuelve «sólo en el nodo» a las
    escrituras del central. **Sin nodo, la web opera como siempre.**

    Lee la base en cada pedido (una fila de una tabla chica, con el índice de la clave): vincular o dar de baja un nodo
    tiene efecto en el acto, sin reiniciar. Una base que todavía no tiene las tablas de LibraEdge (`0033`) no tiene
    nodos."""
    from libracore.db import core
    from libraedge.aprovisionamiento import nodos_activos, tabla_existe

    with core.get_connection() as conn:
        if not tabla_existe(conn, "node_identity"):
            return False
        return nodos_activos(conn) > 0


def solo_en_el_nodo() -> None:
    """Una dependencia de FastAPI: **409 `solo_en_el_nodo` en el central de una instancia con un nodo vinculado**, y
    nada en el nodo, en una instalación común ni en una instancia sin nodo.

        @router.post("", dependencies=[Depends(solo_en_el_nodo)])

    A diferencia de `SinConexion` (409 `sin_conexion`: «probá cuando vuelva internet»), esto no se arregla esperando: la
    web **no tiene** esa función mientras haya un nodo, esté en línea o no."""
    if nodo() is not None:
        return
    if hay_nodo_vinculado():
        raise HTTPException(409, SoloEnElNodo().detalle())


_LECTURAS = frozenset({"GET", "HEAD", "OPTIONS"})


def escritura_solo_en_el_nodo(request: Request) -> None:
    """Como `solo_en_el_nodo`, pero **sólo para lo que escribe**: las lecturas pasan. Es lo que se le pone a un router
    entero cuyos datos manda el nodo (órdenes, caja, gastos, comprobantes): el central los lee y no los cambia."""
    if request.method not in _LECTURAS:
        solo_en_el_nodo()


#: La guarda del nodo: lo que manda el central (maestros, configuración, usuarios, tarifario) el nodo lo lee del espejo
#: y no lo cambia. 409 `solo_en_el_central` en un nodo; nada en el central ni en una instalación común.
solo_en_el_central = guarda_solo_en_el_central(nodo=lambda: nodo())


def escritura_solo_en_el_central(request: Request) -> None:
    """Como `solo_en_el_central`, pero **sólo para lo que escribe**: las lecturas pasan."""
    if request.method not in _LECTURAS:
        solo_en_el_central()


_RUTA_DE_TERCEROS = re.compile(r"^/api/terceros(?:/(?P<id>-?\d+)(?:/roles/[a-z]+)?)?/?$")


def maestros_del_central_salvo_terceros_nuevos(request: Request) -> None:
    """La guarda de los maestros (terceros, localidades, choferes, vehículos, tipos de carga): los manda el central y
    el nodo los lee del espejo, **salvo que da de alta un tercero** (un cliente nuevo que llama a la oficina sin
    internet) y que corrige uno de los que él mismo dio de alta y todavía no bajó con su id definitivo (id negativo).

    Es lo único que el nodo escribe de los maestros (libraedge ADR-021). Todo lo demás, 409 `solo_en_el_central`."""
    if request.method in _LECTURAS or nodo() is None:
        return
    coincide = _RUTA_DE_TERCEROS.match(request.url.path)
    if coincide is not None:
        id_ = coincide.group("id")
        if (request.method == "POST" and id_ is None) or (id_ is not None and int(id_) < 0):
            return
    solo_en_el_central()


# ── Encolar una operación ─────────────────────────────────────────────────────────────────────────────────────────────


def _ahora_utc() -> str:
    return datetime.now(UTC).isoformat()


def encolar_operacion(conn, tipo: str, agregado: str, id_local: Any, payload: Mapping[str, Any], *,
                      commit: bool = False) -> None:
    """Encola `tipo` en el outbox de este nodo, **en la transacción de `conn`** (sin confirmar, salvo `commit=True`).

    Es el contrato de ADR-025 de LibraEdge: `operation_id = <nodo>:<secuencia>`, `aggregate_id =
    <nodo>:<agregado>:<id local>`, y la secuencia es una sola por nodo: el central recibe las operaciones en el orden en
    que ocurrieron (libraedge ADR-020). Levanta `RuntimeError` fuera de un nodo: encolar en el central dejaría una
    operación que nadie sube.

    `conn` es una conexión DB-API de la familia (`libracore.db.core.get_connection()` o `conexion_libracore(...)` sobre
    la conexión de la sesión): con la de la sesión, la operación vive o muere con el cambio que la originó."""
    from libraedge.db.repository import NodeRepository
    from libraedge.domain.sync import OutboxOperation

    node_id = nodo()
    if node_id is None:
        raise RuntimeError("Encolar una operación es del nodo: esta instancia no es un nodo de LibraEdge.")
    repo = NodeRepository(conn)
    secuencia = repo.next_sequence(commit=False)
    repo.enqueue_operation(OutboxOperation(
        operation_id=f"{node_id}:{secuencia}", node_id=node_id, sequence=secuencia, operation_type=tipo,
        aggregate_type=agregado, aggregate_id=f"{node_id}:{agregado}:{id_local}", occurred_at=_ahora_utc(),
        schema_version=SCHEMA_VERSION, payload=dict(payload),
    ), commit=False)
    if commit:
        conn.commit()


def _encolar_de_caja(tipo: str):
    def gancho(conn, datos: dict) -> None:
        # Fuera de un nodo (el central, una instalación común) los ganchos no hacen nada: se arma siempre igual.
        if nodo() is not None:
            encolar_operacion(conn, tipo, "caja_movimiento", datos["movimiento_id"], datos)

    return gancho


#: Los ganchos de la caja para `libracore.db.caja` (`ganchos=`): en un nodo encolan cada movimiento que se anota (con lo
#: propio de este producto en `datos["extra"]`: el tercero, la descripción y el recibo) y cada anulación; **fuera de un
#: nodo** no hacen nada, como `GanchosDeCaja()`. LibraCargo no tiene turnos ni cierre del día: sólo estos dos.
#:
#: La contrapartida en la cuenta corriente **no viaja acá**: sube por su cuenta como `cargo.asiento`
#: (`servicios/cuentas.py` avisa cada asiento que escribe), para que el central tenga el mismo libro que el nodo sea
#: cual sea el hecho que lo originó (un cobro, una orden, un gasto, una factura).
GANCHOS_DE_CAJA = GanchosDeCaja(
    al_registrar_movimiento=_encolar_de_caja(TIPO_CAJA_MOVIMIENTO),
    al_anular_movimiento=_encolar_de_caja(TIPO_CAJA_ANULADO),
)


# ── Facturar y emitir sin red: la cola de ARCA ────────────────────────────────────────────────────────────────────────

_cliente_de_ticket = None


def _version_esquema_del_nodo() -> str | None:
    """La misma versión de esquema que manda el proceso del nodo (`LIBRAEDGE_VERSION_ESQUEMA`, `alembic` por defecto),
    para que el central conteste 409 si no coinciden."""
    from libracore.db.core import get_connection
    from libraedge.cli import version_esquema_del_nodo

    with get_connection() as conn:
        return version_esquema_del_nodo(conn, os.environ.get("LIBRAEDGE_VERSION_ESQUEMA"))


def cliente_de_ticket():
    """El `ClienteDeTicket` de LibraEdge de este nodo (uno por proceso: guarda el ticket en memoria hasta que vence).
    Lo arma recién al primer uso: fuera de un nodo no hay a quién pedirle y `cliente_desde_entorno` levantaría."""
    global _cliente_de_ticket
    if _cliente_de_ticket is None:
        from libraedge.sync.ticket import cliente_desde_entorno

        version: list[str | None] = []

        def version_esquema() -> str | None:
            if not version:
                version.append(_version_esquema_del_nodo())
            return version[0]

        _cliente_de_ticket = cliente_desde_entorno(version_esquema=version_esquema)
    return _cliente_de_ticket


async def obtener_ta(arca: dict, servicio: str = "wsfe") -> dict:
    """El `obtener_ta(arca, servicio=)` de `ColaDeArca` y de `numerador_con_ta`, sobre el transporte de LibraEdge.

    **No** el de un solo parámetro de VentaLibra: la cola lo llama con `servicio="wscpe"` para las CPE. Un corte (sin
    red, 5xx, esquema distinto) llega como `SinConexion` y el pedido queda `esperando`; un rechazo del central (nodo
    revocado, sin credencial de ese servicio) como `RechazoDelCentral` con el mensaje del central: se informa en vez
    de reintentarse."""
    base = cliente_de_ticket().para_servicio(sin_conexion=SinConexion, rechazo=RechazoDelCentral)
    return await base(arca, servicio=servicio)


async def numerar_en_el_nodo(punto_venta: int, tipo: int) -> tuple:
    """El `numerar_comprobante` de un nodo: el número de ARCA pedido con el ticket que presta el central. **Nunca numera
    local** (ese número chocaría con el de ARCA y con el del central). Devuelve `(numero, ta, arca)`."""
    from libracore.nodo_offline import numerador_con_ta

    return await numerador_con_ta(obtener_ta)(punto_venta, tipo)


def subir_pedido(payload: dict) -> None:
    """El `al_cambiar` de la cola: encola el estado del pedido (`cola.pedido`) para que el central lo vea («la web
    consulta»). Corre **después** de confirmar el cambio de la cola y no tiene transacción propia: abre la suya. Si
    falla, el motor lo registra y no deshace el comprobante (ya está emitido en ARCA); la `revision` del payload hace
    idempotente el reenvío al reconciliar."""
    from libracore.db.core import get_connection

    with get_connection() as conn:
        encolar_operacion(conn, TIPO_COLA_PEDIDO, "cola_arca", payload["id_en_el_nodo"], payload)
        conn.commit()


def cola() -> ColaDeArca:
    """La cola de comprobantes de ARCA de este producto (libracore ADR-079). El mismo armado en el nodo y en el
    central: en el central no hace nada (`encolar` se rehúsa y `procesar_cola` no emite). Se arma en cada llamada (es
    barata) para que un test pueda cambiar la conexión o el numerador."""
    from app.servicios import emisores

    return ColaDeArca(
        producto=PRODUCTO,
        emisores={"documento": emisores.emitir_documento, "cpe": emisores.emitir_cpe},
        conexion=CONEXION,
        obtener_ta=obtener_ta,
        al_cambiar=subir_pedido,
    )


def arrancar_cola() -> Any:
    """En un nodo, arranca el hilo que emite lo que quedó en la cola cuando vuelve la conexión (libracore ADR-079, punto
    7). Devuelve el `Event` que lo para, o `None` si la instancia no es un nodo."""
    from libracore.cola_arca import arrancar_cola_al_volver

    return arrancar_cola_al_volver(cola())


# ── El aprovisionamiento del central ──────────────────────────────────────────────────────────────────────────────────


def _conectar():
    """La base de la instancia, para el CLI de LibraEdge (que corre sin la app): la misma URL que arma `app/main.py`. En
    LibraCargo el dominio y LibraCore son la misma base (ADR-054)."""
    from libracore.db.core import conectar

    from app.config import Config

    return conectar(Config.desde_entorno().database_url)


def nodos_del_central() -> list[dict]:
    """Los nodos registrados en esta instancia, para la barra de estado del pie (libracore ADR-075): la misma lista que
    «Sucursal sin internet». El motor usa sólo `activo` y `estado`."""
    from libracore.db.core import get_connection
    from libraedge.pantalla_del_central import nodos_de_la_instancia

    with get_connection() as conn:
        return nodos_de_la_instancia(conn, [])


def listar_sucursales(conn) -> list[dict]:
    """La oficina, y nada más: LibraCargo no tiene sucursales. Ver `SUCURSAL_UNICA`."""
    return [dict(SUCURSAL_UNICA)]


def _aprovisionamiento():
    from libraedge.aprovisionamiento import Aprovisionamiento, sin_guarda

    return Aprovisionamiento(
        prefijo=PREFIJO, tablas_de_referencia=TABLAS_DE_REFERENCIA, listar_sucursales=listar_sucursales,
        # Sin guarda comercial: LibraEdge está incluido en todos los planes (libraedge ADR-014).
        verificar_alta=sin_guarda, conectar=_conectar,
        tablas_solo_lectura=TABLAS_SOLO_LECTURA, altas_en_nodo=ALTAS_EN_EL_NODO,
    )


#: Lo que el central necesita para aprovisionar los nodos de este producto (`LIBRAEDGE_APROVISIONAMIENTO`).
aprovisionamiento = _aprovisionamiento()
