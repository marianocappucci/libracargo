#!/usr/bin/env python3
"""Datos de ejemplo de la instancia demo pública.

Va **por la API** y no por SQL: así los comprobantes, el estado de las órdenes y
los asientos de cuenta corriente salen del mismo camino que usa el producto, y
no de un `INSERT` que puede dejar invariantes rotas que después la pantalla
reporta como alarma. El gate de F5 —que los totales por razón social coincidan
por los dos lados— vale sobre estos datos justamente por eso.

**Vive en el repo y no suelto en el servidor.** El estado limpio de la demo es
código: agregar un dato de ejemplo es un commit, no una operación manual sobre
el VPS a las cuatro de la mañana. `scripts/reset_demo.sh` lo saca de
`origin/develop` cada noche.

🔴 **Las fechas son relativas a hoy.** Con fechas fijas, a los tres meses la demo
muestra órdenes de un mes que ya pasó, los reportes "del período" salen vacíos y
el tablero —que mira el mes en curso— queda en cero. Un visitante que entra a
eso concluye que el sistema no anda.

Se corta solo si ya hay terceros cargados: es un seed, no un importador.

    python3 seed_demo.py --url https://demo.libracargo.com.ar \\
        --usuario admin --password "$LIBRACARGO_ADMIN_PASSWORD"
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", required=True, help="Base de la instancia, con https://")
parser.add_argument("--usuario", default="admin")
parser.add_argument("--password", required=True)
args = parser.parse_args()

BASE = args.url.rstrip("/")

cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=30) as r:
            texto = r.read().decode()
            return r.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def crear(ruta, cuerpo, etiqueta):
    codigo, salida = pedir("POST", ruta, cuerpo)
    if codigo != 201:
        print(f"  x {etiqueta}: {codigo} {salida}")
        sys.exit(1)
    print(f"  ok {etiqueta} -> id {salida['id']}")
    return salida["id"]


def hace(dias: int) -> str:
    """Una fecha relativa a hoy, en ISO. Ver el 🔴 del encabezado."""
    return (date.today() - timedelta(days=dias)).isoformat()


# ---- sesión ---------------------------------------------------------------
# 🔴 Por `https://` y no por el puerto local: la cookie de sesión está marcada
# `Secure`, así que sobre http el login devuelve 200 y **todo lo demás 401** —
# se lee como "el login no anda" cuando lo que pasa es que la cookie no vuelve.
codigo, _ = pedir("POST", "/auth/login", {"username": args.usuario, "password": args.password})
if codigo != 200:
    print(f"login: {codigo}")
    sys.exit(1)
print("sesion abierta")

codigo, terceros = pedir("GET", "/api/terceros")
if codigo != 200:
    print(f"no se puede leer terceros: {codigo} -- la cookie no viajo?")
    sys.exit(1)
if terceros:
    print(f"ya hay {len(terceros)} terceros cargados: no toco nada")
    sys.exit(0)

# ---- maestros -------------------------------------------------------------
print("maestros")
agro = crear("/api/terceros", {
    "razon_social": "Agro del Oeste SA", "cuit": "30-71234567-9",
    "condicion_iva": "responsable_inscripto", "es_cliente": True,
    "localidad": "Suipacha", "provincia": "Buenos Aires",
    "telefono": "2324-441122", "contacto": "Marta Gil"}, "cliente Agro del Oeste")
molinos = crear("/api/terceros", {
    "razon_social": "Molinos Suipacha", "cuit": "30-70987654-3",
    "condicion_iva": "responsable_inscripto", "es_cliente": True,
    "localidad": "Suipacha", "provincia": "Buenos Aires"}, "cliente Molinos Suipacha")
aguirre = crear("/api/terceros", {
    "razon_social": "Transportes Aguirre", "cuit": "20-24567890-1",
    "condicion_iva": "monotributo", "es_fletero": True, "es_proveedor": True,
    "localidad": "Mercedes", "provincia": "Buenos Aires"}, "fletero Transportes Aguirre")
# Cliente y fletero a la vez: es el caso que hace que la cuenta sea el PAR
# (tercero, rol) y no el tercero solo.
cerealera = crear("/api/terceros", {
    "razon_social": "Cerealera del Sur", "cuit": "30-65432109-8",
    "condicion_iva": "responsable_inscripto", "es_cliente": True, "es_fletero": True,
    "localidad": "Bahia Blanca", "provincia": "Buenos Aires"},
    "cliente Y fletero Cerealera del Sur")

suipacha = crear("/api/localidades", {"nombre": "Suipacha", "provincia": "Buenos Aires"},
                 "Suipacha")
mercedes = crear("/api/localidades", {"nombre": "Mercedes", "provincia": "Buenos Aires"},
                 "Mercedes")
rosario = crear("/api/localidades", {"nombre": "Rosario", "provincia": "Santa Fe"}, "Rosario")
bahia = crear("/api/localidades", {"nombre": "Bahia Blanca", "provincia": "Buenos Aires"},
              "Bahia Blanca")

ramon = crear("/api/choferes", {"nombre": "Ramon Ferreyra", "dni": "24567890",
                                "fletero_id": aguirre}, "chofer Ramon Ferreyra")
julio = crear("/api/choferes", {"nombre": "Julio Aguirre", "dni": "20345678",
                                "fletero_id": aguirre}, "chofer Julio Aguirre")

scania = crear("/api/vehiculos", {"patente_chasis": "AB123CD", "patente_acoplado": "AC456EF",
                                  "observaciones": "Scania con batea", "fletero_id": aguirre},
               "vehiculo AB123CD")
iveco = crear("/api/vehiculos", {"patente_chasis": "AD789GH", "observaciones": "Iveco chasis",
                                 "fletero_id": aguirre}, "vehiculo AD789GH")

cereal = crear("/api/tipos-carga", {"nombre": "Cereal", "unidad_default": "kg"}, "Cereal")
general = crear("/api/tipos-carga", {"nombre": "Carga general", "unidad_default": "bultos"},
                "Carga general")

# Las dos razones sociales, cada una con su punto de venta.
suitrans = crear("/api/razones-sociales", {
    "nombre": "Suitrans SRL", "cuit": "30-11223344-5",
    "condicion_iva": "responsable_inscripto", "punto_venta": 1}, "razon social Suitrans SRL")
mauricio = crear("/api/razones-sociales", {
    "nombre": "Mauricio Cappucci", "cuit": "20-22334455-6",
    "condicion_iva": "monotributo", "punto_venta": 2}, "razon social Mauricio Cappucci")

# ---- órdenes --------------------------------------------------------------
print("ordenes de carga")


def ordenar(dias_atras, cliente, origen, destino, tarifa, **extra):
    fecha = hace(dias_atras)
    cuerpo = {"fecha": fecha, "cliente_id": cliente, "origen_id": origen,
              "destino_id": destino, "tarifa": tarifa, **extra}
    return crear("/api/ordenes", cuerpo, f"orden {fecha} . {tarifa}")


o1 = ordenar(18, agro, suipacha, rosario, "845000.00", fletero_id=aguirre,
             chofer_id=ramon, vehiculo_id=scania, tipo_carga_id=cereal,
             cantidad="30000", unidad="kg", remito="0001-00012345",
             comision="84500.00", razon_social_id=suitrans)
o2 = ordenar(16, agro, suipacha, bahia, "1120000.00", fletero_id=aguirre,
             chofer_id=julio, vehiculo_id=iveco, tipo_carga_id=cereal,
             cantidad="28500", unidad="kg", remito="0001-00012346",
             comision="112000.00", razon_social_id=suitrans)
o3 = ordenar(14, molinos, mercedes, rosario, "610500.50", fletero_id=aguirre,
             chofer_id=ramon, vehiculo_id=scania, tipo_carga_id=general,
             cantidad="140", unidad="bultos", remito="0001-00012347",
             comision="61050.05", razon_social_id=mauricio)
# Estas quedan PENDIENTES: son las que se ven en "facturar pendientes".
o4 = ordenar(9, agro, suipacha, mercedes, "398000.00", fletero_id=aguirre,
             chofer_id=julio, tipo_carga_id=cereal, cantidad="12000", unidad="kg",
             remito="0001-00012348", comision="39800.00")
o5 = ordenar(7, molinos, suipacha, rosario, "742300.00", fletero_id=aguirre,
             chofer_id=ramon, vehiculo_id=scania, tipo_carga_id=cereal,
             cantidad="26000", unidad="kg", remito="0001-00012349",
             comision="74230.00")
o6 = ordenar(5, cerealera, bahia, rosario, "1580000.00", fletero_id=aguirre,
             chofer_id=julio, vehiculo_id=iveco, tipo_carga_id=cereal,
             cantidad="31000", unidad="kg", remito="0001-00012350",
             comision="158000.00")
# Una anulada, para que el listado muestre los tres estados.
o7 = ordenar(5, molinos, mercedes, bahia, "205000.00", tipo_carga_id=general,
             cantidad="40", unidad="bultos", remito="0001-00012351")
codigo, _ = pedir("DELETE", f"/api/ordenes/{o7}")
print(f"  ok orden {o7} anulada -> {codigo}")

# ---- comprobantes ---------------------------------------------------------
print("comprobantes")


def facturar(dias_atras, razon, cliente, numero, ordenes, punto_venta, etiqueta):
    return crear("/api/comprobantes", {
        "fecha": hace(dias_atras), "razon_social_id": razon, "cliente_id": cliente,
        "tipo": "factura_a", "punto_venta": punto_venta, "numero": numero,
        "orden_ids": ordenes}, etiqueta)


# Una factura que agrupa DOS órdenes: es lo que en el legado hacía "facturar
# pendientes".
c1 = facturar(11, suitrans, agro, 1041, [o1, o2], 1, "Factura A 0001-00001041")
c2 = facturar(10, mauricio, molinos, 388, [o3], 2, "Factura A 0002-00000388")
# Y una anulada, para que se vea el estado y la reversión en la cuenta.
c3 = facturar(8, suitrans, cerealera, 1042, [o6], 1, "Factura A 0001-00001042")
codigo, _ = pedir("DELETE", f"/api/comprobantes/{c3}")
print(f"  ok comprobante {c3} anulado -> {codigo}")

# ---- caja -----------------------------------------------------------------
print("caja")
crear("/api/caja", {"fecha": hace(7), "tipo": "ingreso",
                    "concepto": "Cobro factura 0001-00001041", "tercero_id": agro,
                    "rol": "cliente", "importe": "1500000.00",
                    "medio_pago": "transferencia", "recibo": "R-000210"}, "cobro a Agro")
crear("/api/caja", {"fecha": hace(6), "tipo": "egreso",
                    "concepto": "Pago de fletes del mes", "tercero_id": aguirre,
                    "rol": "fletero", "importe": "980000.00",
                    "medio_pago": "transferencia", "recibo": "OP-000144"}, "pago a Aguirre")
# Sin tercero: un gasto general no mueve ninguna cuenta corriente.
crear("/api/caja", {"fecha": hace(4), "tipo": "egreso", "concepto": "Gasoil y peajes",
                    "importe": "185400.00", "medio_pago": "efectivo"},
      "gasto general sin tercero")

# ---- lo que quedó ---------------------------------------------------------
# No es decoración: es la contraprueba de que lo sembrado deja al producto en un
# estado coherente. Si los totales no coincidieran, la demo estaría mostrando la
# alarma roja que el propio sistema levanta cuando algo no cierra.
print("\nasi quedo la demo:")
for ruta, nombre in (("/api/terceros", "terceros"), ("/api/ordenes", "ordenes"),
                     ("/api/comprobantes", "comprobantes"), ("/api/caja", "caja")):
    _, filas = pedir("GET", ruta)
    print(f"  {nombre}: {len(filas)}")
_, pendientes = pedir("GET", "/api/ordenes?facturada=false&estado=pendiente")
print(f"  ordenes pendientes de facturar: {len(pendientes)}")

problemas = 0
_, totales = pedir("GET", "/api/comprobantes/totales")
for t in totales:
    print(f"  razon social {t['razon_social_id']}: comprobantes {t['total_comprobantes']} . "
          f"ordenes {t['total_ordenes']} . coinciden {t['coinciden']}")
    problemas += 0 if t["coinciden"] else 1
_, cuenta = pedir("GET", f"/api/cuentas/cliente/{agro}")
print(f"  cuenta de Agro del Oeste: saldo {cuenta['saldo']} . "
      f"recorriendo {cuenta['saldo_recorriendo']} . coinciden {cuenta['coinciden']}")
problemas += 0 if cuenta["coinciden"] else 1

if problemas:
    print(f"\nx {problemas} verificacion(es) no coinciden: la demo quedaria mostrando alarmas")
    sys.exit(1)
print("\nok las verificaciones del producto coinciden por los dos caminos")
