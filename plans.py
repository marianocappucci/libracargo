"""El plan de LibraCargo: uno solo, «Plan único», y qué módulos habilita.

Fuente de verdad compartida con `libracore.provisioning.nuevo_cliente`, que
asigna el plan al dar de alta un cliente, y con `libracore.admin.services`, que
lo muestra en el backoffice. Mismo patrón que el `plans.py` de VentaLibra.

**Un único plan** (ADR-049, decisión del humano 2026-10-14). Se llama `unico`
(etiqueta «Plan único») y **no tiene precio cargado**: LibraCargo publica
«Consultar precio», así que `PLAN_PRECIOS = {"unico": None}` y el backoffice lo
muestra sin importe (`planes_info()` lo lee con `.get` y admite `None`). Ya no
existen Básico, Estándar ni Premium.

Historia: este archivo nació con tres planes (15.000 / 25.000 / 40.000, «alineados
con la familia»), que nunca fueron un precio publicado ni se le cobraron a nadie.
Repartían dos módulos, `reportes` (Estándar) y `auditoria` (Premium), que **nunca
gatearon nada**: la tabla `modulos` está vacía en las instancias y ni la SPA ni el
servidor los ocultan —el core no se gatea: órdenes de carga, terceros, choferes,
vehículos, localidades, tipos de carga, cuentas corrientes, caja y comprobantes son
lo que define al producto—. El único gate real de este producto es el add-on
`resguardo_externo` (`ADDONS`, `app.addons`). Por eso el plan único no cambia lo
que ve ni lo que puede hacer ninguna instancia: sólo deja de ofrecer una escalera
que no escalaba nada.

## Lo que ya no existe, y qué pasa con las instancias que lo tienen guardado

Las instancias guardan su plan en el `cliente.json` (`plan = "premium"` en la
mayoría). Nada de eso se toca a mano:

- **Planes retirados** (`basico`, `estandar`, `premium`): ver `PLANES_RETIRADOS`.
  `modulos_de_plan` y `plan_vigente` los resuelven como `unico`, avisando con un
  `WARNING`. Como el plan único no tiene módulos gateables, el reemplazo trae lo
  mismo que cualquiera de ellos tenía: no se pierde ni se gana nada.
- **El motor** hace lo mismo del lado del alta y del backoffice
  (`libracore.provisioning.resolver_plan`, libracore ≥ v1.151.0): `crear_cliente`
  con `plan="basico"` (su default) y el formulario del backoffice dan de alta en
  `unico`, y el backoffice busca la instancia vieja en el único plan vigente
  (`libracore.admin.services.plan_vigente`). Un plan que no es de ninguna de las
  dos listas (un typo) no se adivina.
- **Módulos retirados**: ver `MODULOS_RETIRADOS`.
"""
import logging

logger = logging.getLogger(__name__)

PLANES = ["unico"]

PLAN_LABELS = {"unico": "Plan único"}

# Sin precio: LibraCargo publica «Consultar precio» y no hay un número que mostrar
# (ADR-049). `libracore.admin.services.planes_info()` lo lee con `.get` y el
# backoffice lo muestra sin importe. No inventarlo acá: se carga cuando exista.
PLAN_PRECIOS = {"unico": None}

# El core no se gatea: no hay módulos que repartir por plan.
PLAN_MODULOS: dict[str, set[str]] = {"unico": set()}

# Planes que existieron y ya no se venden, con el plan que los reemplaza. Hoy los
# tres se resuelven como `unico`. El reemplazo trae todo lo que cualquiera de ellos
# tenía (que era nada gateable), así que la instancia no pierde ni gana nada.
PLANES_RETIRADOS = {"basico": "unico", "estandar": "unico", "premium": "unico"}

# Módulos que el plan repartía y nunca gatearon nada: `reportes` (Estándar) y
# `auditoria` (Premium). Quedan listados para que quien encuentre uno en una fila
# vieja de `modulos` sepa que no es un olvido. Ni la SPA ni el servidor los leen.
MODULOS_RETIRADOS = {"reportes", "auditoria"}

