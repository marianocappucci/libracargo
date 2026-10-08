"""Los titulares de Carta de Porte (ADR-044): a nombre de quién se emite y quién emite.

ARCA está simulada en el borde del motor (`libracore.arca_wscpe`), como en `test_emision_cpe`: el ticket y sus
relaciones. Lo que se prueba es lo del producto —que la delegación se **lee** del ticket y no se tilda, los cuatro
estados, que una pantalla sin ARCA no se rompe, que el ticket cacheado se reusa y nunca se fuerza otro—, más la
plantilla (las mismas claves que lee la propuesta), el vínculo con Entidades, la traba al emitir y las instrucciones
de delegación. CUIT ficticios con dígito verificador válido: nunca los de Pereiro, Suitrans ni ninguno real.
"""

# ruff: noqa: F811  (las fixtures `arca` y `orden` se importan de test_emision_cpe y los tests las piden por nombre)
from __future__ import annotations

import datetime
from itertools import count

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from libracore import arca_wsaa, arca_wscpe
from libracore.arca_wsfe import cuit_con_verificador_valido
from sqlalchemy import select

from app.models import RegistroAuditoria
from app.models.cartas_porte import PlantillaCpe, TitularCpe
from app.servicios import cartas_porte as cpe_servicio
from app.servicios import emision_cpe, titulares_cpe
from tests.test_cartas_porte import _ticket  # noqa: F401
from tests.test_emision_cpe import (  # noqa: F401
    _cargar_empresa,
    _datos,
    _habilitar,
    _propuesta,
    arca,
    orden,
)

RUTA = "/api/cartas-porte/titulares"


def _cuit(n: int) -> str:
    """Un CUIT ficticio de empresa (30…) con dígito verificador válido, determinado por `n`."""
    for k in count(n * 10):
        base = f"30{k % 10**8:08d}"
        pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
        resto = 11 - sum(int(d) * p for d, p in zip(base, pesos, strict=True)) % 11
        dv = {11: 0, 10: 9}.get(resto, resto)
        cuit = f"{base}{dv}"
        if cuit_con_verificador_valido(cuit):
            return cuit
    raise AssertionError("inalcanzable")


A, B, C, X = (_cuit(n) for n in (1111, 2222, 3333, 4444))


