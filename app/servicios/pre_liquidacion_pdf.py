"""El PDF de la pre liquidación de transportistas.

Es el documento que se le manda a cada transportista (o a todos juntos) para que confirme lo que se
le va a liquidar. **No es un comprobante**: lleva la leyenda «Pre liquidación — no es un comprobante»
arriba y en el pie de cada hoja.

🔑 **Se arma con las piezas del PDF del motor** (`libracore.pdf_generator`), no con una maqueta
propia: la base que traga cualquier carácter (`_TextoSeguroPDF`), el encabezado con el logo o el
nombre de la empresa y el recuadro de datos, la paleta y los márgenes. Así el papel es de la misma
familia que la pre factura y el resumen de cuenta corriente. El motor no tiene una API pública para
un informe por bloques (sus `generate_pdf_*` son uno por documento), así que acá se usan los helpers
de módulo; **si un salto de versión del motor los renombra, `test_pre_liquidacion.py` se pone rojo en
el CI** (el test genera el PDF de verdad).

El encabezado sale de los **datos de la empresa** (`ConfiguracionEmpresa`), no de la configuración
de archivo del motor: es lo que hace que el papel de cada instancia diga su nombre. El logo vive en
la base, y el encabezado del motor lo quiere como archivo: se baja a un directorio temporal sólo
mientras se dibuja.
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

from libracore import pdf_generator as pg
from sqlalchemy.orm import Session

from app import tiempo
from app.models.configuracion import ConfiguracionEmpresa
from app.servicios.emisor_del_pdf import CONDICION_IVA

#: La leyenda que no puede faltar: es lo que impide que esto se tome por una factura.
LEYENDA = "Pre liquidación — no es un comprobante"

#: Columnas: (clave, encabezado, ancho en mm, alineación). Suman `_CW` (174 mm).
_COLUMNAS = [
    ("fecha", "FECHA", 16, "L"),
    ("orden", "ORDEN", 14, "L"),
    ("remito", "REMITO", 19, "L"),
    ("cliente", "CLIENTE", 28, "L"),
    ("tramo", "ORIGEN → DESTINO", 31, "L"),
    ("cantidad", "CANT.", 13, "R"),
    ("neto", "COMISIÓN", 18, "R"),
    ("iva", "IVA", 16, "R"),
    ("total", "TOTAL", 18, "R"),
]
_ALTO_LINEA = 3.6
_PIE = 24  # mm que se reservan abajo para el pie


def _pesos(valor: Decimal) -> str:
    return "$ " + pg._ar(valor)


def _fecha(valor) -> str:
    return valor.strftime("%d-%m-%Y") if valor else ""


def _cantidad(flete: dict) -> str:
    if flete["cantidad"] is not None:
        texto = f"{flete['cantidad'].normalize():f}".replace(".", ",")
        return f"{texto} {flete['unidad']}" if flete["unidad"] else texto
    return flete["cantidad_legado"] or ""


class PreLiquidacionPDF(pg._TextoSeguroPDF):
    def __init__(self, datos: dict, empresa: dict):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.datos = datos
        self._emp = empresa
        # Sellada con la fecha del período, no con la del momento: reimprimir el mismo rango da los
        # mismos bytes (misma razón que el resto de los PDF del motor).
        self.fijar_fecha_documento(datos["hasta"])
        self.set_margins(pg._LX, pg._LX, pg._LX)
        self.set_auto_page_break(auto=True, margin=_PIE)
        self.alias_nb_pages()

    def header(self):
        d = self.datos
        info = [
            ("Período desde:", _fecha(d["desde"])),
            ("Período hasta:", _fecha(d["hasta"])),
            ("Emitido:", _fecha(tiempo.hoy())),
        ]
        # `_draw_header_block` pone el título en «Title Case» («De» con mayúscula): el título entero va
        # en el cuerpo, y en el recuadro sólo lo que queda bien así.
        y = pg._draw_header_block(self, "PL", "Pre liquidación", "", info, self._emp)
        self.set_y(y)

    def footer(self):
        fy = self.h - _PIE + 4
        self.set_draw_color(*pg._LINE)
        self.set_line_width(0.4)
        self.line(pg._LX, fy, pg._RX, fy)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*pg._WARNING)
        self.set_xy(pg._LX, fy + 2)
        self.cell(pg._CW, 4, LEYENDA, align="C")
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*pg._MUTED)
        self.set_xy(pg._LX, fy + 7)
        self.cell(pg._CW, 4, "Moneda: pesos argentinos. Los importes pueden cambiar hasta que se "
                  "emita el comprobante.", align="C")
        self.set_xy(pg._LX, self.h - 10)
        self.cell(pg._CW, 4, f"Pág. {self.page_no()}/{{nb}}", align="R")
        self.set_text_color(*pg._INK)

    # ── Piezas del cuerpo ────────────────────────────────────────────────

    def _hay_lugar(self, alto: float) -> bool:
        return self.get_y() + alto <= self.h - _PIE

    def titulo_y_empresa(self, empresa_texto: list[str]):
        self.set_x(pg._LX)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*pg._INK)
        self.cell(pg._CW, 7, "Pre liquidación de transportistas", new_x="LMARGIN", new_y="NEXT")
        for linea in empresa_texto:
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*pg._MUTED)
            self.cell(pg._CW, 4, linea, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*pg._INK)
        self.ln(2)
        # La franja con la leyenda, la misma del motor para la pre factura.
        y = self.get_y()
        self.set_fill_color(*pg._WARNING_SOFT)
        self.set_draw_color(*pg._WARNING)
        self.set_line_width(0.6)
        pg._rrect(self, pg._LX, y, pg._CW, 8, style="DF")
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*pg._WARNING)
        self.set_xy(pg._LX, y + 2)
        self.cell(pg._CW, 4, LEYENDA.upper(), align="C")
        self.set_text_color(*pg._INK)
        self.set_fill_color(*pg._WHITE)
        self.set_y(y + 8 + 4)

    def _encabezado_de_tabla(self):
        y = self.get_y()
        x = pg._LX
        self.set_font("Helvetica", "", 6.5)
        self.set_text_color(*pg._MUTED)
        for _clave, titulo, ancho, alin in _COLUMNAS:
            self.set_xy(x, y)
            self.cell(ancho, 6, titulo, align=alin)
            x += ancho
        self.set_draw_color(*pg._INK)
        self.set_line_width(0.5)
        self.line(pg._LX, y + 6, pg._RX, y + 6)
        self.set_y(y + 7)
        self.set_text_color(*pg._INK)

    def _banda_del_transportista(self, b: dict, continua: bool = False):
        y = self.get_y()
        alto = 11
        self.set_fill_color(*pg._ACCENT_SOFT)
        pg._rrect(self, pg._LX, y, pg._CW, alto, style="F")
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*pg._ACCENT_DARK)
        nombre = b["transportista"] + (" (continúa)" if continua else "")
        self.set_xy(pg._LX + 3, y + 1.2)
        self.cell(pg._CW - 6, 4.5, pg._recortar(self, nombre, pg._CW - 6))
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*pg._INK)
        iva = ("suma IVA" if b["discrimina_iva"] else "sin IVA")
        partes = [f"CUIT {b['cuit']}" if b["cuit"] else "Sin CUIT",
                  f"{b['condicion_iva_texto']} ({iva})"]
        self.set_xy(pg._LX + 3, y + 6)
        self.cell(pg._CW - 6, 4, "  ·  ".join(partes))
        self.set_y(y + alto + 1)
        if b["aviso"] and not continua:
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(*pg._WARNING)
            self.set_x(pg._LX)
            self.multi_cell(pg._CW, 3.4, b["aviso"], new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(*pg._INK)
        self._encabezado_de_tabla()

    def _medir_fila(self, valores: dict[str, str], negrita: bool = False):
        self.set_font("Helvetica", "B" if negrita else "", 7)
        anchos = {c[0]: c[2] for c in _COLUMNAS}
        envueltas = {
            k: (pg._wrap_text(self, v, anchos[k] - 2)[:2] if k in ("cliente", "tramo") else [v])
            for k, v in valores.items()}
        lineas = max(len(v) for v in envueltas.values())
        alto = lineas * _ALTO_LINEA + 2.4
        return envueltas, alto

    def dibujar_fila(self, b: dict, valores: dict[str, str], negrita: bool = False,
                     subtotal: bool = False):
        envueltas, alto = self._medir_fila(valores, negrita)
        if not self._hay_lugar(alto + 1):
            self.add_page()
            self._banda_del_transportista(b, continua=True)
        y = self.get_y()
        x = pg._LX
        self.set_font("Helvetica", "B" if negrita else "", 7)
        self.set_text_color(*pg._INK)
        for clave, _titulo, ancho, alin in _COLUMNAS:
            for i, texto in enumerate(envueltas.get(clave, [""])):
                self.set_xy(x + (1 if alin == "L" else 0), y + 1.2 + i * _ALTO_LINEA)
                self.cell(ancho - 1, _ALTO_LINEA, texto, align=alin)
            x += ancho
        self.set_draw_color(*(pg._INK if subtotal else pg._LINE))
        self.set_line_width(0.4 if subtotal else 0.2)
        self.line(pg._LX, y + alto, pg._RX, y + alto)
        self.set_y(y + alto)

    def total_general(self, d: dict):
        alto = 24
        if not self._hay_lugar(alto + 6):
            self.add_page()
        self.ln(5)
        y = self.get_y()
        ancho = pg._TOTALS_W
        x = pg._RX - ancho
        self.set_fill_color(*pg._ACCENT_SOFT)
        pg._rrect(self, x, y, ancho, alto, style="F")
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*pg._ACCENT_DARK)
        self.set_xy(x + 4, y + 2)
        self.cell(ancho - 8, 4, f"TOTAL GENERAL ({d['fletes']} flete{'' if d['fletes'] == 1 else 's'})")
        for i, (etiqueta, valor, grande) in enumerate([
                ("Comisión (neto)", d["neto"], False), ("IVA", d["iva"], False),
                ("Total a liquidar", d["total"], True)]):
            self.set_font("Helvetica", "B" if grande else "", 9 if grande else 8)
            self.set_text_color(*pg._INK)
            self.set_xy(x + 4, y + 7 + i * 5.2)
            self.cell((ancho - 8) / 2, 5, etiqueta)
            self.cell((ancho - 8) / 2, 5, _pesos(valor), align="R")
        self.set_y(y + alto)


def _datos_de_empresa(sesion: Session, directorio_del_logo: Path) -> tuple[dict, list[str]]:
    """El dict de emisor que entiende el encabezado del motor, y las líneas de datos de la empresa.

    Sin datos cargados el papel sale con el encabezado del motor en blanco: **igual sirve**, como la
    orden de carga (lo que no puede pasar es que no se pueda generar por falta de configuración).
    """
    cfg = sesion.get(ConfiguracionEmpresa, 1)
    if cfg is None:
        return {"nombre": "", "logo_path": ""}, []
    logo = ""
    if cfg.logo:
        sufijo = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
            cfg.logo_tipo or "", ".png")
        ruta = directorio_del_logo / f"logo{sufijo}"
        ruta.write_bytes(cfg.logo)
        logo = str(ruta)
    emisor = {"nombre": cfg.nombre_fantasia or cfg.razon_social, "logo_path": logo}
    domicilio = ", ".join(p.strip() for p in (cfg.domicilio, cfg.localidad, cfg.provincia)
                          if p and p.strip())
    fiscal = "  ·  ".join(p for p in (
        cfg.razon_social if cfg.nombre_fantasia else "",
        f"CUIT {cfg.cuit}" if cfg.cuit else "", CONDICION_IVA.get(cfg.condicion_iva, ""),
        f"IIBB {cfg.ingresos_brutos}" if cfg.ingresos_brutos else "") if p)
    contacto = "  ·  ".join(p for p in (cfg.telefono, cfg.email) if p)
    return emisor, [t for t in (domicilio, fiscal, contacto) if t]


def generar(sesion: Session, datos: dict) -> bytes:
    """El PDF de `pre_liquidacion.armar(...)`, en memoria."""
    with tempfile.TemporaryDirectory(prefix="preliq-") as tmp:
        empresa, lineas = _datos_de_empresa(sesion, Path(tmp))
        pdf = PreLiquidacionPDF(datos, empresa)
        pdf.add_page()
        pdf.titulo_y_empresa(lineas)

        if not datos["transportistas"]:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*pg._MUTED)
            pdf.set_x(pg._LX)
            pdf.cell(pg._CW, 8, "No hay fletes con comisión en ese período.")
        for b in datos["transportistas"]:
            # Un bloque no arranca en el último renglón de la hoja: banda, encabezado y un flete.
            if not pdf._hay_lugar(40):
                pdf.add_page()
            pdf._banda_del_transportista(b)
            for f in b["fletes"]:
                pdf.dibujar_fila(b, {
                    "fecha": _fecha(f["fecha"]), "orden": str(f["orden_id"]),
                    "remito": f["remito"] or "", "cliente": f["cliente"],
                    "tramo": f"{f['origen']} → {f['destino']}", "cantidad": _cantidad(f),
                    "neto": pg._ar(f["neto"]), "iva": pg._ar(f["iva"]), "total": pg._ar(f["total"]),
                })
            n = b["cantidad_fletes"]
            pdf.dibujar_fila(b, {
                "cliente": f"Subtotal · {n} flete{'' if n == 1 else 's'}",
                "neto": pg._ar(b["neto"]), "iva": pg._ar(b["iva"]), "total": pg._ar(b["total"]),
            }, negrita=True, subtotal=True)
            pdf.ln(6)

        if datos["transportistas"]:
            pdf.total_general(datos)
        return bytes(pdf.output())