#: Todos los módulos gateables, para que el backoffice pueda listarlos. Hoy
#: ninguno: los add-ons no van acá (ver `ADDONS`).
MODULOS = sorted(set().union(*PLAN_MODULOS.values()))

MODULO_LABELS: dict[str, str] = {}


def plan_vigente(plan: str) -> str:
    """El plan con el que se opera hoy: el mismo, o el que reemplaza a uno retirado.

    Un plan retirado (`PLANES_RETIRADOS`) se resuelve **avisando**, no en
    silencio: queda un `WARNING` en el log. Uno desconocido vuelve igual (no es
    un plan retirado y no hay a qué mapearlo); quien lo aplica decide qué hacer.
    """
    reemplazo = PLANES_RETIRADOS.get(plan)
    if reemplazo is None:
        return plan
    logger.warning(
        "El plan %r ya no se vende (ADR-049): se lo trata como %r.", plan, reemplazo,
    )
    return reemplazo


def modulos_de_plan(plan: str) -> set[str]:
    """Los módulos habilitados para un plan (vacío si el plan es desconocido).

    Un plan retirado se resuelve como su reemplazo (`plan_vigente`).

    🔴 La llama `libracore.admin.services.planes_info()`, que es `GET
    /api/planes` del backoffice. Sin ella esa ruta da 500, y como la pantalla
    de una instancia pide planes junto con la instancia, **«Administrar» queda
    en blanco** — medido en LibraClub el 2026-09-15, con este mismo hueco acá.
    Mismo contrato que en el resto de la familia.
    """
    return set(PLAN_MODULOS.get(plan_vigente(plan), ()))


def aplicar_plan_en_db(db_path: str, plan: str) -> None:
    """Escribe el estado de módulos de una instancia.

    El alta la corre DENTRO del contenedor (`nuevo_cliente._aplicar_plan_en_contenedor`). Es un shim sobre
    `libracore.provisioning.apply_plan_modules`, igual que en el resto de la familia. **LibraCargo no tenía esta
    función** (nunca la definió): sin ella el alta de una instancia nueva terminaba en `AltaIncompleta`.

    Con el plan único no hay módulos que gatear (`PLAN_MODULOS["unico"]` es vacío): no prende ni apaga nada, y los
    add-ons (`ADDONS`) quedan afuera a propósito. Un plan retirado se aplica como `unico` (`plan_vigente`, con su
    aviso); uno desconocido levanta `ValueError`, para que un error de tipeo no se confunda con «todo apagado».
    """
    vigente = plan_vigente(plan)
    if vigente not in PLAN_MODULOS:
        raise ValueError(f"Plan desconocido: {plan!r}. Los vigentes son {PLANES}.")
    from libracore.provisioning import apply_plan_modules
    apply_plan_modules(
        db_path, active_modules=set(PLAN_MODULOS[vigente]),
        all_modules=set(MODULOS) - ADDONS, plan=vigente,
    )


# ── Add-ons ──────────────────────────────────────────────────────────────────
#
# Un add-on **no pertenece a ningún plan**: está disponible en cualquiera, viene
# apagado y se prende por instancia desde el backoffice. Es el primero de
# LibraCargo.
#
# El backoffice (`libracore.admin.services.set_addon`) valida el nombre contra
# este conjunto y después lo escribe corriendo `app.database.set_addon` ADENTRO
# del contenedor. Por eso no va en `MODULOS` ni en `MODULO_LABELS`, que listan
# lo que reparten los planes, y por eso `libracore.db.modulos.apply_plan` saltea
# estas claves: si cambiar de plan las tocara, subir o bajar de plan apagaría un
# adicional en silencio.
#
# - `resguardo_externo`: la copia externa del backup en la nube del propio
#   cliente (Google Drive o Dropbox), enlazada desde Configuración → Datos. El
#   gate es `app.addons.require_addon`.
ADDONS = {"resguardo_externo"}