def _alta(cliente, cuit, razon_social="Titular de Prueba SA", **extra):
    r = cliente.post(RUTA, json={"cuit": cuit, "razon_social": razon_social, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _listado(cliente):
    r = cliente.get(RUTA)
    assert r.status_code == 200, r.text
    return r.json()


def _staff(cliente):
    cliente.post("/api/usuarios", json={"username": "marta", "name": "Marta", "password": "una-clave",
                                        "role": "staff"})
    c = TestClient(cliente.app, base_url="https://testserver")
    assert c.post("/auth/login", json={"username": "marta", "password": "una-clave"}).status_code == 200
    return c


# ── La delegación se lee de ARCA ───────────────────────────────────────────

def test_los_cuatro_estados_salen_del_ticket_y_no_de_lo_que_se_cargo(cliente, arca):
    arca["relaciones"] = (A, X)
    _alta(cliente, A, "Delegó SA")
    _alta(cliente, B, "Todavía no SA")
    _alta(cliente, C, "Emite solo SA", emite="titular")
    cliente.post("/api/terceros", json={"razon_social": "Cliente Con Delegación", "cuit": f"{X[:2]}-{X[2:10]}-{X[10]}",
                                        "es_cliente": True})

    r = _listado(cliente)

    por_cuit = {t["cuit"]: t for t in r["titulares"]}
    assert por_cuit[A]["delegacion"] == "delegado"
    assert por_cuit[B]["delegacion"] == "pendiente", "cargado, pero ARCA todavía no lo trae"
    assert por_cuit[C]["delegacion"] == "no_aplica", "emite él: no hay delegación que mirar"
    # El que ARCA trae y no está cargado se ofrece para darlo de alta, con la entidad que ya tiene ese CUIT.
    assert [(s["cuit"], s["tercero"]["razon_social"]) for s in r["sin_cargar"]] == [(X, "Cliente Con Delegación")]
    assert (r["ambiente"], r["verificado"], r["motivo"]) == ("produccion", True, None)
    assert r["cuit_para_catalogos"] == A


def test_cuando_arca_suma_la_relacion_el_pendiente_pasa_a_delegado(cliente, arca):
    _alta(cliente, B)
    assert _listado(cliente)["titulares"][0]["delegacion"] == "pendiente"
    arca["relaciones"] = (B,)
    assert _listado(cliente)["titulares"][0]["delegacion"] == "delegado"


def test_sin_certificado_la_pantalla_no_se_rompe_y_dice_el_motivo(cliente, arca):
    arca["ambientes"] = set()
    _alta(cliente, A)
    r = _listado(cliente)
    assert r["verificado"] is False and r["ambiente"] is None
    assert "certificado" in r["motivo"] and "Configuración" in r["motivo"]
    assert r["titulares"][0]["delegacion"] == "sin_verificar", "ni delegado ni pendiente: no se sabe"
    assert r["sin_cargar"] == []


def test_si_arca_no_contesta_tampoco_se_rompe(cliente, arca, monkeypatch):
    _alta(cliente, A)

    async def cae(empresa, ambiente):
        raise RuntimeError("WSAA: timeout")

    monkeypatch.setattr(arca_wscpe, "autenticar", cae)
    r = _listado(cliente)
    assert r["verificado"] is False and r["ambiente"] == "produccion"
    assert "timeout" in r["motivo"]
    assert r["titulares"][0]["delegacion"] == "sin_verificar"


def test_un_ticket_sin_relaciones_legibles_no_declara_pendiente_a_nadie(cliente, arca, monkeypatch):
    """`cuits_habilitados` da `()` ante un token ilegible: «no se sabe» (como en `emitir`), no «nadie delegó»."""
    _alta(cliente, A)

    async def ilegible(empresa, ambiente):
        return {"token": "no-es-base64", "sign": "SGN"}

    monkeypatch.setattr(arca_wscpe, "autenticar", ilegible)
    r = _listado(cliente)
    assert r["verificado"] is False and "ninguna delegación" in r["motivo"]
    assert r["titulares"][0]["delegacion"] == "sin_verificar"


def _par_con_sujeto(carpeta, cn: str, cuit: str) -> tuple[str, str]:
    """Un certificado y su clave en disco, con el sujeto de los que emite ARCA (`CN=alias`, `serialNumber=CUIT …`)."""
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {cuit}"),
    ])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(ahora - datetime.timedelta(days=1))
            .not_valid_after(ahora + datetime.timedelta(days=700)).sign(clave, hashes.SHA256()))
    crt, key = carpeta / f"{cn}.crt", carpeta / f"{cn}.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                        serialization.NoEncryption()))
    return str(crt), str(key)


def test_el_ticket_que_ya_esta_en_la_cache_se_reusa_y_nunca_se_pide_otro(cliente, tmp_path, monkeypatch):
    """🔴 Pedir un ticket a WSAA tiene costo y ARCA rechaza otro mientras el vigente no venció.

    Esta prueba **no** parcha `arca_wscpe.autenticar`: pasa por el del motor, con su caché de disco. Hay un ticket
    vigente guardado; listar los titulares lo lee, y si en cambio pidiera uno nuevo (`_pedir_ticket`) el test cae.
    """
    cert, clave = _par_con_sujeto(tmp_path, "libracargowscpeprod", "20111111112")
    monkeypatch.setenv("ARCA_TA_DIR", str(tmp_path / "arca_ta"))
    monkeypatch.setattr(cpe_servicio.arca_credenciales, "paths_en_disco_de_servicio",
                        lambda empresa, servicio, ambiente: (cert, clave) if ambiente == "produccion" else ("", ""))
    pedidos = []

    async def no_pedir(*a, **k):
        pedidos.append(a)
        raise AssertionError("se pidió un ticket nuevo a WSAA teniendo uno vigente")

    monkeypatch.setattr(arca_wsaa, "_pedir_ticket", no_pedir)
    ruta = arca_wsaa._ruta_del_ticket(cert, "produccion", "wscpe")
    import os
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    vence = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=10)
    arca_wsaa._guardar_ticket(ruta, {**_ticket(A), "expiracion": vence.isoformat()})
    _alta(cliente, A)

    for _ in range(3):  # abrir la pestaña varias veces no cuesta ni un ticket
        r = _listado(cliente)
        assert r["verificado"] is True
        assert r["titulares"][0]["delegacion"] == "delegado"
    assert pedidos == []


