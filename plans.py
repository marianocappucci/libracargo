"""Los planes comerciales de LibraCargo y qué módulos habilita cada uno.

Fuente de verdad compartida con `libracore.provisioning.nuevo_cliente`, que
asigna el plan al dar de alta un cliente. Mismo patrón que el `plans.py` de los
otros seis productos.

⚠️ **Los precios y el reparto de módulos son una decisión comercial, no
técnica.** Acá quedan alineados con los del resto de la familia y **con el core
sin gatear**, que es el mismo criterio que se tomó en LibraDesk: un LibraCargo
sin órdenes de carga no es un plan más barato, es otra cosa. Cuando el negocio
defina qué se cobra aparte, se cambia este archivo y nada más.

**El core no se gatea**: órdenes de carga, terceros, choferes, vehículos,
localidades, tipos de carga, razones sociales, cuentas corrientes, caja y
comprobantes son lo que define al producto.
"""

PLANES = ["basico", "estandar", "premium"]

PLAN_LABELS = {
    "basico":   "Básico",
    "estandar": "Estándar",
    "premium":  "Premium",
}

# Precio mensual de referencia (informativo, para mostrar en el backoffice).
# Alineado con el resto de la familia.
PLAN_PRECIOS = {
    "basico":   15000,
    "estandar": 25000,
    "premium":  40000,
}

# Básico: el core de la agencia de cargas completo. No son módulos gateables.
_BASICO: set[str] = set()

# Estándar: los reportes parametrizables y la impresión de listados.
_ESTANDAR = _BASICO | {"reportes"}

# Premium: además, el log de actividad — quién hizo qué y cuándo.
_PREMIUM = _ESTANDAR | {"auditoria"}

PLAN_MODULOS = {
    "basico":   sorted(_BASICO),
    "estandar": sorted(_ESTANDAR),
    "premium":  sorted(_PREMIUM),
}

#: Todos los módulos gateables, para que el backoffice pueda listarlos.
MODULOS = sorted(_PREMIUM)

MODULO_LABELS = {
    "reportes":  "Reportes e impresión de listados",
    "auditoria": "Log de actividad",
}
