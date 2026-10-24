"""Un nodo y su central, con dos bases, para probar lo que sube la oficina (ADR-056).

El **nodo** es la app de la suite sobre la base del worker, con la identidad de un nodo en el entorno
(`LIBRAEDGE_NODE_ID`). El **central** es una **copia de esa base** hecha después de cargar la referencia (terceros,
localidades, la empresa y su ARCA): es lo que deja el espejo de LibraEdge, el nodo tiene las mismas filas con las mismas
claves. En el central se registra el nodo con el aprovisionamiento del producto (`app.offline`). Lo que el nodo hace
después (órdenes, caja, facturas) sólo existe en su base y llega al central como operaciones del outbox, que acá se
aplican con el receptor de LibraEdge y el despachador **reales** del producto (`routers/sincronizacion_offline.py`).

ARCA y el ticket que presta el central son dobles (`arca_responde` de `conftest`, más `ticket_de_prueba`); todo lo
demás es el código de verdad. Datos ficticios.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime

from libracore.db import core
from libracore.nodo_offline import SinConexion
from libracore.respaldo_postgres import con_base
from libraedge import aprovisionamiento as aprov
from libraedge.db.repository import NodeRepository
from libraedge.sync.receiver import SyncReceiver
from libraedge.sync.ticket import SinConexionConElCentral

from app import db, offline

NODO = "oficina-1"


def _ahora_iso() -> str:
    return datetime.now(UTC).isoformat()


class Escenario:
    """El nodo (la app de la suite) y su central (una copia de la base). Ver el docstring del módulo."""

    def __init__(self, cliente, engine, monkeypatch, tmp_path, base_del_worker):
        self.cliente = cliente
        self.engine = engine
        self.monkeypatch = monkeypatch
        self.base = base_del_worker            # `BasePorWorker` de `tests.conftest`
        self.ruta_estado = str(tmp_path / "estado.json")
        self.url_central: str | None = None
        self.secreto: str | None = None
        self.prefijo: str | None = None
        self.cola_central = None

    # ── el central ────────────────────────────────────────────────────────────────────────────────────────────────────

    def clonar_el_central(self) -> None:
        """Copia la base del nodo en este momento: la referencia que el espejo ya bajó. `CREATE DATABASE ... TEMPLATE`
        exige que nadie esté conectado: se sueltan los pools y las conexiones vivas (se renuevan solas)."""
        db.engine().dispose()
        self.engine.dispose()
        nombre = f"{self.base.nombre}_central"
        self.base._soltar(nombre)
        self.base._sql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{self.base.nombre}' AND pid <> pg_backend_pid()")
        self.base._crear(nombre, plantilla=self.base.nombre)
        self.nombre_central = nombre
        self.url_central = con_base(self.base.url_original, nombre)

    def registrar_el_nodo(self) -> None:
        """Da de alta el nodo en el central con el aprovisionamiento del producto (de ahí, el secreto y el prefijo)."""
        conn = core.conectar(self.url_central)
        try:
            alta = aprov.registrar(conn, offline.aprovisionamiento, NODO, sucursal="1")
        finally:
            conn.close()
        self.secreto, self.prefijo = alta.secreto, alta.prefijo

    def soltar(self) -> None:
        if self.url_central:
            self.base._soltar(self.nombre_central)

    @contextmanager
    def en_el_central(self):
        """La app apuntada al central y **sin identidad de nodo**, mientras dura el `with`."""
        guardadas = {v: os.environ.pop(v, None) for v in ("LIBRAEDGE_NODE_ID", "LIBRAEDGE_PREFIJO")}
        anterior = core._db_path
        core.configure(self.url_central)
        try:
            yield self
        finally:
            core.configure(anterior)
            for variable, valor in guardadas.items():
                if valor is not None:
                    os.environ[variable] = valor

    def sql_central(self, sentencia: str, *params):
        """Una consulta contra la base del central (con `?` como parámetros)."""
        conn = core.conectar(self.url_central)
        try:
            return [tuple(f) for f in conn.execute(sentencia, params).fetchall()]
        finally:
            conn.close()

    # ── el nodo ───────────────────────────────────────────────────────────────────────────────────────────────────────

    def ser_nodo(self) -> None:
        """Desde acá la instancia es el nodo de la oficina."""
        self.monkeypatch.setenv("LIBRAEDGE_NODE_ID", NODO)
        self.monkeypatch.setenv("LIBRAEDGE_PREFIJO", self.prefijo or "S01")
        self.monkeypatch.setenv("LIBRAEDGE_ESTADO", self.ruta_estado)
        self.en_linea(False)

    def en_linea(self, si: bool) -> None:
        """Lo que dice el archivo de estado del proceso del nodo (libracore ADR-074)."""
        with open(self.ruta_estado, "w", encoding="utf-8") as archivo:
            json.dump({"node_id": NODO, "en_linea": si, "ultima_sincronizacion_ok": _ahora_iso()}, archivo)

    def sql_nodo(self, sentencia: str, *params):
        with core.get_connection() as conn:
            return [tuple(f) for f in conn.execute(sentencia, params).fetchall()]

    # ── subir ─────────────────────────────────────────────────────────────────────────────────────────────────────────

    def pendientes(self):
        """Las operaciones que el nodo tiene sin subir, en el orden en que ocurrieron."""
        with core.get_connection() as conn:
            return list(NodeRepository(conn).list_pending_operations(limit=1000))

    def tipos_pendientes(self) -> list[str]:
        return [op.operation_type for op in self.pendientes()]

    def subir(self, operaciones=None):
        """Aplica en el central las operaciones del nodo (o las que se le pasen), una por una, como lo hace el
        receptor de LibraEdge. Devuelve `[(operación, resultado)]`; las aceptadas quedan confirmadas en el nodo."""
        from app.routers.sincronizacion_offline import despachador

        operaciones = self.pendientes() if operaciones is None else operaciones
        resultados = []
        with self.en_el_central():
            conn = core.conectar(self.url_central)
            try:
                receptor = SyncReceiver(conn, despachador=despachador)
                for op in operaciones:
                    resultados.append((op, receptor.accept(op)))
            finally:
                conn.close()
        with core.get_connection() as nodo:
            repo = NodeRepository(nodo)
            for op, resultado in resultados:
                if resultado.result in ("accepted", "duplicate"):
                    repo.acknowledge_operation(op.operation_id, _ahora_iso())
        return resultados

    def subir_todo_y_exigir(self):
        """Sube todo y exige que se haya aceptado: lo que rebota va a revisión manual y el test lo tiene que ver."""
        resultados = self.subir()
        rechazadas = [(op.operation_type, r.error) for op, r in resultados if r.result == "rejected"]
        assert not rechazadas, f"el central rechazó operaciones del nodo: {rechazadas}"
        return resultados


def ticket_de_prueba(monkeypatch, *, ambiente="produccion", falla=None, relaciones_wscpe=()):
    """El ticket que el central le presta al nodo (doble de `offline.obtener_ta`) y del cliente de LibraEdge
    (`offline.cliente_de_ticket`, que usa `servicios/cartas_porte.py` para consultar a ARCA).

    `falla` es una excepción que levanta en vez de dar el ticket (un corte, un rechazo del central). El de `wscpe`
    trae las relaciones del titular que delegó (`relaciones_wscpe`: CUIT), como el WSAA. Devuelve la lista de lo que
    se pidió: `[(servicio, arca)]`."""
    import base64

    pedidos: list[tuple] = []

    def token(servicio):
        if servicio != "wscpe":
            return "TKN"
        relaciones = "".join(f'<relation key="{c}" reltype="4"/>' for c in relaciones_wscpe)
        xml = f'<sso><operation><login service="wscpe"><relations>{relaciones}</relations></login></operation></sso>'
        return base64.b64encode(xml.encode()).decode()

    def ticket(arca, servicio):
        return {"token": token(servicio), "sign": "SGN", "expiracion": "2099-01-01T00:00:00+00:00",
                "ambiente": ambiente, "servicio": servicio, "cuit": (arca or {}).get("cuit"),
                "emisor_id": (arca or {}).get("id")}

    async def obtener_ta(arca, servicio="wsfe"):
        if not offline.en_linea():
            raise SinConexion("Sin conexión con el central: se emite al volver la conexión.")
        pedidos.append((servicio, arca))
        if falla is not None:
            raise falla
        return ticket(arca, servicio)

    class Cliente:
        def pedir_ticket(self, emisor_id=None, servicio="wsfe"):
            if not offline.en_linea():
                raise SinConexionConElCentral("El central no respondió.", codigo="sin_conexion")
            pedidos.append((servicio, {"id": emisor_id}))
            if falla is not None:
                raise falla
            return ticket({"id": emisor_id}, servicio)

    monkeypatch.setattr(offline, "obtener_ta", obtener_ta)
    monkeypatch.setattr(offline, "cliente_de_ticket", Cliente)
    return pedidos