# ── Alta, edición y baja ───────────────────────────────────────────────────

def test_el_alta_se_vincula_sola_a_la_entidad_con_ese_cuit_y_toma_su_nombre(cliente, arca):
    ent = cliente.post("/api/terceros", json={"razon_social": "Agro Vinculada SA", "es_cliente": True,
                                              "cuit": f"{A[:2]}-{A[2:10]}-{A[10]}"}).json()
    t = _alta(cliente, A, razon_social=None)
    assert t["razon_social"] == "Agro Vinculada SA"
    assert t["tercero"] == {"id": ent["id"], "razon_social": "Agro Vinculada SA"}
    assert t["emite"] == "nosotros" and t["activo"] is True


def test_sin_entidad_la_razon_social_es_obligatoria(cliente, arca):
    r = cliente.post(RUTA, json={"cuit": A})
    assert r.status_code == 422 and "razón social" in r.json()["detail"]


def test_el_cuit_se_valida_y_no_se_repite(cliente, arca):
    for malo in ("123", "30-12345678-0", ""):
        assert cliente.post(RUTA, json={"cuit": malo, "razon_social": "X"}).status_code == 422, malo
    _alta(cliente, A)
    r = cliente.post(RUTA, json={"cuit": f"{A[:2]}-{A[2:10]}-{A[10]}", "razon_social": "Otra vez"})
    assert r.status_code == 409 and "ya está cargado" in r.json()["detail"]


def test_editar_cambia_quien_emite_pero_no_el_cuit_y_queda_en_la_auditoria(cliente, arca, sesion):
    t = _alta(cliente, A)
    r = cliente.put(f"{RUTA}/{t['id']}", json={"razon_social": "Nuevo Nombre SA", "emite": "titular",
                                               "activo": False, "notas": "Emite con su software"})
    assert r.status_code == 200, r.text
    assert (r.json()["cuit"], r.json()["emite"], r.json()["activo"], r.json()["notas"]) == (
        A, "titular", False, "Emite con su software")
    asientos = sesion.scalars(select(RegistroAuditoria).where(RegistroAuditoria.entidad == "titular_cpe")
                              .order_by(RegistroAuditoria.id)).all()
    assert [a.accion.value for a in asientos] == ["alta", "modificacion"]
    assert asientos[1].datos_despues["emite"] == "titular"
    assert cliente.put(f"{RUTA}/9999", json={"razon_social": "x", "emite": "nosotros", "activo": True}
                       ).status_code == 404


def test_borrar_saca_al_titular_pero_deja_su_plantilla(cliente, arca, sesion):
    t = _alta(cliente, A)
    assert cliente.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": {"cod_grano": 19}}).status_code == 200
    assert cliente.delete(f"{RUTA}/{t['id']}").status_code == 204
    assert _listado(cliente)["titulares"] == []
    assert sesion.get(PlantillaCpe, A) is not None, "lo último emitido a su nombre se conserva"
    assert cliente.delete(f"{RUTA}/{t['id']}").status_code == 404


def test_ver_es_de_staff_y_escribir_es_de_un_administrador(cliente, arca):
    t = _alta(cliente, A)
    staff = _staff(cliente)
    assert staff.get(RUTA).status_code == 200
    assert staff.get(f"{RUTA}/{t['id']}/plantilla").status_code == 200
    assert staff.post(RUTA, json={"cuit": B, "razon_social": "X"}).status_code == 403
    assert staff.put(f"{RUTA}/{t['id']}", json={"razon_social": "X", "emite": "nosotros", "activo": True}
                     ).status_code == 403
    assert staff.delete(f"{RUTA}/{t['id']}").status_code == 403
    assert staff.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": {}}).status_code == 403
    assert staff.delete(f"{RUTA}/{t['id']}/plantilla").status_code == 403


