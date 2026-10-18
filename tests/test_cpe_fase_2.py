"""CPE fase 2 (ADR-051): el refresco programado de las cartas abiertas y los códigos de ARCA traducidos.

ARCA está simulada en el borde del motor (`libracore.arca_wscpe`), como en `test_cartas_porte`: el ticket, la consulta
de una CPE y las tablas de grano, provincia y localidad. Lo que se prueba es lo del producto: cuándo el refresco **no**
corre (apagado, demo, sin certificado, otra corrida en curso), que sólo consulta, que una carta que falla no frena a las
demás, que no llena la auditoría, y que los nombres salen de la base y no de ARCA en cada pantalla. CUIT ficticios.
"""
# ruff: noqa: F811  (la fixture `arca` se importa de test_cartas_porte y los tests la piden por nombre)

from __future__ import annotations

import importlib.util
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from libracore import arca_wscpe
from libracore.candados import candado_de_base
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.models import ConfiguracionEmpresa, RegistroAuditoria
from app.models.cartas_porte import (
    CATALOGO_GRANO,
    CATALOGO_LOCALIDAD,
    CATALOGO_PROVINCIA,
    CartaPorte,
    CatalogoCpe,
)
from app.servicios import catalogo_cpe, refresco_cpe
from tests.conftest import cargar_empresa, config_de_prueba, rearmar_en
from tests.test_cartas_porte import TRANSPORTISTA, _traer, arca, cpe  # noqa: F401
from tests.test_retirar_pre_facturas import _alembic

RAIZ = Path(__file__).resolve().parent.parent
RUTA = "/api/cartas-porte"


def _hace(**tiempo) -> datetime:
    return datetime.now(UTC) - timedelta(**tiempo)


@pytest.fixture
def catalogos(arca, monkeypatch):
    """Las tablas de WSCPE de mentira. `llamadas` cuenta cuántas veces se las pidió a ARCA."""
    estado = {
        "granos": {19: "MAIZ", 23: "SOJA"},
        "provincias": {1: "BUENOS AIRES", 12: "SANTA FE"},
        # El 5321 existe en dos provincias con nombres distintos: la localidad es de una provincia.
        "localidades": {12: {5321: "FUNES", 4211: "ROSARIO"}, 1: {5321: "OTRA LOCALIDAD"}},
        "llamadas": [],
        "falla": None,
    }

    def contestar(nombre, valor):
        estado["llamadas"].append(nombre)
        if estado["falla"]:
            raise estado["falla"]
        return valor

    async def tipos_grano(cuit, token, sign, ambiente):
        return contestar("grano", estado["granos"])

    async def provincias(cuit, token, sign, ambiente):
        return contestar("provincia", estado["provincias"])

    async def localidades(cuit, token, sign, *, cod_provincia, ambiente):
        return contestar(f"localidad:{cod_provincia}", estado["localidades"].get(cod_provincia, {}))

    monkeypatch.setattr(arca_wscpe, "tipos_grano", tipos_grano)
    monkeypatch.setattr(arca_wscpe, "provincias", provincias)
    monkeypatch.setattr(arca_wscpe, "localidades", localidades)
    return estado


@pytest.fixture
def sin_emitir(monkeypatch):
    """El refresco sólo consulta: si algo llama a emitir o anular, el test se cae."""
    def prohibida(*args, **kwargs):
        raise AssertionError("el refresco no puede emitir ni anular")

    for nombre in ("emitir_cpe", "anular_cpe", "autorizar_cpe"):
        monkeypatch.setattr(arca_wscpe, nombre, prohibida)


def _prender(cliente, valor=True):
    cargar_empresa(cliente)
    r = cliente.put(f"{RUTA}/refresco/habilitado", json={"habilitado": valor})
    assert r.status_code == 200, r.text
    return r.json()


def _envejecer(sesion, ctg=None, **valores):
    """Como si la carta se hubiera consultado hace una hora (el refresco espera 15 minutos entre consultas)."""
    valores.setdefault("consultada_en", _hace(hours=1))
    consulta = update(CartaPorte).values(**valores)
    if ctg is not None:
        consulta = consulta.where(CartaPorte.nro_ctg == ctg)
    sesion.execute(consulta)
    sesion.commit()


