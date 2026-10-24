"""El reparto de autoridad del nodo de LibraCargo: qué manda el central, qué genera el nodo y qué no se espeja
(ADR-056).

`app/offline.py` declara **qué tablas** baja el espejo al nodo (`TABLAS_DE_REFERENCIA`). Lo que el nodo genera
—órdenes, caja, asientos, facturas, cartas de porte— no se publica: sube como operaciones, y lo que el central ya
tenía baja una sola vez por la carga inicial. Y hay cosas que **no se espejan nunca**: la clave privada y el almacén
de claves, porque el ticket de ARCA lo presta el central (libracore ADR-074).
"""
from __future__ import annotations

import pytest
from libracore.db import core
from libraedge import aprovisionamiento as aprov
from libraedge.aprovisionamiento import SegundoNodoEnLaSucursal

from app import offline

#: Lo que nunca puede bajar a una PC de mostrador. El motivo de cada una, a la vista.
PROHIBIDAS = {
    "arca_credenciales_servicio": "los pares de wscpe: el ticket lo presta el central y la clave no sale del VPS",
    "secretos_instancia": "el almacén cifrado de claves de la instancia (tokens, contraseñas de SMTP)",
    "auth_log": "el registro de accesos es del central",
    "envios_email": "el rastro de los mails enviados es del central",
}

#: Lo que genera el nodo: sube como operación (o ya lo tiene del central por la carga inicial) y no se publica nunca.
DEL_NODO = (
    "ordenes_carga", "ordenes_adjuntos", "gastos_de_proveedor", "facturas", "comprobantes_cargo",
    "comprobante_de_apertura", "caja_movimientos", "movimientos_caja_cargo", "cc_asientos",
    "movimientos_cuenta_cargo", "cartas_porte",
    "cartas_porte_pdf", "plantillas_cpe", "cola_arca", "auditoria", "comprobantes_pendientes",
)


def test_nunca_se_espeja_lo_prohibido():
    espejadas = set(offline.TABLAS_DE_REFERENCIA)
    assert not espejadas & set(PROHIBIDAS), {t: PROHIBIDAS[t] for t in espejadas & set(PROHIBIDAS)}
    assert not set(offline.aprovisionamiento.nombres) & set(PROHIBIDAS)


def test_lo_que_genera_el_nodo_no_se_publica():
    assert not set(offline.aprovisionamiento.nombres) & set(DEL_NODO)


def test_el_nodo_recibe_lo_que_necesita_para_operar():
    esperadas = {"usuarios", "terceros", "localidades", "choferes", "vehiculos", "tipos_carga", "configuracion_empresa",
                 "arca_config", "cajas", "tarifarios", "tarifas_referencia", "titulares_cpe"}
    assert esperadas <= set(offline.aprovisionamiento.nombres)


def test_los_maestros_son_de_solo_lectura_en_el_nodo():
    # Las tablas de solo lectura tienen que estar entre las que se espejan (si no, `Aprovisionamiento` no se arma) y no
    # pueden incluir lo que el nodo escribe a propósito.
    assert offline.TABLAS_SOLO_LECTURA <= offline.TABLAS_DE_REFERENCIA
    assert not offline.TABLAS_SOLO_LECTURA & {"usuarios", "aceptaciones_terminos", "cajas", "catalogo_cpe"}
    # El mapeo de ids baja por el espejo y en el nodo sólo lo escribe el espejo.
    assert "libraedge_mapeo" in offline.aprovisionamiento.solo_lectura


def test_los_terceros_son_la_unica_alta_en_el_nodo():
    assert [a.tabla for a in offline.aprovisionamiento.altas] == ["terceros"]


def test_la_referencia_no_apunta_a_nada_que_no_se_espeje(cliente):
    """Una clave foránea de una tabla espejada hacia una que no se espeja rompería el espejo al aplicar una fila: el
    nodo no tendría con qué satisfacerla. Se lee del catálogo de la base, no de una lista que alguien tenga que
    mantener."""
    nombres = set(offline.aprovisionamiento.nombres)
    with core.get_connection() as conn:
        fks = conn.execute(
            """SELECT cl.relname, ref.relname
                 FROM pg_constraint c
                 JOIN pg_class cl ON cl.oid = c.conrelid
                 JOIN pg_class ref ON ref.oid = c.confrelid
                 JOIN pg_namespace n ON n.oid = cl.relnamespace
                WHERE c.contype = 'f' AND n.nspname = current_schema()""").fetchall()
    sueltas = sorted((hija, padre) for hija, padre in ((f[0], f[1]) for f in fks)
                     if hija in nombres and padre not in nombres)
    assert not sueltas, f"tablas espejadas con una FK hacia una que no se espeja: {sueltas}"


def test_la_oficina_es_la_unica_sucursal_y_hay_un_solo_nodo(cliente):
    with core.get_connection() as conn:
        sucursales = aprov.listar_sucursales(conn, offline.aprovisionamiento)
        assert [(s.id, s.nombre) for s in sucursales] == [("1", "Oficina")]
        aprov.registrar(conn, offline.aprovisionamiento, "oficina-1", sucursal="1")
        assert aprov.nodos_activos(conn) == 1
        with pytest.raises(SegundoNodoEnLaSucursal):
            aprov.registrar(conn, offline.aprovisionamiento, "oficina-2", sucursal="1")
        # Re-registrar el MISMO nodo es como se reemplaza una PC: emite un secreto nuevo.
        aprov.registrar(conn, offline.aprovisionamiento, "oficina-1", sucursal="1")
        assert aprov.nodos_activos(conn) == 1


def test_registrar_el_nodo_publica_lo_que_hay_que_espejar_y_las_altas(cliente):
    with core.get_connection() as conn:
        alta = aprov.registrar(conn, offline.aprovisionamiento, "oficina-1", sucursal="1")
    assert set(alta.espejo) <= set(offline.aprovisionamiento.nombres)
    assert "terceros" in alta.espejo and "libraedge_mapeo" in alta.espejo
    assert not set(alta.espejo) & set(PROHIBIDAS) and not set(alta.espejo) & set(DEL_NODO)
    assert [a.tabla for a in alta.altas] == ["terceros"]
    assert "libraedge_mapeo" in alta.solo_lectura and "terceros" in alta.solo_lectura


def test_publicar_instala_el_changelog_de_toda_la_referencia(escenario):
    # En el central de prueba (una copia descartable de la base): `publicar` instala triggers que no hay que dejarle a
    # la base del worker.
    conn = core.conectar(escenario.url_central)
    try:
        salidas: list[str] = []
        assert aprov.publicar(conn, offline.aprovisionamiento, salidas.append) == 0, salidas
        conn.commit()
        publicadas = {f[0] for f in conn.execute(
            "SELECT DISTINCT event_object_table FROM information_schema.triggers").fetchall()}
    finally:
        conn.close()
    assert {"terceros", "localidades", "configuracion_empresa", "arca_config"} <= publicadas
    assert not publicadas & set(DEL_NODO), "lo que genera el nodo no se publica"