# ── La plantilla: las mismas claves que lee la propuesta ───────────────────

PLANTILLA = {
    "sucursal": 2,
    "origen": {"tipo": "campo", "cod_provincia": 1, "cod_localidad": 13575, "renspa": "01.001.0.00001/00"},
    "cod_grano": 19, "cosecha": 2526,
    "destino": {"cuit": "30650849805", "cod_provincia": 1, "cod_localidad": 11128, "planta": 715070,
                "es_campo": False},
    "cuit_destinatario": "30650849805",
    "intervinientes": {"cuitCorredorVentaPrimaria": "20-12345678-6", "cuitMercadoATermino": ""},
    "cuit_remitente_comercial_productor": A,
    "mercaderia_fumigada": True, "km": 80, "observaciones": "Descarga de 6 a 14",
}


def test_la_plantilla_guardada_es_la_que_la_propuesta_de_emision_usa(cliente, arca, orden):
    t = _alta(cliente, "30876543210", "Agro Titular SA")  # el titular del fixture de emisión
    r = cliente.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": PLANTILLA})
    assert r.status_code == 200, r.text
    guardada = r.json()
    assert guardada["existe"] is True
    # Lo vacío no se guarda y los CUIT quedan en dígitos: la clave ausente es «que lo complete quien emite».
    assert guardada["datos"]["intervinientes"] == {"cuitCorredorVentaPrimaria": "20123456786"}
    assert guardada["datos"]["cuit_destinatario"] == "30650849805"

    p = _propuesta(cliente, orden)
    assert p["de_plantilla"] is True
    assert (p["sucursal"], p["cod_grano"], p["cosecha"]) == (2, 19, 2526)
    assert p["cuit_destinatario"] == "30650849805"
    assert p["intervinientes"] == {"cuitCorredorVentaPrimaria": "20123456786"}
    assert p["cuit_remitente_comercial_productor"] == A
    assert p["transporte"]["mercaderia_fumigada"] is True
    assert (p["destino"]["planta"], p["observaciones"]) == (715070, "Descarga de 6 a 14")
    assert p["faltantes"] == []


def test_una_plantilla_vacia_se_guarda_y_leerla_sin_haberla_cargado_da_vacio(cliente, arca):
    t = _alta(cliente, A)
    assert cliente.get(f"{RUTA}/{t['id']}/plantilla").json() == {"datos": {}, "existe": False, "actualizada": None}
    assert cliente.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": {}}).json()["existe"] is True
    assert cliente.delete(f"{RUTA}/{t['id']}/plantilla").status_code == 204
    assert cliente.get(f"{RUTA}/{t['id']}/plantilla").json()["existe"] is False


@pytest.mark.parametrize(("datos", "texto"), [
    ({"clave_inventada": 1}, "clave_inventada"),
    ({"cosecha": 25260}, "cosecha"),
    ({"km": 0}, "km"),
    ({"km": 100000}, "km"),
    ({"cuit_destinatario": "123"}, "CUIT"),
    ({"destino": {"cuit": "30-12345678-0"}}, "CUIT"),
    ({"intervinientes": {"cuitInventado": "20123456786"}}, "interviniente desconocido"),
    ({"intervinientes": {"cuitCorredorVentaPrimaria": "1234"}}, "CUIT"),
    ({"origen": {"tipo": "puerto"}}, "tipo"),
    ({"observaciones": "x" * 2001}, "observaciones"),
])
def test_la_plantilla_rechaza_lo_que_la_emision_rechazaria(cliente, arca, datos, texto):
    t = _alta(cliente, A)
    r = cliente.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": datos})
    assert r.status_code == 422, r.text
    assert texto in r.text
    assert cliente.get(f"{RUTA}/{t['id']}/plantilla").json()["existe"] is False, "nada se guardó a medias"