def _carta(sesion, ctg) -> CartaPorte:
    sesion.expire_all()
    return sesion.scalar(select(CartaPorte).where(CartaPorte.nro_ctg == ctg))


def _asientos(sesion) -> int:
    return sesion.scalar(select(func.count()).select_from(RegistroAuditoria).where(
        RegistroAuditoria.entidad == "carta_porte"))


def _ver(cliente, id_):
    r = cliente.get(f"{RUTA}/{id_}")
    assert r.status_code == 200, r.text
    return r.json()


# ═════════════════════════════════════════════════════════════════════════
# El refresco programado
# ═════════════════════════════════════════════════════════════════════════

def test_actualiza_el_estado_los_kilos_y_la_fecha_de_la_ultima_consulta(cliente, arca, catalogos, sesion, sin_emitir):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    antes = _carta(sesion, 1).consultada_en
    arca["pedidos"].clear()
    arca["cpes"][1] = cpe(1, estado="CN", descarga=(45100, 15800))

    r = refresco_cpe.correr(sesion)

    assert (r["estado"], r["actualizadas"], r["errores"]) == ("corrio", 1, [])
    assert [p[0] for p in arca["pedidos"]] == [1]
    carta = _carta(sesion, 1)
    assert (carta.estado, carta.peso_bruto_descarga) == ("CN", 45100)
    assert carta.consultada_en > antes
    cfg = sesion.get(ConfiguracionEmpresa, 1)
    assert cfg.cpe_refresco_ultima_corrida is not None
    assert cfg.cpe_refresco_resumen == "1 actualizada"
    # Y lo que cambió queda a nombre del refresco, no de un usuario.
    asiento = sesion.scalars(select(RegistroAuditoria).where(
        RegistroAuditoria.entidad == "carta_porte").order_by(RegistroAuditoria.id.desc())).first()
    assert asiento.usuario_nombre == "sistema (refresco de CPE)"
    assert asiento.datos_despues["estado"] == "CN"


