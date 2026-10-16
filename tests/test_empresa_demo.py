"""La demo muestra la empresa ficticia del producto, nunca la de `config.json` ni la «Empresa Demo SRL» genérica.

Sin `importlib.reload(config_manager)`: recargar el módulo borra el almacén de secretos que la app enchufó al arrancar
y rompe a los tests que vienen después. Se cambian las rutas y la empresa registrada con `monkeypatch`, que las repone.
"""
import json

from libracore import config_manager, emisor_del_pdf
from libracore.demo import clasificar_documento

from app import empresa_demo


def test_la_app_registra_la_empresa_ficticia_al_arrancar(cliente):
    """🔴 Sin `empresa_demo.registrar()` en `crear_app`, el PDF de la demo dice «Empresa Demo SRL» (la del motor)."""
    registrada = config_manager.empresa_demo()
    assert registrada["empresa_nombre"] == empresa_demo.EMPRESA["empresa_nombre"]
    assert registrada["empresa_cuit"] == empresa_demo.EMPRESA["empresa_cuit"]


def test_la_demo_muestra_la_empresa_ficticia(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "LOGO_DIR", str(tmp_path / "logos"))
    monkeypatch.setattr(config_manager, "_empresa_demo", config_manager.empresa_demo())
    monkeypatch.setattr(config_manager, "_logo_demo", config_manager._logo_demo)
    (tmp_path / "config.json").write_text(
        json.dumps({"empresa_nombre": "Cliente Real SRL", "empresa_cuit": "30-11111111-8"}), encoding="utf-8")
    empresa_demo.registrar()
    cfg = config_manager.load()
    assert cfg["empresa_nombre"] == empresa_demo.EMPRESA["empresa_nombre"]
    assert cfg["empresa_cuit"] == empresa_demo.EMPRESA["empresa_cuit"]
    # Y el emisor del PDF es esa empresa aunque el resolvedor del producto traiga otra (ADR-061).
    emisor = emisor_del_pdf.emisor_para(
        {}, resolvedor=lambda documento: {"nombre": "Otra Real SA", "cuit": "30-22222222-0"})
    assert emisor["nombre"] == empresa_demo.EMPRESA["empresa_nombre"]
    assert emisor["cuit"] == empresa_demo.EMPRESA["empresa_cuit"]


def test_fuera_de_una_demo_no_cambia_nada(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text(json.dumps({"empresa_nombre": "Mi Empresa SRL"}), encoding="utf-8")
    assert config_manager.load()["empresa_nombre"] == "Mi Empresa SRL"


def test_la_empresa_es_ficticia():
    assert clasificar_documento(empresa_demo.EMPRESA["empresa_cuit"]) == "ficticio"
    assert empresa_demo.EMPRESA["empresa_email"].endswith(".example")