def test_los_intervinientes_son_los_del_motor():
    """`arca_wscpe._ORDEN_INTERVINIENTES` es privada: se copió. Si el motor suma uno, acá cae el rojo."""
    assert emision_cpe.INTERVINIENTES == arca_wscpe._ORDEN_INTERVINIENTES


def test_la_plantilla_queda_en_la_auditoria(cliente, arca, sesion):
    t = _alta(cliente, A)
    cliente.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": {"cod_grano": 19}})
    cliente.put(f"{RUTA}/{t['id']}/plantilla", json={"datos": {"cod_grano": 23}})
    cliente.delete(f"{RUTA}/{t['id']}/plantilla")
    asientos = sesion.scalars(select(RegistroAuditoria).where(RegistroAuditoria.entidad == "plantilla_cpe")
                              .order_by(RegistroAuditoria.id)).all()
    assert [a.accion.value for a in asientos] == ["alta", "modificacion", "baja"]
    assert asientos[1].datos_antes == {"datos": {"cod_grano": 19}}


# ── Emitir: la lista frena al que emite solo, pero no a quien sólo ARCA conoce ─

def _emitir(cliente, orden, **cambios):
    return cliente.post("/api/cartas-porte/emision/emitir",
                        json={"orden_id": orden, "datos": _datos(_propuesta(cliente, orden), **cambios)})


def test_un_titular_cargado_como_emite_el_no_se_emite_desde_aca_aunque_arca_lo_delegue(cliente, arca, orden):
    arca["ambientes"] = {"homologacion"}
    t = _alta(cliente, "30876543210", "Agro Titular SA", emite="titular")
    r = _emitir(cliente, orden)
    assert r.status_code == 409 and "emite sus propias" in r.json()["detail"]
    assert arca["emitidas"] == []
    cliente.put(f"{RUTA}/{t['id']}", json={"razon_social": "Agro Titular SA", "emite": "nosotros", "activo": True})
    assert _emitir(cliente, orden).status_code == 201


def test_un_titular_dado_de_baja_no_emite(cliente, arca, orden):
    arca["ambientes"] = {"homologacion"}
    _alta(cliente, "30876543210", "Agro Titular SA", activo=False)
    r = _emitir(cliente, orden)
    assert r.status_code == 409 and "dado de baja" in r.json()["detail"]
    assert arca["emitidas"] == []


def test_un_cuit_que_solo_esta_en_el_ticket_sigue_pudiendo_emitir(cliente, arca, orden):
    """Lo que ya andaba con un titular delegado y todavía no cargado (el primer cliente) no se rompe."""
    arca["ambientes"] = {"homologacion"}
    assert _listado(cliente)["titulares"] == []
    assert _emitir(cliente, orden).status_code == 201


# ── La línea de la ficha del cliente ───────────────────────────────────────

def test_la_ficha_del_cliente_dice_su_estado_y_solo_consulta_a_arca_si_emitimos_nosotros(cliente, arca, monkeypatch):
    ent = cliente.post("/api/terceros", json={"razon_social": "Agro Ficha SA", "es_cliente": True,
                                              "cuit": f"{A[:2]}-{A[2:10]}-{A[10]}"}).json()
    otro = cliente.post("/api/terceros", json={"razon_social": "Agro Solo SA", "es_cliente": True,
                                               "cuit": f"{C[:2]}-{C[2:10]}-{C[10]}"}).json()
    sin_titular = cliente.post("/api/terceros", json={"razon_social": "No es titular", "es_cliente": True}).json()
    assert cliente.get(f"{RUTA}/de-tercero/{sin_titular['id']}").json() is None

    arca["relaciones"] = ()  # ARCA todavía no trae la delegación
    t = _alta(cliente, A)
    assert cliente.get(f"{RUTA}/de-tercero/{ent['id']}").json()["delegacion"] == "sin_verificar"
    arca["relaciones"] = (B,)
    f = cliente.get(f"{RUTA}/de-tercero/{ent['id']}").json()
    assert (f["id"], f["delegacion"], f["emite"]) == (t["id"], "pendiente", "nosotros")
    arca["relaciones"] = (A,)
    assert cliente.get(f"{RUTA}/de-tercero/{ent['id']}").json()["delegacion"] == "delegado"

    # El que emite solo no cuesta una consulta a ARCA.
    _alta(cliente, C, "Agro Solo SA", emite="titular")

    async def no_deberia(empresa, ambiente):
        raise AssertionError("consultó a ARCA por un titular que emite él")

    monkeypatch.setattr(arca_wscpe, "autenticar", no_deberia)
    f = cliente.get(f"{RUTA}/de-tercero/{otro['id']}").json()
    assert (f["emite"], f["delegacion"]) == ("titular", "no_aplica")
    assert cliente.get(f"{RUTA}/de-tercero/9999").status_code == 404