def test_viene_apagado_de_fabrica_y_no_consulta_nada(cliente, arca, sesion):
    """El estado de fábrica: ni con cartas abiertas y de sobra para consultar."""
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    cargar_empresa(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()
    logins = arca["logins"]

    assert cliente.get(f"{RUTA}/refresco/estado").json()["habilitado"] is False
    r = refresco_cpe.correr(sesion)

    assert (r["estado"], r["actualizadas"]) == ("omitido", 0)
    assert "apagado" in r["motivo"]
    assert arca["pedidos"] == []
    assert arca["logins"] == logins, "ni siquiera pidió un ticket a ARCA"
    assert sesion.get(ConfiguracionEmpresa, 1).cpe_refresco_ultima_corrida is None


def test_apagar_el_refresco_lo_detiene(cliente, arca, sesion):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _prender(cliente, False)
    _envejecer(sesion)
    arca["pedidos"].clear()
    assert refresco_cpe.correr(sesion)["estado"] == "omitido"
    assert arca["pedidos"] == []


def test_en_una_demo_saltea_sin_error_aunque_este_prendido(cliente, arca, sesion, monkeypatch):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()
    monkeypatch.setenv("DEMO_MODE", "1")

    r = refresco_cpe.correr(sesion)

    assert (r["estado"], r["actualizadas"], r["errores"]) == ("omitido", 0, [])
    assert "demo" in r["motivo"]
    assert arca["pedidos"] == []


def test_sin_certificado_saltea_sin_error(cliente, arca, sesion):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()
    arca["ambientes"] = set()

    r = refresco_cpe.correr(sesion)

    assert (r["estado"], r["actualizadas"], r["errores"]) == ("omitido", 0, [])
    assert "certificado" in r["motivo"]
    assert arca["pedidos"] == []


def test_no_corre_si_otra_corrida_tiene_el_candado(cliente, arca, catalogos, sesion, engine):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()

    with engine.connect() as otra, otra.begin():
        with candado_de_base(otra, refresco_cpe.CANDADO) as lo_tiene:
            assert lo_tiene
            r = refresco_cpe.correr(sesion)
    assert (r["estado"], r["actualizadas"]) == ("ocupado", 0)
    assert arca["pedidos"] == []

    # Soltado el candado, la corrida siguiente sí consulta.
    assert refresco_cpe.correr(sesion)["actualizadas"] == 1


def test_dos_corridas_a_la_vez_consultan_una_sola_vez(cliente, arca, catalogos, sesion, engine, monkeypatch):
    """La carrera de verdad: la primera se queda adentro de ARCA y la segunda llega mientras tanto."""
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()
    entro, soltar = threading.Event(), threading.Event()
    consulta = arca_wscpe.consultar_cpe

    async def lenta(cuit, token, sign, *, ctg, ambiente):
        entro.set()
        assert soltar.wait(20), "la segunda corrida no terminó"
        return await consulta(cuit, token, sign, ctg=ctg, ambiente=ambiente)

    monkeypatch.setattr(arca_wscpe, "consultar_cpe", lenta)
    Sesion = sessionmaker(bind=engine, expire_on_commit=False)
    resultado = {}

    def primera():
        with Sesion() as s:
            resultado["primera"] = refresco_cpe.correr(s)

    hilo = threading.Thread(target=primera)
    hilo.start()
    try:
        assert entro.wait(20), "la primera corrida nunca consultó"
        with Sesion() as s:
            resultado["segunda"] = refresco_cpe.correr(s)
    finally:
        soltar.set()
        hilo.join(20)

    assert resultado["segunda"]["estado"] == "ocupado"
    assert (resultado["primera"]["estado"], resultado["primera"]["actualizadas"]) == ("corrio", 1)
    assert [p[0] for p in arca["pedidos"]] == [1]


def test_una_carta_que_falla_no_frena_a_las_demas(cliente, arca, catalogos, sesion, monkeypatch):
    arca["cpes"].update({1: cpe(1), 2: cpe(2), 3: cpe(3)})
    _traer(cliente, 1, 2, 3)
    _prender(cliente)
    _envejecer(sesion)
    # Un corte de red (que no es un error de ARCA), un error de ARCA, y una que anda.
    arca["cpes"][1] = httpx.ConnectError("sin red")
    arca["cpes"][2] = arca_wscpe.ErrorWscpe("WSCPE: servicio no disponible", [])
    arca["cpes"][3] = cpe(3, estado="CN", descarga=(45100, 15800))

    # Un manejador propio, y el logger prendido: el `fileConfig` de alembic (que la suite corre en el mismo proceso, en
    # `engine`) deja desactivados los loggers que ya existían. En producción las migraciones van en otro proceso.
    registros: list[str] = []
    manejador = logging.Handler()
    manejador.emit = lambda registro: registros.append(registro.getMessage())
    logger = logging.getLogger("app.servicios.refresco_cpe")
    monkeypatch.setattr(logger, "disabled", False)
    logger.addHandler(manejador)
    try:
        r = refresco_cpe.correr(sesion)
    finally:
        logger.removeHandler(manejador)

    assert (r["estado"], r["actualizadas"]) == ("corrio", 1)
    assert sorted(e["ctg"] for e in r["errores"]) == [1, 2]
    assert _carta(sesion, 3).estado == "CN"
    assert sesion.get(ConfiguracionEmpresa, 1).cpe_refresco_resumen == "1 actualizada, 2 con error"
    assert any(m.startswith("CPE 1:") for m in registros) and any(m.startswith("CPE 2:") for m in registros), (
        "los errores quedan registrados")


def test_si_WSAA_no_da_ticket_no_se_lo_pide_por_cada_carta(cliente, arca, catalogos, sesion, monkeypatch):
    """El mismo error para todas las del ambiente: se anota en cada una, pero no se golpea a ARCA una vez por carta."""
    arca["cpes"].update({1: cpe(1), 2: cpe(2), 3: cpe(3)})
    _traer(cliente, 1, 2, 3)
    _prender(cliente)
    _envejecer(sesion)
    pedidos = []

    async def caido(empresa, ambiente):
        pedidos.append(ambiente)
        raise RuntimeError("WSAA no contesta")

    monkeypatch.setattr(arca_wscpe, "autenticar", caido)

    r = refresco_cpe.correr(sesion)

    assert (r["estado"], r["actualizadas"], len(r["errores"])) == ("corrio", 0, 3)
    assert all("WSAA no contesta" in e["error"] for e in r["errores"])
    assert pedidos == ["produccion"], "un intento por ambiente, no uno por carta"


def test_no_vuelve_a_consultar_una_carta_recien_consultada(cliente, arca, catalogos, sesion):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    arca["pedidos"].clear()

    r = refresco_cpe.correr(sesion)

    assert (r["estado"], r["actualizadas"]) == ("corrio", 0)
    assert arca["pedidos"] == []


def test_no_toma_las_cerradas_ni_las_descargadas(cliente, arca, catalogos, sesion):
    arca["cpes"].update({1: cpe(1), 2: cpe(2, estado="AN"), 3: cpe(3, descarga=(1, 1))})
    _traer(cliente, 1, 2, 3)
    _prender(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()

    refresco_cpe.correr(sesion)

    assert [p[0] for p in arca["pedidos"]] == [1]


def test_una_carta_vencida_hace_mucho_deja_de_consultarse_sola(cliente, arca, catalogos, sesion):
    arca["cpes"].update({1: cpe(1), 2: cpe(2)})
    _traer(cliente, 1, 2)
    _prender(cliente)
    _envejecer(sesion, 1, fecha_vencimiento=_hace(days=refresco_cpe.DIAS_VENCIDA + 5))
    _envejecer(sesion, 2, fecha_vencimiento=_hace(days=3))
    arca["pedidos"].clear()

    refresco_cpe.correr(sesion)

    assert [p[0] for p in arca["pedidos"]] == [2]


def test_una_corrida_toma_un_lote_y_las_mas_viejas_primero(cliente, arca, catalogos, sesion, monkeypatch):
    arca["cpes"].update({1: cpe(1), 2: cpe(2), 3: cpe(3)})
    _traer(cliente, 1, 2, 3)
    _prender(cliente)
    _envejecer(sesion, 1, consultada_en=_hace(hours=2))
    _envejecer(sesion, 2, consultada_en=_hace(hours=5))
    _envejecer(sesion, 3, consultada_en=_hace(hours=3))
    monkeypatch.setattr(refresco_cpe, "MAX_POR_CORRIDA", 2)
    arca["pedidos"].clear()

    r = refresco_cpe.correr(sesion)

    assert r["actualizadas"] == 2
    assert [p[0] for p in arca["pedidos"]] == [2, 3], "la 2 y la 3 son las que hace más que no se consultan"


def test_el_refresco_solo_consulta(cliente, arca, catalogos, sesion, sin_emitir):
    """`sin_emitir` hace explotar cualquier llamada a emitir, autorizar o anular; el refresco con la emisión APAGADA."""
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    assert cliente.get(f"{RUTA}/emision/estado").json()["habilitada"] is False

    assert refresco_cpe.correr(sesion)["actualizadas"] == 1


def test_si_ARCA_contesta_lo_mismo_no_llena_la_auditoria(cliente, arca, catalogos, sesion):
    """Cambia la hora de la consulta y el XML, no la carta: un asiento por carta por corrida sería ruido."""
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    antes_de_la_hora = _carta(sesion, 1).consultada_en
    asientos = _asientos(sesion)

    assert refresco_cpe.correr(sesion)["actualizadas"] == 1

    assert _carta(sesion, 1).consultada_en > antes_de_la_hora
    assert _asientos(sesion) == asientos


def test_la_pantalla_ve_cuando_corrio_por_ultima_vez(cliente, arca, catalogos, sesion):
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    _prender(cliente)
    _envejecer(sesion)
    refresco_cpe.correr(sesion)

    e = cliente.get(f"{RUTA}/refresco/estado").json()

    assert e["habilitado"] is True
    assert e["resumen"] == "1 actualizada"
    assert e["ultima_corrida"] is not None


def test_prenderlo_es_de_un_administrador_y_queda_en_la_auditoria(cliente, arca):
    cargar_empresa(cliente)
    cliente.post("/api/usuarios", json={"username": "marta", "name": "Marta", "password": "una-clave",
                                        "role": "staff"})
    staff = TestClient(cliente.app, base_url="https://testserver")
    assert staff.post("/auth/login", json={"username": "marta", "password": "una-clave"}).status_code == 200

    assert staff.put(f"{RUTA}/refresco/habilitado", json={"habilitado": True}).status_code == 403
    assert staff.get(f"{RUTA}/refresco/estado").status_code == 200, "ver el estado es de staff"
    assert cliente.put(f"{RUTA}/refresco/habilitado", json={"habilitado": True}).json()["habilitado"] is True

    asiento = cliente.get("/api/auditoria?entidad=configuracion").json()["registros"][0]
    assert asiento["datos_despues"]["cpe_refresco_habilitado"] is True


def test_el_script_del_cron_corre_y_dice_que_paso(cliente, arca, catalogos, sesion, engine, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "refrescar_cartas_porte", RAIZ / "scripts" / "refrescar_cartas_porte.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script.Config, "desde_entorno", classmethod(lambda cls: config_de_prueba()))
    monkeypatch.setattr(script.db, "inicializar", lambda config=None: None)
    monkeypatch.setattr(script.db, "fabrica_de_sesiones", lambda: sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(script.libracore_core, "configure", lambda url: None)
    arca["cpes"][1] = cpe(1)
    _traer(cliente, 1)
    cargar_empresa(cliente)
    _envejecer(sesion)
    arca["pedidos"].clear()

    assert script.main() == 0
    assert "cpe-refresco · omitido · el refresco programado está apagado" in capsys.readouterr().out
    assert arca["pedidos"] == []

    _prender(cliente)
    assert script.main() == 0
    assert "cpe-refresco · corrio · 1 actualizada" in capsys.readouterr().out
    assert [p[0] for p in arca["pedidos"]] == [1]


# ═════════════════════════════════════════════════════════════════════════
# Los códigos de ARCA, con su nombre
# ═════════════════════════════════════════════════════════════════════════

def test_al_traer_una_carta_se_bajan_los_nombres_y_la_ficha_los_muestra(cliente, arca, catalogos):
    arca["cpes"][1] = cpe(1)

    id_ = _traer(cliente, 1).json()[0]["id"]
    carta = _ver(cliente, id_)

    assert carta["grano"] == "SOJA"
    assert (carta["provincia_origen"], carta["localidad_origen"]) == ("SANTA FE", "FUNES")
    assert (carta["provincia_destino"], carta["localidad_destino"]) == ("SANTA FE", "ROSARIO")
    # Los códigos siguen estando: el nombre se suma, no los reemplaza.
    assert (carta["cod_grano"], carta["cod_provincia_origen"], carta["cod_localidad_origen"]) == (23, 12, 5321)
    # Una sola tabla de cada una, y una sola de localidades porque las dos puntas son de la misma provincia.
    assert catalogos["llamadas"] == ["grano", "provincia", "localidad:12"]


def test_listar_y_ver_no_van_a_arca(cliente, arca, catalogos):
    arca["cpes"].update({1: cpe(1), 2: cpe(2)})
    _traer(cliente, 1, 2)
    catalogos["llamadas"].clear()
    catalogos["falla"] = RuntimeError("ARCA caída: no debería llamarse")
    arca["pedidos"].clear()
    arca["logins"] = 0

    lista = cliente.get(RUTA).json()
    one = _ver(cliente, lista[0]["id"])

    assert [c["grano"] for c in lista] == ["SOJA", "SOJA"]
    assert one["localidad_destino"] == "ROSARIO"
    assert catalogos["llamadas"] == [] and arca["pedidos"] == [] and arca["logins"] == 0


def test_el_listado_lee_los_nombres_con_una_sola_consulta(cliente, arca, catalogos):
    arca["cpes"].update({n: cpe(n) for n in (1, 2, 3, 4)})
    _traer(cliente, 1, 2, 3, 4)
    consultas = []

    def contar(conn, cursor, statement, *resto):
        if "catalogo_cpe" in statement:
            consultas.append(statement)

    motor = app_db.engine()  # el de la app, no el de la suite
    event.listen(motor, "before_cursor_execute", contar)
    try:
        assert len(cliente.get(RUTA).json()) == 4
    finally:
        event.remove(motor, "before_cursor_execute", contar)

    assert len(consultas) == 1, "una consulta para todo el listado, no una por carta"


def test_lo_que_ya_se_bajo_no_se_vuelve_a_pedir(cliente, arca, catalogos):
    arca["cpes"].update({1: cpe(1), 2: cpe(2)})
    id_ = _traer(cliente, 1).json()[0]["id"]
    catalogos["llamadas"].clear()

    _traer(cliente, 1, 2)
    assert cliente.post(f"{RUTA}/{id_}/actualizar").status_code == 200
    assert cliente.post(f"{RUTA}/actualizar-abiertas").status_code == 200

    assert catalogos["llamadas"] == []


def test_si_ARCA_no_da_las_tablas_la_carta_se_guarda_igual_con_sus_codigos(cliente, arca, catalogos):
    arca["cpes"][1] = cpe(1)
    catalogos["falla"] = arca_wscpe.ErrorWscpe("WSCPE: servicio no disponible", [])

    r = _traer(cliente, 1)

    assert r.status_code == 200, r.text
    assert r.json()[0]["error"] is None
    carta = _ver(cliente, r.json()[0]["id"])
    assert (carta["grano"], carta["provincia_origen"], carta["localidad_origen"]) == (None, None, None)
    assert (carta["cod_grano"], carta["cod_provincia_origen"], carta["cod_localidad_origen"]) == (23, 12, 5321)

    # Cuando ARCA vuelve, la próxima vez que se actualiza la carta se completan.
    catalogos["falla"] = None
    assert cliente.post(f"{RUTA}/{carta['id']}/actualizar").status_code == 200
    assert _ver(cliente, carta["id"])["grano"] == "SOJA"


def test_el_refresco_programado_tambien_completa_los_nombres(cliente, arca, catalogos, sesion):
    arca["cpes"][1] = cpe(1)
    catalogos["falla"] = RuntimeError("ARCA caída")
    id_ = _traer(cliente, 1).json()[0]["id"]
    catalogos["falla"] = None
    _prender(cliente)
    _envejecer(sesion)

    refresco_cpe.correr(sesion)

    assert _ver(cliente, id_)["localidad_destino"] == "ROSARIO"


def test_una_localidad_que_ARCA_no_conoce_no_se_pide_en_cada_vuelta(cliente, arca, catalogos, sesion):
    catalogos["localidades"][12] = {4211: "ROSARIO"}  # falta el 5321 del origen
    arca["cpes"][1] = cpe(1)
    id_ = _traer(cliente, 1).json()[0]["id"]
    catalogos["llamadas"].clear()

    assert cliente.post(f"{RUTA}/{id_}/actualizar").status_code == 200
    assert cliente.post(f"{RUTA}/{id_}/actualizar").status_code == 200
    carta = _ver(cliente, id_)

    assert catalogos["llamadas"] == [], "la tabla de la provincia se bajó hace un rato: no se la pide otra vez"
    assert (carta["localidad_origen"], carta["localidad_destino"]) == (None, "ROSARIO")
    assert carta["cod_localidad_origen"] == 5321, "sin nombre se sigue viendo el código"

    # Pasado el tiempo sí: ARCA pudo haberla sumado.
    catalogos["localidades"][12][5321] = "FUNES"
    sesion.execute(update(CatalogoCpe).values(actualizado_en=_hace(hours=13)))
    sesion.commit()
    assert cliente.post(f"{RUTA}/{id_}/actualizar").status_code == 200
    assert catalogos["llamadas"] == ["localidad:12"]
    assert _ver(cliente, id_)["localidad_origen"] == "FUNES"


def test_la_vista_previa_tambien_traduce_con_lo_que_ya_se_bajo(cliente, arca, catalogos):
    arca["cpes"].update({1: cpe(1), 2: cpe(2)})
    _traer(cliente, 1)
    catalogos["llamadas"].clear()

    previa = cliente.post(f"{RUTA}/consultar", json={"ctg": 2, "cuit_representada": TRANSPORTISTA}).json()

    assert previa["id"] is None
    assert (previa["grano"], previa["localidad_destino"]) == ("SOJA", "ROSARIO")
    assert catalogos["llamadas"] == [], "la vista previa lee la base, no le pide nada a ARCA"


def test_la_localidad_es_de_su_provincia(sesion):
    """El 5321 es FUNES en Santa Fe y otra localidad en Buenos Aires: sin la provincia se confundirían."""
    catalogo_cpe._guardar(sesion, "produccion", CATALOGO_LOCALIDAD, 12, {5321: "FUNES"})
    catalogo_cpe._guardar(sesion, "produccion", CATALOGO_LOCALIDAD, 1, {5321: "OTRA LOCALIDAD"})
    catalogo_cpe._guardar(sesion, "produccion", CATALOGO_PROVINCIA, 0, {12: "SANTA FE"})
    catalogo_cpe._guardar(sesion, "produccion", CATALOGO_GRANO, 0, {12: "UN GRANO CON EL MISMO CÓDIGO"})
    sesion.commit()

    claves = {("produccion", CATALOGO_LOCALIDAD, 12, 5321), ("produccion", CATALOGO_LOCALIDAD, 1, 5321),
              ("produccion", CATALOGO_PROVINCIA, 0, 12), ("produccion", CATALOGO_GRANO, 0, 12)}
    t = catalogo_cpe.Traductor(sesion, claves)

    assert t.localidad("produccion", 12, 5321) == "FUNES"
    assert t.localidad("produccion", 1, 5321) == "OTRA LOCALIDAD"
    assert t.provincia("produccion", 12) == "SANTA FE"
    assert t.grano("produccion", 12) == "UN GRANO CON EL MISMO CÓDIGO"
    assert t.localidad("produccion", None, 5321) is None, "sin provincia no se puede ubicar la localidad"
    assert t.grano("produccion", None) is None
    assert t.grano("homologacion", 12) is None, "cada ambiente tiene sus tablas"


def test_guardar_el_catalogo_dos_veces_no_duplica_y_actualiza_el_nombre(sesion):
    catalogo_cpe._guardar(sesion, "produccion", CATALOGO_GRANO, 0, {23: "SOJA"})
    catalogo_cpe._guardar(sesion, "produccion", CATALOGO_GRANO, 0, {23: "SOJA (NUEVO NOMBRE)", 19: "MAIZ"})
    sesion.commit()

    filas = dict(sesion.execute(select(CatalogoCpe.codigo, CatalogoCpe.nombre)).all())

    assert filas == {23: "SOJA (NUEVO NOMBRE)", 19: "MAIZ"}


def test_los_nombres_se_guardan_por_ambiente(cliente, arca, catalogos, sesion):
    arca["ambientes"] = {"homologacion"}
    arca["cpes"][1] = cpe(1)

    _traer(cliente, 1)

    assert set(sesion.scalars(select(CatalogoCpe.ambiente))) == {"homologacion"}


# ═════════════════════════════════════════════════════════════════════════
# La migración
# ═════════════════════════════════════════════════════════════════════════

def test_la_0031_no_toca_ninguna_fila_y_nace_apagada(engine, sesion):
    rearmar_en("0030")
    try:
        with engine.begin() as con:
            con.execute(text("INSERT INTO configuracion_empresa (id, razon_social, condicion_iva) "
                             "VALUES (1, 'Transportes Ficticios SRL', 'responsable_inscripto')"))
        _alembic("0031")
        with engine.connect() as con:
            fila = con.execute(text("SELECT cpe_refresco_habilitado, cpe_refresco_ultima_corrida, "
                                    "cpe_refresco_resumen, cpe_emision_habilitada FROM configuracion_empresa")).one()
            assert tuple(fila) == (False, None, None, False), "apagado, sin corridas, y la emisión real intacta"
            assert con.execute(text("SELECT count(*) FROM catalogo_cpe")).scalar() == 0
        _alembic("0030", bajar=True)
        with engine.connect() as con:
            assert con.execute(text("SELECT to_regclass('catalogo_cpe')")).scalar() is None
            assert con.execute(text("SELECT count(*) FROM information_schema.columns WHERE "
                                    "table_name = 'configuracion_empresa' AND column_name LIKE 'cpe_refresco%'")
                               ).scalar() == 0
            assert con.execute(text("SELECT count(*) FROM configuracion_empresa")).scalar() == 1
    finally:
        sesion.rollback()
        with engine.begin() as con:
            con.execute(text("TRUNCATE TABLE configuracion_empresa RESTART IDENTITY CASCADE"))
        _alembic("head")