def test_el_vinculo_elegido_a_mano_manda_sobre_el_cuit(cliente, arca):
    otra = cliente.post("/api/terceros", json={"razon_social": "Grupo Madre SA", "es_cliente": True}).json()
    t = _alta(cliente, A, "Campo Hijo SA", tercero_id=otra["id"])
    assert t["tercero"]["razon_social"] == "Grupo Madre SA"
    assert cliente.get(f"{RUTA}/de-tercero/{otra['id']}").json()["id"] == t["id"]
    assert cliente.post(RUTA, json={"cuit": B, "razon_social": "X", "tercero_id": 99999}).status_code == 404


# ── Instrucciones de delegación ────────────────────────────────────────────

def test_las_instrucciones_salen_del_certificado_cargado(cliente, arca, tmp_path, monkeypatch):
    cert, clave = _par_con_sujeto(tmp_path, "libracargowscpeprod", "20111111112")
    monkeypatch.setattr(cpe_servicio.arca_credenciales, "paths_en_disco_de_servicio",
                        lambda e, s, ambiente: (cert, clave) if ambiente == "produccion" else ("", ""))
    r = cliente.get(f"{RUTA}/instrucciones")
    assert r.status_code == 200, r.text
    assert r.json() == {"disponible": True, "ambiente": "produccion", "alias": "libracargowscpeprod",
                        "cuit_representante": "20111111112", "motivo": None}


def test_si_solo_hay_homologacion_las_instrucciones_lo_dicen(cliente, arca, tmp_path, monkeypatch):
    cert, clave = _par_con_sujeto(tmp_path, "libracargowscpehomo", "20111111112")
    monkeypatch.setattr(cpe_servicio.arca_credenciales, "paths_en_disco_de_servicio",
                        lambda e, s, ambiente: (cert, clave) if ambiente == "homologacion" else ("", ""))
    r = cliente.get(f"{RUTA}/instrucciones").json()
    assert (r["disponible"], r["ambiente"], r["alias"]) == (True, "homologacion", "libracargowscpehomo")


def test_sin_certificado_o_con_uno_ilegible_las_instrucciones_no_se_inventan(cliente, arca, tmp_path):
    arca["ambientes"] = set()
    r = cliente.get(f"{RUTA}/instrucciones").json()
    assert r["disponible"] is False and r["alias"] is None and "certificado" in r["motivo"]
    arca["ambientes"] = {"produccion"}  # el par de la fixture apunta a /c.crt, que no existe
    r = cliente.get(f"{RUTA}/instrucciones").json()
    assert r["disponible"] is False and "No se pudo leer" in r["motivo"]


def test_las_instrucciones_no_llevan_cuit_ni_alias_escritos_en_el_codigo():
    """El texto de referencia sale de los datos del certificado: ningún CUIT ni alias fijo en el servicio."""
    import inspect
    import re

    fuente = inspect.getsource(titulares_cpe)
    assert not re.search(r"\b(20|23|24|27|30|33|34)\d{9}\b", fuente)
    assert "libracargowscpe" not in fuente


def test_el_modelo_es_el_que_la_migracion_crea(sesion):
    """Una fila mínima toma los defaults de la base: quien emite es «nosotros» y está activo."""
    sesion.add(TitularCpe(cuit=A, razon_social="Mínimo SA"))
    sesion.commit()
    t = sesion.scalars(select(TitularCpe)).one()
    assert (t.emite, t.activo, t.tercero_id, t.notas) == ("nosotros", True, None, None)
