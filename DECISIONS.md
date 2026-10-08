# Decisiones arquitectónicas — LibraCargo

Registro ADR. No se borran decisiones: si dejan de aplicar, se marcan como
reemplazadas.

## ADR-001 — PostgreSQL como único motor, sin default

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: el estándar de la familia (2026-08-12) es PostgreSQL en producción,
  dev y tests. Una suite verde sobre SQLite no dice nada del motor real: no
  chequea FK con el pragma apagado y acepta cadenas donde la base pide enteros.
- Decisión: `app/config.py` **exige** `DATABASE_URL` y rechaza cualquier
  esquema que no sea PostgreSQL. No hay valor por defecto.
- Consecuencias: no se puede levantar la app "rápido" sin base. Es deliberado.
- Alternativas descartadas: default a SQLite para desarrollo — es exactamente
  la puerta por la que entraron los defectos que el estándar vino a cerrar.

## ADR-002 — `terceros` con roles, en vez de tres maestros

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: en Suitrans, `clientes`, `fleteros` y `proveedores` tienen **las
  mismas 13 columnas** — el mismo formulario copiado tres veces. Y `ctacteprov`
  lleva **a la vez** `proveedor_id` y `fletero_id`: en los datos reales las
  entidades ya se cruzan, y el modelo viejo no tiene dónde decirlo.
- Decisión: una tabla `terceros` con `es_cliente`/`es_fletero`/`es_proveedor`, y
  una cuenta corriente por par *(tercero, rol)*.
- Consecuencias: un fletero que también es proveedor tiene dos cuentas y una
  sola ficha. Requiere el `CHECK` de al menos un rol.
- Alternativas descartadas: mantener tres maestros por paridad literal con el
  legado; arrastraba la duplicación sin resolver el cruce.

## ADR-003 — La migración no deduplica terceros

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: los 276 maestros del legado probablemente tengan CUITs repetidos
  entre sí.
- Decisión: entran los 276 como terceros distintos, cada uno con su rol y su
  `origen_legado`. La fusión por CUIT es **posterior**, asistida, con una
  persona aprobando de a uno.
- Consecuencias: al principio hay fichas duplicadas. Es preferible a lo otro.
- Alternativas descartadas: fusionar por CUIT durante la carga — es la forma
  más rápida de romperle las tres cuentas corrientes a un cliente real.

## ADR-004 — `NUMERIC` para todo importe

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: Suitrans usa `float(10,2)` en las 14 tablas. `FLOAT` de MySQL es
  **precisión simple**: no hace falta sumar nada para perder plata. Medido:
  $1.500.000,55 se guarda como $1.500.000,50 —cinco centavos en una sola fila—
  y $1.234.567,89 como $1.234.567,88.
- Decisión: `NUMERIC(14,2)` para dinero y `NUMERIC(12,3)` para cantidades.
- Consecuencias: los saldos migrados **van a diferir** de los del sistema viejo.
  Esa diferencia es el error que el `float` venía arrastrando, y se entrega
  como reporte por tercero para que el cliente lo valide.
- Alternativas descartadas: `double precision` — corrige la pérdida por fila
  pero sigue sin ser exacto para dinero.

## ADR-005 — El IVA se calcula en el servidor

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: el legado lo calcula en JavaScript (`importe * 21/100`) y el PHP
  guarda lo que llegue por POST, sin recalcular ni validar. La alícuota está
  fija y la condición de IVA del cliente no participa.
- Decisión: el cálculo es del servidor; la alícuota sale de la condición de IVA
  del tercero. El navegador sólo previsualiza.
- Consecuencias: hay que relevar con el cliente si existen operaciones al 10,5%
  o exentas, hoy corregidas a mano en algún lado.

## ADR-006 — Estado explícito en la orden, y FK al comprobante

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: en el legado el estado se derivaba de dos banderas
  (`carga_facturado`, `carga_fsuitrans`) y el "número de factura" era un entero
  copiado a mano, sin relación real.
- Decisión: `estado` es un `ENUM` y `comprobante_id` es una FK, con un `CHECK`
  que exige comprobante si y sólo si la orden está `facturada`.
- Consecuencias: no se puede marcar una orden como facturada sin emitir.

## ADR-007 — El downgrade de la migración borra los tipos ENUM

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: Alembic autogenera el `DROP TABLE` pero **no el de los tipos
  `ENUM`**. Sin corregirlo, el downgrade deja los 7 tipos huérfanos y el
  upgrade siguiente muere con `DuplicateObject`. **La migración parecía
  reversible y no lo era** — se descubrió corriendo el ciclo completo, no
  leyéndola.
- Decisión: `DROP TYPE IF EXISTS` explícito al final de `downgrade()`, y un
  test que corre `upgrade → downgrade → upgrade` sobre una base descartable.
- Consecuencias: cada migración futura que agregue un `ENUM` tiene que sumar su
  `DROP TYPE`. El test lo detecta si se olvida.

## ADR-008 — Facturación ARCA diferida

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: el sistema viejo no emite, registra un número que alguien tipea.
- Decisión: replicar primero el registro manual. La emisión por ARCA vía
  LibraCore es una fase posterior.
- Consecuencias: se puede comparar totales contra el sistema viejo durante la
  migración. Si se mezclaran, una diferencia tendría dos causas posibles y
  ninguna forma de separarlas.

## ADR-009 — Los importes negativos se normalizan invirtiendo la columna

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: el perfilado sobre el dump real encontró **1.779 importes negativos**
  en las tres cuentas corrientes (101 en clientes, 1.664 en fleteros, 14 en
  proveedores), casi todos en la columna del haber. El caso más grande son dos
  asientos de "ajuste" por −108.357.828 sobre una cuenta de seguros. El resto de
  la lectura se confirmó: `importe1`/`importe2` **sí** son debe y haber —cero
  filas mueven las dos columnas a la vez—, así que el signo negativo se estuvo
  usando como "el asiento va para el otro lado".
- Decisión: un haber de −X entra como **debe de +X**, y viceversa. Se anota en
  `observaciones` que el signo se normalizó, con el valor original.
- Consecuencias: el saldo de cada tercero queda **idéntico** al del legado
  —invertir columna y signo es la identidad sobre `debe − haber`— y el `CHECK`
  `(debe > 0 AND haber = 0) OR (haber > 0 AND debe = 0)` se cumple sin relajarlo.
- Alternativas descartadas: **relajar el `CHECK`** y migrar tal cual — el sistema
  nuevo heredaría para siempre la ambigüedad que vino a corregir, y un asiento
  podría significar dos cosas según el signo. **Frenar y consultar al cliente**:
  la inversión no pierde información ni cambia ningún saldo, así que no hay nada
  que consultar; lo que sí se le va a preguntar es qué fue el ajuste de −108 M,
  pero eso es una pregunta de negocio, no un bloqueo de la migración.

## ADR-010 — Las 17 órdenes sin factura entran con un comprobante de apertura

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: **17 órdenes de agosto de 2023** —los primeros días del sistema—
  están marcadas `carga_facturado = 1` pero con `carga_factura = 0` y
  `carga_razonsocial = 0`: no hay ninguna fila en `facturas` que las respalde.
  Suman $2.950.434,06. El modelo nuevo tiene un `CHECK` que no deja una orden en
  `facturada` sin comprobante.
- Decisión: se crea **un comprobante de apertura** —punto de venta `0`, número
  `0`, `origen_legado = 'apertura'`— que agrupa las 17. Sus importes son la suma
  de esas órdenes, como cualquier otro comprobante.
- Consecuencias: se conserva que ya estaban facturadas y cobradas, no aparecen en
  "facturar pendientes" como plata por cobrar que no existe, y **el gate de F5
  sigue cerrando**: el total del comprobante es exactamente el de sus órdenes.
  El comprobante es identificable por su numeración en cero.
- Alternativas descartadas: migrarlas como **pendientes** —17 órdenes de 2023
  aparecerían como cobranza pendiente— o como **anuladas**, que dice algo falso:
  se hicieron y se cobraron.

## ADR-011 — Las cuentas internas entran como terceros, marcadas

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: **19 de los 186 "fleteros" nunca aparecen en una orden de carga**.
  Son cuentas internas: la oficina, el galpón, un auto, el contador, los seguros
  de carga. La cuenta corriente de fleteros se usa además como caja de gastos —de
  hecho el mayor saldo del sistema (−30,4 M) es una cuenta de seguros, no un
  transportista.
- Decisión: entran como **terceros con rol fletero**, como cualquier otro, con la
  marca en `observaciones`. No se crea una categoría nueva.
- Consecuencias: ningún saldo ni movimiento se pierde ni se mueve de lugar, y la
  migración no toma una decisión de producto. La reorganización —si hace falta un
  concepto de centro de costos— se decide con el cliente **después**, con los
  datos ya adentro y sobre la lista concreta de 19.
- Alternativas descartadas: inventar el rol o el tipo "cuenta interna" durante la
  migración. Es diseño de producto decidido sobre la marcha, sin el cliente, y
  sobre una lista que él todavía no vio.

## ADR-012 — Las fechas `0000-00-00` se infieren del id vecino, con su contrapartida como control

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: hay **4 filas con `0000-00-00`**, que son **2 operaciones** con su
  contrapartida: la novedad 483 con su asiento en `clientectacte` ($42.000), y un
  par `fleteroctacte`/`ctacteprov` ($28.245,32). `date NOT NULL` de MySQL admite
  la fecha cero; `date` de PostgreSQL no.
- Decisión: se toma la fecha de los **ids vecinos**, que en estas tablas son
  cronológicos, y se confirma cruzando con la contrapartida. Da **2023-10-23**
  para la primera operación (vecinos 482 y 484, los dos ese día) y **2025-01-06**
  para la segunda (vecinos 6704 y 6706, los dos ese día). Se anota en
  `observaciones` que la fecha es inferida.
- Consecuencias: 4 filas con una fecha inventada, marcadas como tales, en vez de
  4 filas rechazadas o puestas en una fecha centinela que después nadie entiende.
- Alternativas descartadas: fecha centinela (`1900-01-01`) —mete un movimiento
  fuera de todo rango real y descuadra cualquier corte por fecha— o descartar las
  filas, que cambiaría el saldo de dos terceros.

## ADR-013 — Una sola razón social: el `2` del legado no existe en los datos

- Estado: aceptada. **La tabla de razones sociales se retiró en ADR-035**: el emisor único es «Datos de la
  empresa», y lo migrado del legado pertenece a ella.
- Fecha: 2026-08-18
- Contexto: el `<select>` del legado ofrece `1 = Suitrans` y `2 = Mauricio`, y
  `bajarpendientes.php` usa además un `0`. Medido sobre el dump: **las 741
  facturas y 4.317 de las 4.337 órdenes usan `1`**; las otras 20 usan `0`; **el
  `2` no aparece en ninguna fila de ninguna tabla**.
- Decisión: se crea **una** razón social, Suitrans, con `codigo_legado = 1`. El
  `0` no crea una segunda: las 17 órdenes que lo llevan quedan bajo el
  comprobante de apertura (ADR-010) con la razón social Suitrans, y las 3
  restantes —no facturadas— entran con razón social nula, que el modelo permite.
- Consecuencias: el maestro refleja lo que el cliente usa, no lo que el
  formulario ofrecía. Si Mauricio vuelve a facturar, es un alta de una fila.
- Alternativas descartadas: crear las dos "porque estaban en el `<select>`" —un
  maestro con una fila que nadie usó, y un valor más para elegir mal.

## ADR-014 — Lo que no entra en el modelo nuevo se conserva, no se corrige

- Estado: aceptada
- Fecha: 2026-08-18
- Contexto: tres clases de valor del legado no encajan en las columnas nuevas.
  Medidas, son pocas: **12 de 4.337** `carga_cantidad` no numéricas (`shap +
  later`, `832.23 x 6988.46`, `27.73 (28)`, `.`), más 11 vacías; **2 CUITs** de
  más de 13 caracteres; y **551 descripciones truncadas** a 50 por MySQL.
- Decisión: la cantidad no numérica va a **`cantidad_legado`** con `cantidad` en
  nulo —la columna existe para esto—; el CUIT se **normaliza** sacándole guiones y
  espacios antes de guardarlo; el texto truncado se migra **tal cual**.
- Consecuencias: no se pierde ningún dato y ninguno se inventa. Las 12 cantidades
  quedan visibles para que una persona las cargue bien cuando toque esa orden.
- Alternativas descartadas: interpretar `832.23 x 6988.46` como un producto o
  `27.73 (28)` como 28. Es adivinar sobre plata ajena. Y "completar" el texto
  truncado: el final de la cadena no está en ningún lado.

## ADR-015 — Las restricciones de forma valen para lo que se carga de ahora en adelante

- Estado: aceptada
- Fecha: 2026-08-19
- Contexto: al escribir la transformación aparecieron **42 filas que los `CHECK`
  rechazan**, y que el perfilado no había levantado porque medía el legado y no
  las restricciones del modelo nuevo: **33 órdenes con origen = destino** —viajes
  dentro de la misma localidad, repartidos en 6 localidades y 3 años—, **36
  asientos de cuenta con debe y haber en cero**, y **6 movimientos de caja con
  importe cero** que tienen descripción real ("echeq 5948941", "recibí
  $7.000.000") y a los que nadie les cargó el importe.
- Decisión: los tres `CHECK` pasan a condicionarse a `origen_legado IS NULL`
  (migración `0003`). Rigen para **todo lo que se carga desde el sistema nuevo** y
  no para el histórico migrado, que entra completo y marcado.
- Consecuencias: el conteo por tabla cierra contra el legado —que es el gate del
  paso 5— y ninguna fila se pierde. Un alta nueva sigue sin poder salir y llegar
  al mismo lugar, ni asentar un movimiento que no mueve plata. El `downgrade` de
  la migración **falla a propósito** si hay histórico cargado: reponer la regla
  estricta con esas filas adentro dejaría la base violando su propia restricción.
- El criterio general, que es lo que hay que recordar: se **adapta la forma**
  cuando la adaptación no cambia el significado —invertir el signo de un asiento,
  ADR-009— y se **relaja la regla** cuando adaptarla exigiría inventar un dato que
  no está en ningún lado. Nunca al revés.
- Alternativas descartadas: **no migrar las 42 filas** —el saldo no cambiaría,
  porque suman cero, pero se perderían 42 registros con su descripción y el
  conteo dejaría de cuadrar— y **relajar los `CHECK` para todos**, que le regala
  al sistema nuevo, para siempre, dos de las cosas que vino a impedir.

## ADR-016 — LibraCore entra por el backup, antes que por la impresión

**Fecha**: 2026-08-19 · **Estado**: aceptada

El plan tenía a LibraCore entrando en F7, para la impresión de comprobantes. El
backup se pidió antes, y el backup de la familia vive en ese mismo paquete.

Se adelanta **el paquete, no el alcance**: hoy este producto importa
`libracore.respaldo` y `libracore.config_router.build_backup_router`, y nada
más. `pdf_generator` sigue siendo F7 y ARCA sigue siendo F8.

La advertencia sobre el consumo parcial de LibraCore —las tres trampas que
documenta LibraDesk— **no aplica a este tramo**: las tres son de la capa de
datos (el `PRAGMA foreign_keys` no configurable, `init_core_schema()` que no es
componible por tabla, y el DDL que no es el schema real porque hay columnas que
agrega una migración aparte). `respaldo` no toca ninguna: recibe una URL de
conexión y corre `pg_dump`. La advertencia sigue vigente para F7 y F8.

**La alternativa descartada** era escribir un backup propio. Se descartó porque
ese módulo es, casi entero, una lista de modos de falla que ya se pagaron en la
familia: el backup que sale vacío y no se queja, el restore que contesta `ok`
sin efecto porque el proceso no soltó la conexión, el ZIP de otro producto que
se restaura encima, el `pg_restore` de otra major que aborta la transacción
entera. Reimplementarlo era volver a aprenderlos de a uno.

## ADR-017 — La salud se sirve en `/salud` **y** en `/health`

**Fecha**: 2026-08-19 · **Estado**: aceptada

Este producto nombra todo en castellano y su sonda era `/salud`. El provisioning
de la familia le estampa a cada instancia nueva un healthcheck contra
`health_path`, cuyo default es `/health` porque es lo que sirven los otros seis.

Se sirven **las dos rutas sobre el mismo handler**.

**Por qué no alcanzaba con dejar `/salud` y parametrizar el provisioning.** Se
podía: `configure()` acepta `health_path`. Pero el valor efectivo lo fija el
último `configure()` que corre, y `libracore.admin.services` importa
`nuevo_cliente` y `panel_admin` en el mismo proceso sobre un `_cfg` **global**.
Un producto que depende de ese argumento tiene una forma de romperse que los
otros seis no tienen. Converger a la ruta que ya cumple todo el mundo saca el
parámetro del medio.

**Por qué no renombrar `/salud` a secas.** Está en el `HEALTHCHECK` del
Dockerfile, en el README y en los tests. Dos rutas sobre una función no pueden
divergir; una ruta renombrada y un consumidor sin actualizar, sí.

🔴 **El modo de falla que esto cierra no es un 404.** Con la SPA horneada,
`app/asgi.py` responde cualquier ruta desconocida con el `index.html`: un
healthcheck apuntado a una ruta inexistente devuelve **200**, y la instancia se
reporta sana aunque la base esté caída. Le pasó a [[libradesk]] y no lo encontró
el diff — lo encontró medir adentro del contenedor. `tests/test_provisioning.py`
ata las dos puntas: saca las rutas del router y exige que la del provisioning
esté entre ellas.


## ADR-018 — La orden asienta en la cuenta del fletero, y el signo lo da el rol

- Estado: aceptada
- Fecha: 2026-08-20
- Contexto: el chequeo de paridad contra el sistema legado encontró que
  **LibraCargo nunca escribía en la cuenta corriente del fletero**. En el legado,
  `altaordencarga.php` inserta en `fleteroctacte` con la **comisión** — por eso es
  la tabla más movida del sistema, 12.995 filas contra 6.267 de la de clientes.
  Acá `comision` se leía sólo para los reportes. Medido sobre la instancia del
  cliente: de los **8.674** movimientos que apuntan a una orden, **cero** son
  posteriores a la migración. El defecto no se veía porque la instancia todavía
  no tiene órdenes nuevas; habría aparecido después del corte, con la cuenta de
  un fletero mostrando **pagos sin cargos** y el saldo corriendo para un lado.
- Tirando de ese hilo apareció un segundo defecto, en el mismo lugar: el asiento
  de caja decidía la columna **sólo por el tipo de movimiento**, con un comentario
  que lo afirmaba explícitamente ("el signo lo da el movimiento y no el rol"). Con
  esa regla, **pagarle a un fletero le aumentaba el saldo** en vez de cancelarlo.
- Decisión:
  1. El alta de una orden con fletero y comisión crea el asiento en `debe`, **en
     la misma transacción** que la orden. La edición lo corrige en el lugar —una
     línea en la cuenta, no dos, igual que el `UPDATE` de `modifica_carga.php`— y
     la anulación lo **revierte con un contraasiento** que lleva la fecha de la
     orden, no la de hoy.
  2. La columna del asiento de caja depende del **par (rol, tipo)**:

     | Cuenta | Ingreso | Egreso |
     |---|---|---|
     | Cliente | cobranza → `haber` | devolución → `debe` |
     | Fletero / proveedor | devolución → `debe` | pago → `haber` |

     Es la convención del legado y la de los 22.645 movimientos migrados: el
     cargo va a `debe` y el pago a `haber` en las tres cuentas. Lo que cambia es
     cuál de los dos es un ingreso, porque para un cliente el saldo positivo es
     lo que **debe** y para un fletero es lo que se le **debe**.
- Consecuencias: no hace falta migración de datos — el histórico ya trae sus
  asientos y lo que faltaba era el camino nuevo. **Dos tests existentes cambiaron
  de número**, y los dos afirmaban la premisa equivocada: uno esperaba `+40` tras
  pagarle 40 a un fletero, y el ranking de fleteros esperaba que el saldo fuera el
  pago con el signo cambiado.
- Lo que **no** se hizo, a propósito: el legado también inserta en
  `clientectacte` al dar de alta la orden. Acá el cliente debe cuando se le
  factura, y ese asiento lo hace el comprobante — duplicarlo en el alta contaría
  el importe dos veces. La diferencia visible para el cliente es que su cuenta
  corriente lleva **una línea por factura** y no una por orden.


## ADR-019 — Provincias y localidades se eligen de un catálogo, pero el campo sigue guardando texto

- Estado: aceptada
- Fecha: 2026-08-20
- Contexto: el cliente pidió *"que no se carguen mal y sólo se seleccionen"*. El
  maestro de localidades —el que se usa como origen y destino de una orden—
  tenía **121 filas cargadas a mano y ninguna con provincia**: en el legado,
  `origen` y `destino` eran dos tablas con una sola columna de nombre. Adentro
  conviven `Gral Paz` **y** `Gral. Paz`, `Pto San Martín` **y**
  `Pto. San Martín`, `Pilar` **y** `Pilar (BA)`, junto a `Campo`, `Shap`,
  `Coincer` y `(sin nombre)`.
- Decisión:
  1. El catálogo —24 provincias y 4.027 localidades— vive en **LibraCore**
     (`libracore.geografia`), no acá: los seis productos manejan direcciones y
     ninguno lo tenía. Se monta con `build_geo_router()` y la dependencia de rol
     de este producto, igual que el router de backup.
  2. Se usa en **los dos lugares**: el maestro de localidades y la dirección del
     tercero.
  3. 🔑 **El campo sigue guardando texto, no un id del catálogo.**
- Por qué texto y no una clave foránea al catálogo, que es lo que primero se
  quiere hacer:
  - **Los datos viejos no se pierden.** Al abrir un tercero cuya localidad dice
    `Cnel. Bogado` —que no está en el catálogo con esa abreviatura— el campo
    arranca **en modo texto con el valor puesto**. Un desplegable que no
    encuentra el valor guardado lo mostraría vacío, y guardar sin tocar nada
    borraría el dato. Hay un test de eso, verificado en rojo.
  - **Hay lugares reales que no están en ningún recurso oficial.** Tomás Jofré
    no está ni en `localidades`, ni en `localidades-censales`, ni en
    `asentamientos`. Con un desplegable cerrado, ese viaje no se puede cargar.
  - Una FK obligaría además a migrar las 121 filas a ids antes de poder guardar
    nada, y 58 de ellas no tienen a dónde apuntar.
- La migración **`0005`** completa la provincia sólo donde el nombre matchea
  **exactamente una** localidad del catálogo: 63 de 121. Las 17 ambiguas
  (`San Pedro` está en ocho provincias) y las 41 que no matchean quedan como
  están, para que las resuelva una persona con el desplegable puesto. Y sólo
  escribe donde `provincia IS NULL`: un dato cargado a mano vale más que uno
  deducido.
- Consecuencias: el `downgrade` de la `0005` **no deshace nada**, y está escrito
  por qué — poner en nulo lo que escribió borraría también lo que cargue una
  persona después, y no hay forma de distinguirlos.


## ADR-020 — La configuración de ARCA cuelga de la razón social, y verifica los archivos al subirlos

- Estado: aceptada. **Reemplazada en parte por ADR-035**: la configuración
  ya no cuelga de una razón social (no hay) sino de la empresa; sólo se emite si su CUIT es el de «Datos de la empresa».
- Fecha: 2026-08-20
- Contexto: el humano pidió *"agregar la configuración de ARCA y facturación
  electrónica"*, y al plantear el alcance eligió **sólo la pantalla de
  configuración por ahora** — emitir queda para cuando haya certificados. (De
  paso descartó MercadoPago: se había confundido de producto.)
- Decisión 1 — **una configuración por razón social**, no por instancia. El
  certificado de ARCA es **de un CUIT**, y el CUIT acá lo tiene la razón social:
  `razones_sociales` ya guarda `cuit` y `punto_venta`. Una configuración por
  instancia obligaría a elegir cuál de las razones sociales factura, que es
  exactamente lo que el legado resolvía con un entero hardcodeado en el HTML.
- Decisión 2 — **el certificado y la clave se guardan en la base**, como el logo
  del membrete y por el mismo motivo: el backup de esta instancia es
  **exactamente un dump** (`directorios=[]`), así que lo que está en la base
  entra en el ZIP y lo que está en disco no. Con las credenciales afuera,
  restaurar un backup dejaría una instancia que no puede facturar **y no lo
  dice**.
  > ⚠️ La contracara, que hay que saber: el ZIP de backup que el cliente puede
  > descargar **lleva adentro la clave privada**. Es su propia clave y su propio
  > backup —que ya trae todos sus datos—, pero conviene que no viaje por mail.
- Decisión 3 — **los archivos se validan al subirlos, no al emitir.** Es lo que
  esta pantalla aporta de verdad, porque los tres errores de armado no se ven
  mirando el nombre del archivo:
  1. subir el `.csr` —el pedido— en vez del `.crt` que ARCA devolvió;
  2. subir el certificado en el campo de la clave, o al revés;
  3. 🔑 subir un certificado y una clave que **no son pareja**, porque se generó
     una clave nueva y se subió el certificado viejo. Los dos archivos son
     válidos, se ven perfectos en pantalla, y ARCA rechaza la autenticación con
     un error genérico. Se compara la clave pública del certificado contra la de
     la clave privada.
  Y se muestra **cuándo vence**: duran dos años, y el día que vencen la
  facturación deja de andar sin que nadie haya tocado nada.
- Consecuencias: `habilitado` no se puede poner sin las dos mitades —hay un
  `CHECK` en la base, no sólo una validación— y **cambiar una mitad apaga la
  bandera**, porque puede haber roto la pareja. El ambiente por omisión es
  **homologación**: pasar a producción tiene que ser un acto deliberado.
- Lo que **no** hace: emitir. El comprobante se sigue registrando con el número
  que tipea una persona. Cuando se implemente la emisión, la capa de protocolo
  ya existe en LibraCore (`arca_wsaa` + `arca_wsfe`); lo que **no** se puede
  reusar es `arca_facturacion`, que está atado al esquema de `facturas` y
  `arca_config` de LibraCore y este producto tiene el suyo.
  > ⚠️ **Este último punto quedó superado el 2026-08-24 por el ADR-024**, que
  > implementa la emisión. Lo de arriba se conserva como estaba —es lo que se
  > decidió entonces y por qué— pero **ya no describe el comportamiento
  > vigente**. La otra mitad de este ADR, la de MercadoPago, sigue en pie.


## ADR-021 — El bloque de proveedores es un gasto imputado a un fletero, no una factura de compra

- Estado: aceptada
- Fecha: 2026-08-21
- Contexto: era el hueco más grande del chequeo de paridad — el bloque
  **COMPROBANTES PROVEEDORES** del legado, sin equivalente. El nombre engañaba, y
  antes de modelar nada se perfilaron los **3.347 registros** de `ctacteprov`:

  | | |
  |---|---:|
  | Gastos (importe en el debe) | **2.799** |
  | Pagos (importe en el haber) | 539 — ya cubiertos por caja |
  | Gastos **imputados a un fletero** | **2.799 de 2.799** |
  | Gastos **con número de comprobante** | **0 de 2.799** |
  | Tipo usado | **"Remito"** en 2.806, no "Factura" |

- Decisión: se modela **el gasto**, que es lo que hacen: lo que el proveedor
  entrega y **se le descuenta al fletero**. Un gasto deja **dos asientos en una
  transacción** — proveedor al `debe`, fletero al `haber` —, que en el legado
  eran dos `INSERT` sueltos en dos tablas.
  1. **El fletero es obligatorio**, no un campo que a veces se completa: los
     2.799 lo tienen. Un gasto que no se le descuenta a nadie es un gasto general
     de la agencia y va por caja, que ya lo soporta.
  2. **El número de comprobante es opcional.** El campo existe en el legado y
     **nadie lo usó nunca**; hacerlo obligatorio sería inventar un requisito que
     el negocio no tiene.
  3. **No es un documento fiscal**: sin tipo A/B/C, sin punto de venta y sin IVA
     discriminado. Cuando eso haga falta —con ARCA emitiendo y el IVA compras
     importando— será otro documento, no este con campos agregados.
- Consecuencias: editar corrige **los dos asientos en el lugar** —una línea por
  cuenta, como el `UPDATE` de `modifica_ctacteprov.php`— y anular **no borra**:
  deja las dos líneas y agrega sus dos contrapartidas, con la fecha del gasto.
- **El histórico no se convierte.** Los 2.799 del legado ya están como
  movimientos de cuenta con los saldos validados por el gate de F6. Crearles un
  documento retroactivo duplicaría el importe salvo que además se reescribieran
  esos movimientos, y eso es tocar historia conciliada para no ganar nada. La
  tabla arranca vacía.
- Alternativa descartada: **la factura de compra completa**. Habría que decidir
  qué hacer con 2.799 registros que no tienen ni número, ni tipo, ni IVA — y
  construir campos que hoy nadie llena.


## ADR-022 — Un movimiento de caja se anula, no se borra, y el anulado no suma

- Estado: aceptada
- Fecha: 2026-08-21
- Contexto: era el último hueco técnico del chequeo de paridad. El bloque
  NOVEDAD del legado tiene **Modificar** y **Eliminar**, y acá sólo había
  `POST /api/caja`: un cobro mal cargado no tenía forma de corregirse.
- Qué hace el legado: `modifica_novedad.php` actualiza la novedad **y su fila de
  cuenta corriente** en el lugar; `elimina_novedad.php` hace **tres `DELETE`
  sueltos** —cliente, fletero, proveedor— y después borra la novedad.
- Decisión:
  1. **Editar corrige el movimiento y su contrapartida**, en el lugar y en una
     transacción. Una línea por cuenta, como el `UPDATE` del legado. Cambiar el
     tercero o el rol **mueve** el asiento; sacarle el tercero lo borra;
     agregarle uno lo crea.
  2. **Anular no borra.** El movimiento queda con `anulado`, su asiento se
     revierte con una contrapartida y los dos siguen a la vista. Borrar hacía
     que un cobro desapareciera sin rastro y que el **número de recibo quedara
     con un hueco que nadie podía explicar**.
  3. 🔴 **El anulado sigue en el listado pero NO suma en los totales.** Son dos
     cosas distintas y las dos hacen falta: el listado lo muestra porque el
     hueco en la numeración necesita explicación; el resumen y el reporte de
     caja lo excluyen porque si no, un cobro dado de baja sigue contando en los
     ingresos del período y el número se ve perfectamente plausible.
- Consecuencias: los **dos** agregados de caja llevan el filtro
  (`servicios/reportes.py`), y hay un test que anula un cobro y verifica que el
  total baje **y** que el listado lo siga trayendo. La regla del signo del
  asiento —que depende del par (rol, tipo)— salió del alta a
  `servicios/caja.py`, porque la edición y la anulación no tenían de dónde
  sacarla sin repetirla.
- La migración `0008` agrega la columna **con `server_default`**, y el modelo lo
  declara igual. Sin el default, agregar una columna `NOT NULL` falla en una
  tabla con filas —la instancia del cliente tiene **8.387**— y el `COPY` del ETL
  de migración, que no nombra la columna, inserta `NULL`. Ninguna de las dos
  cosas se ve en una base vacía.

## ADR-023 — Los listados se imprimen desde Reportes, y ahí el rango es obligatorio

- Estado: aceptada
- Fecha: 2026-08-22
- Contexto: cinco pantallas —órdenes, comprobantes, comprobantes de proveedores,
  caja y el log— tenían su propio botón **Imprimir** arriba a la derecha. El
  botón hacía lo correcto —volvía a pedir el listado paginando, en vez de
  fotografiar la página que se veía— pero **nada obligaba a filtrar antes**: se
  apretaba con la pantalla recién abierta y salían las 4.337 órdenes en unas
  noventa hojas. Sobre la instancia de Suitrans el log arranca con **15.884
  registros migrados**, así que ahí el papel era peor todavía.
- Decisión:
  1. **Los listados salen del catálogo de reportes**, con `detalle: true`. Son
     cinco entradas nuevas (`listado-ordenes`, `listado-comprobantes`,
     `listado-gastos`, `listado-caja`, `listado-logs`) que aparecen en su propia
     sección del índice, separadas de los ocho agregados de siempre.
  2. 🔴 **Sin `desde` y `hasta` no hay listado.** El endpoint contesta **422** y
     la pantalla ni siquiera lo pide: muestra por qué falta y **no dibuja el
     botón de imprimir**. Las dos mitades hacen falta — la del backend porque la
     regla es del reporte y no del dibujo, la del frontend porque un 422 en la
     cara no explica que falta elegir fechas.
  3. **Los endpoints no repiten la consulta**: cada uno delega en el mismo
     `listar` que sirve la pantalla. Un filtro nuevo o un orden distinto en el
     listado aparece en el papel sin tocar nada — que es justo lo que no pasaba
     cuando cada pantalla armaba su propia impresión.
  4. **El log cambia de lugar, no de permiso.** `listado-logs` lleva
     `require_admin` **además** del `require_staff` del router, y el catálogo lo
     esconde para quien no es admin: un ítem que se ve y contesta 403 es un menú
     roto.
- Qué NO se movió: la impresión de **una** orden —el ícono de la fila y el botón
  del detalle— y la de **una** cuenta corriente. Las dos ya están acotadas a un
  registro o a un tercero: son una hoja, no un listado.
- Consecuencias:
  - `traerTodo` recibe el tamaño de tanda del endpoint que va a pedir. 🔴 No es
    cosmético: corta cuando una tanda viene más corta que lo pedido, así que
    pedirle 500 a un endpoint de tope 500 comparando contra 1.000 hacía que la
    **primera** tanda pareciera la última — y la hoja salía con 500 filas y
    `truncado: false`, o sea diciendo que había traído todo. Es lo que hacía el
    log.
  - `GET /api/caja` gana `desplazamiento` y `medio_pago`. Le faltaba la
    paginación —era el único listado sin ella— y la hoja de caja la suplía con
    un `desplazamiento > 0 ? [] : …` que pedía **una** tanda y perdía en
    silencio lo que no entrara.
  - La grilla del reporte dibuja las primeras 200 filas y **lo dice**: abajo de
    la tabla aclara cuántas hay y cuántas se están viendo. Un corte callado se
    lee como el listado completo, y ahí la pantalla y el papel dicen cosas
    distintas.


## ADR-024 — Emitir por ARCA reemplaza al alta manual, pero sólo donde ARCA está habilitado

- Estado: aceptada
- Fecha: 2026-08-24
- Supersede: la mitad **"emitir"** del ADR-020. La otra mitad de aquel —
  MercadoPago descartado, *"se había confundido de producto"*— **sigue en pie**.
- Contexto: el ADR-020 difirió la emisión *"para cuando haya certificados"*, y
  el ROADMAP la dejó como una línea: *"F8 — Emisión ARCA real vía LibraCore"*.
  Con la paridad de la migración ya verificada (F5), el humano reabrió esa
  mitad. El diseño no estaba escrito, y tenía tres decisiones abiertas.

- Decisión 1 — **el número lo da ARCA, no la persona**, y no admite convivencia
  dentro de un mismo comprobante. ARCA numera correlativamente por punto de
  venta y tipo, y rechaza cualquier número que no sea
  `FECompUltimoAutorizado + 1`: uno tipeado a mano que coincida es casualidad, y
  uno que no, es un rechazo. El punto de venta sale de la razón social, que es
  donde está dado de alta en ARCA. Un `numero` en el payload se ignora.

- Decisión 2 — 🔑 **pero el alta manual no desaparece de golpe: sobrevive donde
  ARCA no está habilitado.** Es una precisión sobre la decisión anterior, y el
  motivo es operativo, no de diseño: la instancia del cliente tiene
  `configuracion_arca` **vacía**. Aplicar *"emitir reemplaza al alta"* de forma
  literal la dejaría **sin poder facturar**, que es una regresión sobre un
  sistema vivo. El alta manual es el camino de la razón social que todavía no
  cargó su certificado, y desaparece en cuanto lo carga y lo habilita.
  > `habilitado` no es lo mismo que "tiene los archivos": cargar el par y no
  > habilitar es un estado legítimo —el cliente lo subió y todavía no quiere
  > emitir— y ahí sigue registrando.

- Decisión 3 — 🔴 **el pedido de CAE va adentro de la misma transacción que el
  alta.** O el comprobante existe con CAE, o no existe y las órdenes vuelven a
  pendientes. Un comprobante con un número que ARCA no autorizó deja el
  correlativo **tomado de este lado y libre del otro**, y el próximo intento
  choca contra `uq_comprobantes_numeracion` sin que nadie entienda por qué.
  > La garantía es que el `commit` **nunca ocurre**, no el `rollback` explícito:
  > `obtener_sesion` cierra la sesión en su `finally` y SQLAlchemy descarta la
  > transacción abierta. Medido con una mutación — sacar el rollback no cambia
  > el resultado. Se deja igual porque hace explícita la intención.

- Decisión 4 — **el par de certificados se pasa en bytes**, no por ruta. Acá
  vive en la base (ADR-020, decisión 2), así que la API por rutas de
  `arca_wsaa.autenticar()` no servía. LibraCore `v1.49.0` suma
  `autenticar_con_bytes()` y `par_en_disco()`: el par igual tiene que tocar el
  disco —la firma del TRA la hace `openssl` por subproceso, y openssl lee de
  archivos— pero la clave se escribe con **0600** y se borra **siempre**,
  también si el bloque explota. Vive en el motor y no acá para que cada producto
  que guarde credenciales fuera del volumen no improvise su propio temporal.

- Decisión 5 — **del motor se reusa sólo la capa de protocolo**, `arca_wsaa` +
  `arca_wsfe`, como el propio ADR-020 anticipaba. `libracore.arca_facturacion`
  está atado a **su** esquema de `facturas` y `arca_config`.

- Consecuencias: la migración `0010` agrega `cae`, `cae_vencimiento` y
  `cae_solicitado_en`, las tres nullable y sin default. **`cae IS NULL` es el
  estado normal** de los 741 comprobantes que vinieron del legado —de un sistema
  que facturaba por afuera— y de todo lo que se registre a mano: no es una fila
  incompleta. `cae_solicitado_en` es aparte de `fecha` porque un reintento
  después de que ARCA estuvo caído deja las dos separadas.

- Lo que **no** hace: notas de crédito contra ARCA con su comprobante asociado
  (`CbtesAsoc`), reintento del CAE sobre un comprobante ya registrado, y PDF con
  QR de ARCA. Los tres quedan para cuando haya un certificado real cargado — hoy
  la emisión está construida y verificada **contra mocks y homologación**, no
  contra ARCA de verdad.

## ADR-025 — La FCE MiPyME se emite sólo por ARCA, sólo como factura, con lo normalizado de la suite

**Estado:** aceptada (2026-10-02). **Contexto:** Suitrans les factura a empresas grandes y necesita la Factura de
Crédito Electrónica MiPyME. `libracore` v1.119.0 ya resuelve del lado de ARCA los códigos, el vencimiento de pago, el
CBU y la modalidad. El humano pidió no armar pantallas nuevas ni cosas paralelas: lo normalizado primero, y lo extra
como arista.

- Decisión 1 — **sólo las facturas** (`fce_a`, `fce_b`, `fce_c`), no las notas de crédito ni de débito. Este producto
  todavía no emite notas contra ARCA (anular no habla con ARCA, ADR-024), así que una nota de FCE no tendría camino. Se
  agregan junto con las notas comunes, con su comprobante asociado.
- Decisión 2 — **una FCE sin CAE no existe.** No hay camino de «registrar con el número que tengo»: es el documento que
  ARCA registra y que el comprador acepta o rechaza. Sin ARCA habilitado para la razón social, `422`. (Contraste con
  ADR-024, donde el alta manual sigue siendo el camino de la razón social que todavía no tiene ARCA.)
- Decisión 3 — **receptor con CUIT de 11 dígitos**, validado **antes** de ir a ARCA. Medido en homologación: con consumidor final
  contesta `10015`. El mensaje dice que se cargue en la ficha del cliente.
  El CUIT **viaja a ARCA sólo en dígitos**: el motor limpia guiones y espacios y nada más, y uno cargado con puntos
  llegaba como «no es un CUIT». El **vencimiento de pago** tiene que ser **igual o posterior** a la fecha del comprobante
  **y a hoy**: medido en homologación el 2026-10-02, el mismo día se autoriza y uno anterior se rechaza (`10164`); se
  valida en el backend antes de pedir el número.
- Decisión 4 — **el CBU y la modalidad no se piden en la pantalla de facturar**: salen de la configuración de ARCA, que
  ya los acepta (`fce_cbu`, `fce_transmision`). **Se guardan en el comprobante**, no se leen después de la
  configuración, para que diga con qué CBU salió aunque cambie. El **vencimiento de pago** sí es del comprobante: lo
  exige ARCA en toda FCE, aun con concepto «Productos» (`10163`), y la pantalla lo propone a 30 días.
- Decisión 5 — **un `CHECK` en la base**: una FCE sin `fch_vto_pago` no entra. Escrito con `tipo::text` y no con el
  literal del `ENUM`, para no depender de que el valor ya exista en la misma transacción de la migración.
- Decisión 6 — **una FCE emitida no se anula desde acá** (`409`). *(Generalizada a todo comprobante con CAE en el ADR-026.)* `anular` no habla con ARCA (ADR-024): la FCE seguiría
  vigente allá, el comprador podría aceptarla, y las órdenes volverían a pendientes para facturarse de nuevo. Revertirla
  pide una nota de crédito de FCE. 🔸 **El mismo hueco existe para cualquier comprobante con CAE** (A, B y C): no se
  tocó porque cambia el comportamiento de lo ya existente y hoy ninguno tiene CAE en producción; queda para decidir.
- Consecuencias: migración `0012`, que **no baja los valores del `ENUM`** (PostgreSQL no permite sacar un valor); queda
  sin usar y volver a subir es inofensivo. No toca ni una fila. En el formulario, una FCE **reemplaza el campo del
  número por el del vencimiento**: el número lo da ARCA.
- 🔸 **Arista pendiente:** el CBU y la modalidad se cargan por la API. La tarjeta de ARCA del kit (`libra-ui`) no tiene
  esos campos; agregarlos —opcionales, sin pantalla nueva— es trabajo del kit y de todos los productos que lo usan.

## ADR-026 — Un comprobante con CAE no se anula desde acá

**Estado:** aceptada (2026-10-02). **Contexto:** `anular` revierte el comprobante **sólo de este lado**: las órdenes vuelven a
pendientes y la cuenta corriente se revierte, pero no habla con ARCA (ADR-024). Con la emisión por ARCA eso es un hueco: el
comprobante sigue vigente allá —y el cliente lo tiene—, y las mismas órdenes se pueden facturar de nuevo. Lo marcó la revisión de
Codex sobre la FCE; el ADR-025 lo cerró sólo para ese tipo y dejó abierto el caso general. El humano pidió cerrarlo.

- Decisión 1 — **un comprobante con CAE responde `409` a `DELETE /api/comprobantes/{id}`**, sea cual sea su tipo (A, B, C y FCE).
  El mensaje dice que lo tiene ARCA y que hace falta una nota de crédito **emitida por ARCA**; en una FCE agrega que el comprador puede
  aceptarla.
- Decisión 2 — **la pantalla no ofrece el botón** cuando hay CAE: en su lugar dice que lo emitió ARCA (con el CAE) y que no se anula
  desde acá. Un `409` detrás de un diálogo se pierde.
- Decisión 3 — **`cae IS NULL` se anula como siempre.** Es lo registrado a mano y lo migrado del legado (741 comprobantes de
  Suitrans); no cambia nada de lo existente. Y hoy **ningún comprobante de producción tiene CAE**: la guarda se pone **antes** de que
  la emisión por ARCA se use de verdad, que es cuando importa.
- Lo que **no** resuelve: cómo revertir de verdad un comprobante con CAE. Eso es la **nota de crédito contra ARCA** con su comprobante
  asociado (`CbtesAsoc`), que sigue pendiente (ADR-024). Cuando exista, `anular` pasa a emitirla y esta guarda se reemplaza.
  *(Cerrado por el ADR-027: la nota sale de `POST /api/comprobantes/{id}/nota-de-credito`; `DELETE` no la emite, sigue en `409` con el
  mensaje apuntando a la nota.)*
- Consecuencias: ningún cambio de esquema ni de datos. Un comprobante emitido por error contra ARCA de **homologación** no es un caso: el
  ensayo no guarda nada (ADR-024).

## ADR-027 — La nota de crédito es del motor; este producto aporta sus costuras

**Estado:** aceptada (2026-10-04). **Contexto:** un comprobante con CAE no se podía revertir (ADR-026). El humano decidió el 2026-10-04 que
**las notas de crédito salen del motor y son iguales para todos los productos** (ADR-014 de `libracore`, `libracore.notas_de_credito`,
desde `v1.126.0`), y que el arreglo de fondo vive siempre en el motor (`reglas/producto.md` del wiki). Este producto es su primer consumidor.

- Decisión 1 — **no hay lógica de nota en este repo.** Qué nota corresponde (la letra se hereda), las guardas (una factura se acredita una
  sola vez, una nota sin CAE no se duplica, el CUIT del receptor, un solo pedido a la vez), el armado (`CbtesAsoc`, fecha de hoy) y el orden
  *numerar → registrar → pedir CAE* son del motor. Si falta una regla, **se agrega en el motor** y llega por el bump de pin.
- Decisión 2 — **lo propio de acá** (`app/servicios/notas_de_credito.py`): cargar el comprobante y sus notas previas; guardar la nota como una
  fila más de `comprobantes`, **en positivo** y con `comprobante_asociado_id` (migración `0013`, aditiva: no toca ninguna fila); y, en la misma
  transacción, **marcar el original `anulado`, devolver sus órdenes a pendientes y abonar la cuenta corriente** con la fecha de la nota.
- Decisión 3 — **`POST /api/comprobantes/{id}/nota-de-credito` con `{motivo}` y nada más.** Sin importe, fecha ni tipo (`extra="forbid"`): la
  nota es total, de hoy y de la letra del original. El motivo es obligatorio y queda en la nota y en la auditoría. Mismos códigos HTTP que
  el router de facturas del motor (tipo 400; ya acreditada, sin CAE y en curso 409; receptor 422).
- Decisión 4 — **si ARCA rechaza, no queda nada** (ni nota, ni original anulado, ni abono, ni número tomado), y contra homologación se corre
  todo y se revierte (como `facturar`): una nota de prueba no mueve la cuenta del cliente. Antes del `commit` se deja en el log lo que ARCA
  autorizó, para poder reconstruir una nota autorizada cuyo `commit` falló (riesgo R1 del diseño).
- Decisión 5 — **las notas no suman en los totales** (`solo_facturas`): la nota total acredita lo mismo que su factura, que ya queda `anulado`.
  Sumarla haría subir lo facturado. Esto se revisa cuando exista la nota **parcial**.
- Decisión 6 — **una FCE no tiene nota todavía** (`422` con el motivo): medido en homologación, sin que el comprador la rechace ARCA no la deja
  anular (`10154`) y una nota total supera su saldo (`10184`).
- Lo que **no** resuelve: la nota parcial, el tope acumulado, las observaciones de ARCA guardadas y mostradas, y las facturas migradas de
  Suitrans (existen en ARCA y acá no tienen CAE; decisión con el cliente). Diseño: `wiki/analyses/libracargo-nota-de-credito-diseno.md`.
- Consecuencias: **migración `0013` aditiva** (dos columnas `NULL`, un `CHECK` verdadero para todo lo existente, un índice); requiere
  `libracore >= v1.126.0`.

## ADR-028 — La nota de crédito parcial, y la de una FCE

**Estado:** aceptada (2026-10-05). **Contexto:** la nota de ADR-027 era sólo total. El motor suma la nota **parcial** con su tope acumulado
(`libracore` v1.130.0, ADR-018 de allá) y frena la nota total de una FCE antes de ir a ARCA (v1.131.0, libracore#343). El humano decidió el
2026-10-05 que **unas parciales que suman el total liberan las órdenes** y que **la nota de una FCE entra ahora** (sólo parcial).

- Decisión 1 — **`{motivo, importe?}`**: sin `importe` la nota es total (como ADR-027); con él, parcial por ese monto **con IVA**, de hasta dos
  decimales (un booleano no es un importe). El tope (lo ya acreditado más esto no supera el total), la nota total sólo sin notas previas, el
  reparto en neto e IVA con la alícuota del original y **las reglas de la FCE** son del motor; acá no hay guarda propia. Códigos nuevos:
  `IMPORTE` 422 y `SUPERA_SALDO` 409, como el router de facturas del motor. Las notas previas viajan al motor **con su `total`**.
- Decisión 2 — **la fila de la nota lleva los importes que armó el motor** (en una C todo es neto) y `pedir_cae` arma el pedido desde ella: lo
  guardado es lo que se mandó a ARCA. Una nota por el total (con o sin `importe`) copia el original tal cual.
- Decisión 3 — **cerrar lo propio depende del saldo** (`saldo_acreditable` del motor, con la nota ya guardada): toda nota abona su importe en la
  cuenta corriente con su fecha; **si el comprobante quedó acreditado por completo** queda `anulado` y sus órdenes vuelven a pendientes
  (refacturables); con saldo, las órdenes no se tocan (la nota acredita plata, no viajes).
- Decisión 4 — **los totales restan las notas de un original vigente, con la fecha de la nota** (`acreditado_por_notas`), en el gate por razón
  social (**de los dos lados**, así una parcial no aparece como diferencia), en el resumen y en lo facturado por razón social. Una nota cuyo
  original está anulado no resta: el original ya salió de todo el rango (así la nota total sigue sin sumar ni restar, sin distinguirla).
- Decisión 5 — **la nota de una FCE**: tipos `nota_credito_fce_a/b/c` (203, 208 y 213; migración `0014`, que rehace
  `ck_comprobantes_nota_con_asociado` para incluirlos). Sólo por **menos que el saldo** (`10184`); anularla entera exige que el comprador la
  rechace (`10154`), que pasa por el servicio de FCE de ARCA que la familia todavía no integra. La marca `N`, el asociado con su fecha (`10158`)
  y no mandar vencimiento ni CBU los arma el motor.
- Decisión 6 — **el detalle del comprobante** trae `notas`, `acreditado` y `saldo_acreditable` (`null` donde no hay nota posible), y la pantalla
  ofrece «por el total» (sin notas previas y no FCE) o «por un importe» (≤ saldo; < saldo en una FCE), con las notas listadas.
- Lo que **no** resuelve: la FCE completa (aceptación y rechazo del comprador, anulación total, nota de débito FCE): es del motor y se diseña
  aparte. Tampoco guarda ni muestra las observaciones de ARCA.
- Consecuencias: **migración `0014`** (tres valores de `ENUM` y el `CHECK` rehecho; no toca filas); requiere `libracore >= v1.131.0`.

## ADR-029 — Una sola base: el schema de LibraCore vuelve a vivir en la del dominio

**Contexto.** Desde que la configuración de ARCA pasó al motor, LibraCargo llevó el schema de LibraCore en una base aparte (`libracargo_core`). El motivo era que los dos declaran `usuarios` y `auth_log`. La etapa 3 del diseño «LibraCargo sobre el modelo de comprobantes del motor» (wiki del ecosistema) pide lo contrario: que los comprobantes vivan en `facturas` del motor. Con dos bases eso no anda:
- `facturas.usuario_id` es una FK a `usuarios`, y el `usuarios` del core está vacío.
- El comprobante, las órdenes y la cuenta corriente tienen que escribirse en una sola transacción (ADR-024 de este producto, ADR-025 del motor), y entre dos bases no se puede.

El humano eligió la salida A, una sola base, el 2026-10-05.

**Medido** ese día sobre una copia de Suitrans:
- Choque de tablas: sólo `usuarios` y `auth_log`. Las columnas son las mismas y cambian los tipos (`varchar`/`timestamp` contra `text`). Es la misma convivencia que tienen Contalibra, VentaLibra y Restolibra, con una u otra forma.
- El core de Suitrans está vacío salvo las semillas.
- `libracore-migrar` sobre la base del dominio muere con *relation "alembic_version_pkc" already exists*: el renombre viejo de la tabla de versión no renombró su clave.
- Con la clave renombrada, la cadena del motor corre y ninguna tabla del dominio cambia sus filas.

**Decisión.**
- **Revisión `0015`**: renombra la clave a `alembic_version_libracargo_pkc` si hace falta.
- **El alta de un cliente nuevo nace con una base** (`base_core_separada=False`): las dos variables llevan la misma URL.
- **El respaldo declara el core como segunda base sólo si es otra** (`_instancia_a_respaldar`). Con una sola base, el dump de la principal ya lo trae todo.
- **La suite corre con una sola base**: la de producción después de unir. Las tablas de `libraauth` se vacían (`vaciar_auth`) en vez de borrarse, porque las FK del motor las referencian.

**Unir una instancia existente** (dev, demo y Suitrans, cada una con su OK):
1. Desplegar esta versión con las bases todavía separadas. La 0015 corre en la del dominio.
2. Respaldar las dos bases y probar la restauración.
3. Copiar a la base del dominio lo que el core tenga además de las semillas (`arca_config` y `modulos`, si tienen filas).
4. Correr `libracore-migrar upgrade --prefijo libracargo` contra la base del dominio.
5. Cambiar `LIBRACARGO_LIBRACORE_DATABASE_URL` en el compose para que apunte a la base del dominio, y desplegar.
6. Verificar: health, versión del motor en la base del dominio, conteos del dominio idénticos y la configuración de ARCA presente.

La base `libracargo_core` vieja se conserva como respaldo; no se borra sin preguntar.

**Consecuencias.**
- Una instancia unida y una sin unir conviven: el código mira si las URLs coinciden.
- Lo que siga de la etapa 3 (los comprobantes en `facturas`) sólo corre en instancias unidas.


## ADR-030 — El comprobante vive en `facturas` del motor

**Contexto.** El humano pidió que LibraCargo no tenga un modelo de comprobantes separado del de la familia («no quiero que sean modelos separados»). Con la base unida (ADR-029) y el motor preparado (emisor por comprobante, anulación con rastro, registro manual, `conn=` y dinero exacto: ADR-021 a ADR-025 de LibraCore), el comprobante puede pasar a `facturas`. Es la etapa 3b del diseño «LibraCargo sobre el modelo de comprobantes del motor» del wiki del ecosistema.

**Decisión.**
- **El comprobante es una fila de `facturas`, con el mismo id que tenía en `comprobantes`.** Así las FK de `ordenes_carga` y `movimientos_cuenta` no cambian de valor: sólo apuntan a otra tabla (revisión `0016`).
- **Lo propio va en `comprobantes_cargo`**, una fila por comprobante: la razón social y el tercero con sus FK, `anulado`, el origen en el legado, cuándo se pidió el CAE y la FK exacta de la nota a su comprobante.
- **`Comprobante` se mapea sobre la unión de las dos tablas.** Los reportes, el control F5 y las pantallas leen igual que antes.
- **Escribe el motor.** El comprobante lo crea `registrar_comprobante` si se registra a mano, o `create_factura(ambiente=)` si emite por ARCA. El CAE lo guarda `update_factura_cae`. Todo pasa con la conexión de la sesión (`conexion_libracore`), en la misma transacción que las órdenes y la cuenta corriente (ADR-024). La única puerta es `app/servicios/comprobantes.py`.
- 🔑 **`anulado` no es `anulada_en`.** Acá un comprobante también queda anulado cuando sus notas lo acreditan entero (ADR-028). Sale de los totales del producto, pero **sigue en el libro IVA** junto a sus notas. Por eso `anulado` se queda en el producto, y `anular_factura` del motor se llama sólo en la anulación **sin CAE**, que sí lo saca de los libros.
- **El emisor** es la fila de `arca_config` del CUIT de la razón social, o `NULL` (el emisor único) si no tiene.
- **El comprobante de apertura** (ADR-010) no es fiscal y no entra en `facturas`. Pasa a `comprobante_de_apertura`, y sus órdenes a `apertura_id`.
- `comprobantes` queda como `comprobantes_legado`, de sólo lectura, por un ciclo.

**Consecuencias.**
- **Dos razones sociales sin ARCA propio comparten talonario**: las dos son del emisor único y el índice de numeración del motor es por emisor. Antes eran dos talonarios. Con su propio emisor, cada una vuelve a tener el suyo. Suitrans tiene una sola razón social; la demo y dev usan puntos de venta distintos.
- Los CHECK de la tabla vieja que `facturas` no tiene (vencimiento de la FCE, la nota con su asociado, los signos) los dice `crear`.
- Los totales y reportes de este producto ya no cuentan el comprobante de apertura. Sus órdenes tampoco, así que el F5 sigue coincidiendo.
- El libro IVA, los PDF y los listados del motor ven los comprobantes de LibraCargo.

## ADR-031 — La cuenta corriente vive en el libro de terceros del motor

**Contexto.** Con el comprobante ya en `facturas` (ADR-030), lo que quedaba propio era la cuenta corriente: `movimientos_cuenta`, un libro de asientos por (tercero, rol) con clientes, fleteros y proveedores. El humano pidió que no haya modelos separados, y eligió la opción A del diseño `cuenta-corriente-de-terceros-diseno` del wiki: un libro de terceros en el motor, opcional (ADR-026 de LibraCore, `cc_asientos`), al que este producto migra primero.

**Decisión.**
- **Cada asiento es una fila de `cc_asientos`, con el mismo id** (revisión `0017`).
- **Lo propio va en `movimientos_cuenta_cargo`**, una fila por asiento: la orden, el cobro de caja o el gasto que lo originó.
- **`MovimientoCuenta` se mapea sobre la unión de las dos tablas**: los saldos, el extracto, los reportes y el control de F4 leen igual que antes.
- **Escribe el motor** (`libracore.db.libro_de_terceros`), con la conexión de la sesión, en la misma transacción que el documento (ADR-024). La única puerta es `app/servicios/cuentas.py`:
  - `asentar`, para lo que antes era un alta;
  - `corregir`, cuando se edita el documento: el gasto, el cobro o la comisión;
  - `borrar`, cuando el documento editado deja de mover la cuenta;
  - `contraasentar`, disponible para revertir.
- **El rol del motor es texto**, y acá se traduce al enum de siempre.
- **La FK al tercero la pone este producto** sobre `cc_asientos.tercero_id` (`fk_cc_asientos_tercero_libracargo`). El motor no la declara porque el tercero es del producto.
- `movimientos_cuenta` queda como `movimientos_cuenta_legado`, de sólo lectura, por un ciclo.

**Consecuencias.**
- Las reglas de los asientos (una sola columna con importe, sin negativos) las dice el motor antes de escribir, y su base las sostiene.
- El import del legado y su reporte de diferencias escriben y leen `cc_asientos`.
- Pide libracore v1.136.0 o posterior (migración `0019_libro_de_terceros`).

## ADR-032 — Todo comprobante sale de una pre factura; se retira el registro a mano

**Contexto.** En «Facturar pendientes» se elegían el cliente y las órdenes, y aparecían **punto de venta** y **número**, que no tienen que aparecer. Servían para el registro a mano: sin certificado de ARCA en la razón social, `POST /api/comprobantes` guardaba el número que alguien tipeaba, sin CAE. Era el camino de lo que se facturaba en otro sistema, y de la instancia de Suitrans mientras no tiene el certificado de producción. El humano pidió el 2026-10-06 que primero haya **algo que se pueda generar en PDF y mandar al cliente para ver si está de acuerdo**, y que de ahí se pueda **facturar por ARCA** (diseño `libracargo-pre-factura-diseno` del wiki del ecosistema). Y decidió dos cosas: **se saca del todo el registro a mano**, y **la conformidad la marca el operador**.

**Decisión.**
- **La pre factura es la del motor** (ADR-030 de LibraCore): una fila de `comprobantes_pendientes` con número interno `PF-0001`, ciclo (pendiente, enviada, aceptada, facturada, anulada), PDF sin valor fiscal y envío por correo. Acá no hay modelo de pre factura propio.
- **Se arma siempre desde órdenes.** `POST /api/pre-facturas` recibe el cliente, la razón social, el tipo, la fecha (y el vencimiento de pago de la FCE) y las `orden_ids`. **Los ítems y los importes los arma el servidor** con `comprobantes.items_de`, lo mismo que lleva la factura. La alícuota del ítem sale de lo que dicen los importes de la orden (`iva / tarifa`), no de la nominal: cada orden redondea su IVA, y con la nominal el total de la pre factura podía diferir en un centavo del de la factura. Una clase C va sin IVA y con el total de la orden como precio.
- **El router del motor se monta con el gate, el SMTP y el emisor de este producto**, pero sin las cuatro rutas que no sirven: `POST /` y `PUT /{id}` (crean y editan desde ítems tipeados: una pre factura sin órdenes no se podría facturar) y `GET /` y `GET /{id}` (no conocen la razón social ni las órdenes). Las reemplazan las propias, en los mismos caminos. Quedan del motor el PDF, el correo, aceptar y anular. `origen_instancia` va vacío: una instancia es una base.
- **Lo propio vive en dos tablas** (revisión `0019`):
  - `pre_facturas_cargo`, una por pre factura con el mismo id: la **razón social** que facturaría y el tercero. Hacen falta porque la bandeja del motor guarda el cliente como foto con una FK a `clients` (que este producto no usa) y el emisor como el `arca_config` del CUIT, que es `NULL` si la razón social no tiene certificado, y el error de «no tiene certificado» tiene que nombrarla.
  - `pre_factura_ordenes`: **la reserva**. `orden_id` es la clave primaria: una orden está en a lo sumo una pre factura abierta, y lo garantiza la base. La fila existe mientras la pre factura está abierta: anular o facturar la borra. Así una orden que vuelve a pendientes (porque se anuló su comprobante) no queda atada a una pre factura cerrada. Las órdenes de una cerrada se leen de sus ítems.
- **Una orden reservada no se edita ni se anula** (409): la pre factura quedaría diciendo otra cosa. Se libera quitándola de la pre factura o anulándola. Si cambia por debajo (SQL, un import), facturar lo detecta: compara los ítems con los de las órdenes de hoy y rechaza si no coinciden. Lo mismo si cambió la razón social o el CUIT del cliente.
- **`POST /api/pre-facturas/{id}/facturar` es el camino de emisión de siempre**, con los datos de la pre factura: número del WSFE, comprobante del motor, órdenes a facturadas, cuenta corriente y CAE, y `marcar_facturada`, todo en una transacción. Si ARCA rechaza, la pre factura sigue abierta y no queda nada. Sin certificado para la razón social, 409 con su nombre y sin tocar nada. Contra homologación se corre todo y se revierte (200 con el ensayo), y la pre factura sigue abierta. Acepta una `fecha` opcional: a los días de generarla, ARCA puede no aceptar la de la pre factura.
- **Aceptar no es obligatorio para facturar.** La conformidad la marca el operador (botón «Marcar aceptada»), y la pantalla avisa si falta, pero no frena: hay clientes a los que se factura sin mandarles nada.
- **`POST /api/comprobantes` ya no existe** (405). Sin punto de venta ni número en ninguna entrada de la API ni de las pantallas. Lo registrado a mano antes y lo migrado del legado sigue ahí, y **se anula como siempre** (`DELETE /api/comprobantes/{id}`, sin CAE). `servicios.comprobantes.crear` conserva la rama de registro (sin `ambiente`) porque la usan los tests y las migraciones para armar ese dato; ninguna ruta la llama.

**Consecuencias.**
- **Una razón social sin certificado de ARCA no puede facturar**: su pre factura queda lista para cuando lo tenga. Es el caso de Suitrans hoy. Antes registraba a mano.
- **La demo no tiene comprobantes sembrados**: no tiene certificado, y ya no hay cómo registrarlos. `scripts/seed_demo.py` genera tres pre facturas (una aceptada, una pendiente, una anulada).
- Pide libracore v1.140.0 o posterior (migración `0021_pre_factura` del motor, que corre antes que la `0019` de acá).
- Una pre factura anulada conserva su número y no se reabre. No hay anulación de una facturada: se revierte la factura con una nota de crédito.
- Anular y aceptar quedan asentadas en la propia pre factura (`resuelto_por`, `motivo_descarte`, `aceptado_por`); crear, editar y facturar, además, en el log de actividad.


## ADR-033 — La pre liquidación de transportistas: el valor es la comisión y el IVA lo decide la condición del transportista

**Contexto.** El humano pidió el 2026-10-06 un reporte **«Pre liquidación de transportistas»**: con un rango de fechas, los fletes que hizo cada transportista, el valor de cada uno y el IVA sumado. Es el papel que se le manda al fletero antes de que facture. Hay dos decisiones que no son obvias y se toman acá para que no se reabran en cada cambio: **qué es el valor de un flete** y **cuándo se suma IVA**.

**Decisión.**
- **El valor de un flete es la comisión de la orden** (`OrdenCarga.comision`), no la tarifa: es lo que cobra el transportista, y el mismo importe que `ordenes.sincronizar_comision` le asienta en su cuenta corriente. La tarifa es lo que se le cobra al cliente.
- **Qué órdenes entran** (la misma condición con que se le asienta el flete): con **fletero**, con **comisión mayor que cero**, **no anuladas**, y con la **fecha de la orden** en el rango, extremos incluidos. Pendientes y facturadas entran las dos: liquidarle al transportista no depende de que al cliente ya se le haya facturado. Una orden **sin fletero no entra**: no hay a quién liquidarle.
- **El IVA lo decide la condición del transportista (`Tercero.condicion_iva`), no la orden.** Sólo quien discrimina IVA en su factura lo suma:

  | Condición | IVA | Por qué |
  |---|---|---|
  | `responsable_inscripto` | `comisión × alícuota de la orden / 100` | factura A: discrimina IVA |
  | `monotributo` | 0 | factura C: no discrimina |
  | `exento` | 0 | exento |
  | `consumidor_final` | 0, **con aviso** | no es una condición de quien presta un servicio: es un dato a corregir en el maestro |
  | `no_categorizado` | 0, **con aviso** | no se sabe; sumar IVA por las dudas le liquidaría de más a quien no lo cobra |

  La alícuota es la de **cada orden** (`OrdenCarga.alicuota_iva`), no una fija: una orden al 10,5 % suma 10,5 %. El IVA se redondea **por flete**, mitad hacia arriba, con la misma fórmula que el IVA de la propia orden (`calcular_importes`): la factura del transportista discrimina flete por flete, y el redondeo sobre el total daría centavos distintos.
- **El criterio es exhaustivo sobre el enum**: un valor nuevo de `CondicionIVA` sin criterio rompe `test_cada_condicion_tiene_su_criterio` en vez de liquidarse en silencio con IVA cero.
- **El reporte es del catálogo** (`pre-liquidacion-transportistas`, `detalle`, rango obligatorio) pero **no cabe en la grilla genérica**: viene en bloques por transportista, con subtotales y total general. Tiene pantalla propia, que se registra antes que `/reportes/:slug`.
- **Se imprime y se baja en PDF.** El PDF lo arma el servidor con las piezas de `libracore.pdf_generator` (la base `_TextoSeguroPDF` y el encabezado de empresa de la pre factura), con los datos de la empresa de la instancia y la leyenda «Pre liquidación — no es un comprobante» arriba y en el pie de cada hoja.

**Consecuencias.**
- Es **de lectura**: no asienta nada, no toca la cuenta corriente ni el libro. Lo que se liquida de verdad sigue siendo lo asentado en la cuenta del fletero.
- Un transportista cargado por la API sin condición queda como `consumidor_final` (el default del alta): sale **sin IVA y con aviso**. Corregirlo en el maestro de terceros es lo que hace que se le sume.
- El motor no tiene una API pública para un informe por bloques: el PDF usa helpers de módulo de `pdf_generator` (prefijo `_`). Si un salto de versión del motor los renombra, `tests/test_pre_liquidacion.py` lo detecta (genera el PDF de verdad). Un generador de «informe por bloques» público en LibraCore sería el arreglo de fondo si otro producto lo necesita.


## ADR-034 — El PDF de los comprobantes: el del motor, con la razón social y el logo de la base

> **Nota (ADR-035).** Se retiró la razón social: el resolvedor devuelve **siempre los datos de la empresa** (nombre,
> CUIT, condición de IVA, domicilio, ingresos brutos, inicio de actividades, teléfono, correo y logo) para todo documento.
> Ya no existe la regla «el domicilio y el logo salen sólo si son de esa razón social», ni la elección de la razón social
> por `pre_facturas_cargo`/`comprobantes_cargo`/`emisor_id`. El resto de esta decisión (un solo resolvedor, qué
> comprobantes se ven, el PDF al emitir y lo que se guarda) sigue igual.

**Contexto.** El humano dijo el 2026-10-06: «los comprobantes, cualquiera sea el tipo, no muestran el logo de Suitrans». Eran dos defectos en uno. **LibraCargo no tenía PDF de factura, de nota de crédito ni de FCE** (sólo el de la pre factura, que armaba su emisor aparte y **sin logo**). Y el motor, hasta libracore v1.140.0, dibujaba todos sus PDF con la configuración global de la instancia: un solo emisor, sin logo en bytes. Libracore v1.141.0 (ADR-031 de allá) lo normaliza para toda la familia: `emisor_del_pdf.emisor_para(documento)` arma el membrete por capas (configuración global, `emisor_id` del comprobante, **el resolvedor que registra el producto**, `empresa=`) y trae `build_comprobantes_pdf_router`.

**Decisión.**
- **Un solo resolvedor, en `app/servicios/emisor_del_pdf.py`**, registrado por `crear_app` (`emisor_del_pdf.registrar_resolvedor`) para **todos** los PDF del proceso: el de la pre factura, el de cada comprobante, el que se guarda al emitir y el que va por correo. `servicios.pre_facturas.emisor_del_pdf` y `routers.pre_facturas._emisor_del_pdf` desaparecen: no quedan dos lugares que decidan quién emite.
- **Qué razón social emite**: la de `pre_facturas_cargo` para una pre factura y la de `comprobantes_cargo` para un comprobante (la fuente exacta: no depende de que el CUIT de la razón social siga siendo el del `arca_config`). Sin fila propia, la razón social cuyo CUIT es el del `emisor_id`; si hay dos con el mismo CUIT no se adivina. `nombre`, `cuit` e `iva_condition` son de la razón social.
- **El domicilio, los ingresos brutos, el inicio de actividades, el teléfono, el correo y el logo** salen de `configuracion_empresa`, **sólo si son de esa razón social** (mismo CUIT, o la empresa no cargó CUIT): el domicilio o el logo de otra razón social en el membrete es peor que no tenerlos. El logo viaja como `logo_bytes`, desde la base (el disco del contenedor se pierde en cada despliegue). El inicio de actividades se normaliza a ISO, que es lo que lee el motor: en «Datos de la empresa» es texto libre, y `31/01/2020` salía como `20-/1-31/0`.
- **El router del motor, montado en `/api/comprobantes`** (`app/routers/comprobantes_pdf.py`): `GET /{id}/pdf` y `POST /{id}/enviar-email`, con `require_staff` y el SMTP de la instancia (el mismo callable que la pre factura). No choca con nada: `comprobantes.router` no tiene `/{id}/pdf` ni `/{id}/enviar-email`.
- **Qué comprobantes se ven (`puede_ver`)**: los que tienen fila en `comprobantes_cargo`, **con CAE** y que **no son de homologación**; el resto es un 404 igual al de un id inexistente.
  - **Sin CAE no hay PDF** (lo registrado a mano y lo migrado del legado): ARCA no los conoce, y un papel con el formato de una factura, sin CAE ni QR, se podría mandar a un cliente como si lo fuera. La pantalla tampoco ofrece los botones. Se anulan como siempre.
  - **De homologación no se imprime**: por el camino normal no queda ninguno (el ensayo se revierte entero, ADR-032), pero un dato cargado por fuera traería un CAE que no vale.
- **El PDF se genera y se guarda al emitir** (`servicios.comprobantes.guardar_pdf`: `generate_pdf_factura` y `facturas.pdf_path`), para la factura (`POST /api/pre-facturas/{id}/facturar`) y para la nota de crédito (`POST /api/comprobantes/{id}/nota-de-credito`). **Va DESPUÉS del `commit` y un fallo no deshace nada**: cuando corre, ARCA ya autorizó y la transacción ya guardó el comprobante; revertirlo por un PDF dejaría a ARCA con una factura que acá no existe. Es el criterio del motor, que genera el PDF recién después de guardar el CAE. Si el PDF falla, se loguea, `pdf_path` queda vacío y el router lo arma al vuelo la primera vez que se pide (y **no** lo guarda: lo dice el motor).
- **El PDF guardado es lo que salió**: con el emisor y el logo de ese momento. Si después cambia el logo o el domicilio de la empresa, los ya emitidos no se reescriben; sí los nuevos. Un PDF que ya no está en disco se arma de nuevo con el emisor de hoy.
- **La pantalla** (Comprobantes, el detalle): «Ver PDF», «Descargar PDF» y «Enviar por correo» (con el correo del cliente prellenado) sólo con CAE, y un enlace «PDF» en cada nota de crédito de la lista.

**Consecuencias.**
- Pide libracore **v1.141.0** o posterior. Sin migración.
- **Los PDF van a `DATA_DIR/facturas_pdf`** (`/app/data`, el volumen de la instancia). No entran en el backup de la instancia (que lleva las dos bases y los certificados): si se pierden se regeneran, pero con el emisor de hoy y no con el de la emisión. Si hace falta conservar el original, hay que sumar esa carpeta al respaldo.
- **Los comprobantes ya emitidos no tienen `pdf_path`**: se arman al pedirlos, con el membrete de hoy (razón social, domicilio y logo cargados ahora). Es lo esperable para lo anterior a este cambio.
- Una instancia con `ENV=development` imprime `[DEV - SIMULADO]` junto al CAE (lo hace el motor): en las instancias desplegadas `ENV` no está definida (sólo `ENTORNO`).
- Una sola configuración de empresa por instancia: con dos razones sociales sólo la que tiene el CUIT de la empresa (o la empresa sin CUIT cargado) lleva logo y domicilio. Para que cada una tenga el suyo hay que modelar el membrete por razón social, y no es el pedido de hoy.

## ADR-035 — Un solo emisor: «Datos de la empresa»; se retira la razón social

**Contexto.** El CUIT del emisor estaba en **tres lugares** que había que mantener iguales a mano: `configuracion_empresa` («Datos de la empresa»: razón social, CUIT, condición de IVA como texto libre, domicilio y logo), `razones_sociales` (nombre, CUIT, condición de IVA, punto de venta; es lo que llevaban la orden, la pre factura, el comprobante y la emisión) y `arca_config` del motor (CUIT, punto de venta, certificado, clave y ambiente). **Las razones sociales existían porque el legado facturaba con dos nombres** (`1 = Suitrans`, `2 = otro nombre` en un `<select>` de HTML, ADR-013), y el producto las heredó como un maestro. Ya se había decidido que Suitrans factura con una sola. En producción hay una sola razón social, con el CUIT **vacío**: por eso el PDF salía sin logo (ADR-034 comparaba el CUIT de la empresa con el de la razón social) y no habría podido emitir por ARCA. **El resto de la familia ya tiene un solo emisor por instancia** (la empresa más su `arca_config`): LibraCargo era la excepción. El humano lo decidió el 2026-10-07: «sacar esa sección y dejar sólo lo que es empresa; que sólo pueda facturar con el CUIT que está en empresa».

**Decisión.**
- **«Datos de la empresa» es la única fuente del emisor**: razón social, CUIT, condición de IVA, domicilio, ingresos brutos, inicio de actividades, teléfono, correo y logo. Toda factura, nota de crédito, pre factura y PDF sale con esos datos (`app/servicios/emisor_del_pdf.py` se reduce a «los datos de la empresa para todo documento»; sigue registrado en el motor).
- **La condición de IVA de la empresa es la enumeración del tercero** (`condicion_iva`), no texto libre: de ella depende qué clase de comprobante se puede emitir (A/B o C). La API la valida (`""` es «sin cargar»; cualquier otro valor fuera del enum es 422) y la pantalla la elige de la lista.
- **`arca_config` es sólo lo técnico**: certificado, clave, **punto de venta** y ambiente. **Se emite por ARCA sólo si hay una configuración con el par completo y su CUIT (en dígitos) es el de la empresa** (`emision_arca.problema_de_emision`). Si no, 409 con el motivo y qué hacer: la empresa sin CUIT («cargá el CUIT en Configuración → Datos de la empresa»), ARCA sin configurar, el CUIT de ARCA distinto del de la empresa (dice los dos), o el par incompleto. La pre factura queda abierta, lista para facturar cuando se resuelva.
  - 🔑 **El CUIT de la configuración de ARCA es el que FACTURA** (el de la empresa), **aunque el certificado esté a nombre de otra persona que la representa** (delegación: en Suitrans el certificado puede ser de una persona física). El motor lo usa como `Cuit` del `Auth` de WSFE. **No se compara nunca contra el sujeto del `.crt`**: sólo contra el CUIT de la empresa.
- **Se retiran la pantalla y la API de «Razones sociales»** (`/api/razones-sociales`), el modelo `RazonSocial` y el selector en Órdenes, Facturar pendientes, pre facturas, Comprobantes y Reportes, y el reporte «Facturado por razón social». **`razon_social_id` se quita** de `ordenes_carga`, `pre_facturas_cargo`, `comprobantes_cargo` y `comprobante_de_apertura`. `comprobantes_cargo` se queda: es la marca «este comprobante es de LibraCargo» que lee `puede_ver`, con el tercero, el anulado y el origen del legado.
- **El gate de totales** (`GET /api/comprobantes/totales`) deja de abrirse por razón social: devuelve **un** total, contado por los dos lados (comprobantes y órdenes), con `coinciden`.
- **Migración `0020`**: antes de borrar, copia a la empresa lo que sólo estaba en la razón social —si la empresa no tiene CUIT o condición de IVA y hay una razón social **única** (la única que hay, o la única con CUIT), se copian; sin razón social (texto), el nombre; sin fila, la crea con el nombre— y **nunca pisa** lo que la empresa ya tenía. Pasa el texto de la condición de IVA a la enumeración (`Responsable Inscripto`, `IVA Responsable Inscripto`, `RI`, `Monotributo`/`Monotributista`, `Exento`, `Consumidor Final`; lo que no se reconoce queda en `NULL`, que no se adivina). Después quita las columnas, sus índices y claves, y la tabla. El tipo `condicion_iva` se queda: lo usa `terceros`. El `downgrade` recrea la estructura con **una** razón social hecha de la empresa y las columnas nulas permitidas apuntando a ella.

**Consecuencias.**
- **Suitrans** (una razón social con el CUIT vacío; la empresa con `30-70933285-2`): tras la migración la empresa conserva su CUIT y recibe la condición `responsable_inscripto` si no tenía. Para emitir hace falta que el `arca_config` lleve ese mismo CUIT.
- **Los comprobantes ya emitidos quedan como están**: su PDF sale con los datos de la empresa de hoy (ADR-034: lo ya guardado en disco no se reescribe).
- **Sólo hay un emisor por instancia.** Si algún día hay que facturar con dos CUIT, es una instancia por CUIT —como en el resto de la familia— y no una tabla de razones sociales.
- El filtro y la columna «Razón social» de los listados y de «Listado de comprobantes» se quitaron; los asientos viejos del log de actividad sobre `razones-sociales` dejan de ser clickeables.
- No hay hoy ninguna regla que limite la clase de comprobante (A/B/C) según la condición de IVA del emisor: el operador elige el tipo. Lo que cambia es que la condición ya no puede ser un texto cualquiera y que sale de un solo lugar.
- La migración del legado (`migracion/transformar.py`) ya no crea ni referencia razones sociales: todo lo migrado pertenece a la empresa, que se carga por la pantalla.

## ADR-036 — Cartas de Porte Electrónicas traídas de ARCA por su CTG, con el CUIT representado elegido en cada pedido

**Contexto.** Suitrans es transportista de granos: el titular emite la Carta de Porte Electrónica (CPE) y Suitrans la ve en ARCA. Necesita los datos de cada CPE —kilos de carga y de descarga, chofer, pagador del flete, origen, destino, tarifa, km— sin tipearlos (plan del wiki `libracargo-ctg-carta-de-porte-plan`, fase 3). El protocolo está en el motor desde libracore v1.143.0 (`libracore.arca_wscpe`, ADR-034 del motor) y el certificado `wscpe` se carga en Configuración → ARCA (ADR-032 del motor). El certificado es de **una persona** que representa a la empresa; por quién se consulta va en cada llamada (`cuitRepresentada`) y ARCA sólo acepta los CUIT que delegaron `wscpe` al alias del certificado. Al 2026-10-07 delegó **un titular** (Agropecuaria Pereiro) y **Suitrans S.A. todavía no**. El servicio **no permite listar** las CPE de un transportista: sólo se consulta por CTG.

**Decisión.**
1. **Tabla `cartas_porte`** (migración `0021`): lo que el producto usa, tipado (CTG, número, estado, fechas, CUIT de transportista, pagador, chofer, origen, destino y destinatario, dominios, grano, cosecha, kilos de carga y de descarga, códigos de ARCA de provincia y localidad, planta, km, tarifa), **por quién y en qué ambiente se consultó**, la respuesta entera de ARCA **sin el PDF** (`respuesta_arca`) y `consultada_en`. El PDF va en `cartas_porte_pdf`. `nro_ctg` es único, y también `(tipo_cpe, sucursal, nro_orden)`.
2. **Los CUIT se guardan como vienen, no como FK.** El chofer no tiene CUIT en `choferes` y el pagador puede no estar cargado: el cruce con `terceros` se hace al leer (por dígitos, porque hay CUIT con guiones) y la pantalla muestra el nombre si lo encuentra. Crear o completar maestros desde la CPE queda para otra etapa.
3. **La orden de carga es opcional y va del lado de la CPE** (`orden_carga_id`, `ON DELETE SET NULL`): una CPE puede llegar antes que su orden y una orden de otra carga no tiene CPE. Se vincula al traerla (sólo con un CTG por pedido) o después; actualizarla desde ARCA no la desvincula.
4. **El CUIT representado se elige en cada pedido, sin valor por defecto**, entre los que el ticket de WSAA deja operar (`GET /api/cartas-porte/representados`, que lee las relaciones del ticket). Se guarda con la CPE y «Actualizar» lo reusa.
5. **El ambiente es el del certificado `wscpe` cargado, producción primero.** En homologación no hay CPE reales, pero si sólo hay ese par se consulta ahí (sirve para probar). Cada CPE guarda su ambiente y se actualiza contra ése.
6. **Ingreso por lote**: hasta 50 CTG por pedido, cada uno en su transacción; un CTG que falla (no existe, el CUIT no interviene) se informa y no se lleva a los demás. Un CUIT sin delegación corta el lote entero, porque falla igual para todos.
7. **Refresco a pedido**, de una CPE o de **todas las abiertas** (sin kilos de descarga y en un estado que no es final: `AN`, `RE`, `DE`). No hay refresco automático programado: se agrega cuando haya volumen real.
8. **Rutas `def`**, con ARCA por `asyncio.run` en el hilo del pedido, como la facturación: la firma de WSAA (`openssl`) y la sesión son sincrónicas. Un test lo mide.

**Consecuencias.**
- Para usarlo en una instancia: libracore v1.143.0, migración `0021`, el certificado `wscpe` cargado y **la delegación hecha en ARCA** por cada CUIT por el que se quiera consultar. Sin la de Suitrans S.A., sólo se leen las CPE en las que interviene un titular que delegó.
- No cambia la orden ni la facturación: los kilos de la CPE **no** liquidan todavía (fase 5 del plan) ni la orden tiene etapas (fase 2).
- El grano y las localidades se muestran por su **código de ARCA**; traducirlos (los catálogos de WSCPE) es una mejora aparte.

## ADR-037 — La orden gana etapa operativa, kilos de carga y de descarga, y adjuntos; el chofer, su CUIT

**Contexto.** Fase 2 del plan de CTG y Carta de Porte (wiki `libracargo-ctg-carta-de-porte-plan`). El dueño de Suitrans describió el circuito de un flete: el chofer sale de la lista, se arma la orden, carga, viaja, descarga y manda la foto del ticket, y se cierra el flete con los kilos de descarga. Hoy la orden tiene sólo el **estado de facturación** (`pendiente`, `facturada`, `anulada`), una `cantidad` sin unidad y ningún adjunto, y el chofer no tiene CUIT, que es con lo que viene en la Carta de Porte (`cuitChofer`). En Suitrans hay 4.337 órdenes: 4.112 facturadas y 226 pendientes, 225 de ellas con más de 60 días. Decisiones del humano del 2026-10-07: la etapa **va aparte** del estado de facturación; las órdenes existentes quedan **cerradas**; y por ahora la etapa **sólo informa**.

**Decisión.**
1. **`ordenes_carga.etapa`** (`etapa_orden`): `asignada`, `cargada`, `en_viaje`, `descargada`, `cerrada`. **No reemplaza al estado**: facturación, pre facturas, reportes y cuenta corriente siguen leyendo `estado`. «Liquidada» **no es una etapa guardada**: la pantalla la muestra cuando el estado es `facturada`. Una orden nueva nace `asignada`; la migración `0022` dejó **todas las existentes en `cerrada`** (son viajes hechos).
2. **Sólo informa.** Se cambia con `PUT /api/ordenes/{id}/etapa`, a cualquier etapa (para adelante o para atrás), **también con la orden facturada**, porque es operativa y no toca el comprobante; una anulada no se mueve. El `PUT` de la orden también la acepta, pero ese sigue cerrado para facturadas. Facturar no exige ninguna etapa: las reglas se agregan cuando el cliente las confirme.
3. **Kilos de carga y de descarga en la orden**: bruto, tara y neto, enteros y opcionales. Si vienen bruto y tara, **el neto lo pone el servidor**: un neto distinto es 422, igual que una tara mayor que el bruto. El neto solo, sin bruto ni tara, se acepta, porque a veces es lo único que dice el ticket. `cantidad` no se toca. **Los kilos todavía no liquidan nada**: eso es la fase 5, con la decisión de facturación aparte.
4. **`choferes.cuit`**: once dígitos, validado con el verificador del motor (`libracore.arca_wsfe.cuit_con_verificador_valido`). Se acepta con guiones y se guarda sin ellos, para cruzarlo con la CPE.
5. **Adjuntos de la orden** (`ordenes_adjuntos`): **en la base**, como el certificado de ARCA y el PDF de la CPE, para que entren en el respaldo sin un paso aparte. Tope de 10 MB. **El tipo sale del contenido** (la firma de JPG, PNG, WEBP, HEIC o PDF) y no del `Content-Type` del navegador; la descarga va con ese tipo y `nosniff`. Se adjunta también a una orden facturada, porque el ticket suele llegar después; no a una anulada. Alta y baja quedan en la auditoría.

**Consecuencias.**
- Migración `0022` sobre una tabla con filas: agrega la columna con default `cerrada` y después lo cambia a `asignada`. Hay un test que siembra antes de subir.
- **Considerado y descartado por ahora: un módulo de adjuntos en el motor.** MedLibra y LibraDesk ya tienen los suyos (en disco, cada uno a su manera) y ninguno los comparte. Si un segundo producto necesita adjuntos genéricos, este se muda a `libracore` (`reglas/producto.md`: «el arreglo de fondo vive en el motor») en vez de copiarse.
- Pendientes: que la Carta de Porte vinculada complete los kilos de descarga de la orden, la cola de choferes (fase 6) y las reglas por etapa que confirme el cliente.

## ADR-038 — El tarifario de referencia en el sistema; la orden lleva km y tarifa por tonelada, que varía por viaje

**Contexto.** Suitrans cotiza el flete con la **tarifa de referencia de cereales y oleaginosas** que publica el sector: una tarifa en pesos **por tonelada** para **cada kilómetro**, más un valor de estadía. La vigente es la del 10 de abril de 2026, con 9.636,69 $/t de 1 a 10 km, 23.205,57 a 80 km y 108.021,12 a 1.000 km. Viene en un PDF con la tipografía codificada: los dígitos son otros glifos y se decodifican con una sustitución simple. Audios del dueño (2026-10-07): «en 100 km una tarifa, en 101 otra… siempre se ponen los kilómetros y la tarifa, y la tarifa es **por tonelada descargada**». En la CPE de Pereiro, 80 km a 19.724,73 $/t es **exactamente el 85 %** de la referencia. El humano (2026-10-08): el porcentaje **varía por viaje**, no es fijo por cliente; y el tarifario se hace **antes** de terminar la emisión de cartas de porte, para que la emisión ya traiga km y tarifa.

**Decisión.**
1. **`tarifarios` + `tarifas_referencia`** (migración `0023`): una edición por **vigencia** (única), con su nombre y el valor de estadía, y una fila por km. Las ediciones viejas se quedan. **La referencia de una orden es la del tarifario que regía en su fecha**: la vigencia más reciente que no sea posterior. Un km que no está en la tabla **no se extrapola**: se informa que falta.
2. **Carga por CSV** `km;tarifa`, que admite `9.636,69`, con o sin encabezado y con `;` o `,`. Sólo un administrador. La misma vigencia se **reemplaza entera** y queda en la auditoría con las filas y el rango de km. El PDF no se lee en el sistema: su tipografía codificada puede cambiar en cada edición, así que se convierte a CSV fuera.
3. **La orden gana `km` y `tarifa_tonelada`**, opcionales. La pantalla propone la tarifa como referencia × porcentaje, y **el porcentaje que sugiere es el del último viaje de ese cliente** (`GET /api/tarifario/sugerencia`). No se guarda un porcentaje por cliente, porque varía por viaje.
4. **No liquida todavía**: `tarifa`, el importe, sigue siendo lo que se factura. Liquidar «toneladas descargadas × tarifa por tonelada + IVA» es la fase 5, con su decisión de facturación aparte.

**Consecuencias.**
- La emisión de la Carta de Porte (fase 4) toma `km` y `tarifa_tonelada` de la orden. El esquema de ARCA admite hasta 99.999,99 $/t; una referencia de más de 1.000 km lo supera, y ahí la emisión avisa.
- Del PDF de abril salen completos los km de 1 a 1.000. Más allá, sólo filas sueltas: lo que no está se informa como faltante.

## ADR-039 — El tarifario se carga desde el PDF que publica el sector; los dígitos codificados se deducen y se verifican

**Contexto.** ADR-038 cargaba el tarifario desde un CSV y dejaba el PDF afuera, porque sus números vienen con una tipografía sin tabla de caracteres. El humano corrigió (2026-10-08): «el transportista carga el PDF que descarga de la página, porque no está en CSV; el sistema lo convierte». Medido con `pdfplumber` sobre la edición del 10 de abril de 2026: los números salen como `(cid:N)`, con 488-497 para 0-9, 558 para el punto de miles y 559 para la coma. El título, la fecha («10 ABRIL 2026») y el «Valor de estadía: $214.146,67» salen como texto común. La tabla trae completos los km 1 a 1.000; más allá, el PDF publica sólo algunas filas.

**Decisión.**
1. **`POST /api/tarifario` acepta el PDF**, reconocido por `%PDF`, además del CSV. Del PDF salen las filas, la **vigencia** (día, mes en letras y año), el **valor de estadía** y el nombre. Lo que venga en el formulario manda sobre lo leído. Un CSV sin vigencia la pide.
2. **La codificación no se deja fija**, porque otra edición puede numerar los glifos distinto. Se deduce de la forma de las tarifas (`d.ddd,dd`): la **coma** es el símbolo que va 3 lugares antes del final de cada tarifa, el **punto de miles** el que va 7, y los **diez restantes, en orden**, son 0-9.
3. **Se verifica antes de cargar:** al menos 100 filas, los km arrancan en 1 y son consecutivos en un tramo de al menos 100, y las tarifas no bajan al subir los km. Si algo no cierra, **no se carga nada** y el error lo dice: un tarifario mal leído es peor que ninguno.
4. **`POST /api/tarifario/previsualizar`** lee y muestra, **sin guardar**: vigencia, estadía, filas, rango de km, una muestra de km para comparar a ojo y si reemplaza una edición. La pantalla confirma después.
5. Dependencia nueva: `pdfplumber`.

**Consecuencias.**
- La pantalla pide el PDF; el CSV queda como alternativa.
- El PDF real de abril es fixture de los tests (es público). Un test con otra numeración comprueba que la deducción no depende de la de abril.
- Si una edición futura cambia la **forma** de la tabla (otras columnas, otro formato de número), la verificación la rechaza y se carga por CSV hasta ajustar la lectura.
- Va junto con `cartas_porte.fecha_inicio_estado` (migración `0024`): el humano vio una CPE «Anulada» cuyo PDF decía otra cosa. El PDF es del día de la emisión y la anulación fue después; la pantalla ahora dice «desde cuándo».

## ADR-040 — «Entidades» en el menú principal: una persona o empresa es una sola, con roles; fletero y chofer, separados

**Contexto.** El humano (2026-10-08): «de Configuración sacamos Terceros y Choferes y ponemos un ítem en el menú principal que diga Entidades, y dentro Clientes, Fleteros, Choferes y Proveedores». También pidió, a nivel de datos, un modelo común de personas y empresas con roles, para que una misma entidad pueda ser fletero y proveedor sin duplicar datos, y fletero (transportista, propietario o contratado) y chofer (quien conduce) separados. **El modelo ya era así**: `terceros` tiene una fila por entidad, con `es_cliente`, `es_fletero` y `es_proveedor` (al menos uno, ADR anteriores), y `choferes` es aparte, con `fletero_id` y su CUIT (ADR-037). Lo que faltaba era la pantalla y una regla. Medido en Suitrans:
- 276 terceros, **ninguno con más de un rol**;
- **un CUIT cargado dos veces**, una como cliente y otra como fletero;
- **68 con un CUIT de relleno** («1») que vino del legado.

**Decisión.**
1. **Un CUIT, una entidad.** Al dar de alta o editar, un CUIT de 11 dígitos que ya tiene **otra** entidad da **409**, con la entidad existente y sus roles (`detail.existente`). Así la pantalla ofrece **sumarle el rol** en lugar de duplicarla. Los CUIT que no tienen 11 dígitos, como el relleno del legado, no se comparan. Es una regla de la API y no una restricción de la base, porque el duplicado que ya existe la violaría.
2. **`POST /api/terceros/{id}/roles/{rol}`** le suma un rol a una entidad y la reactiva si estaba de baja, con auditoría.
3. **`?fletero_id=`** en `/api/choferes` y `/api/vehiculos`, para la ficha del fletero. El constructor de maestros gana dos costuras, `filtros` y `validar`, y los demás maestros no cambian. La búsqueda de choferes incluye el CUIT.
4. **Pantalla «Entidades»** en el menú principal, con pestañas Clientes, Fleteros, Choferes y Proveedores. Terceros y Choferes salen de Configuración, y los enlaces viejos redirigen.

**Consecuencias.**
- **El duplicado que ya existe no se une solo**: los dos registros tienen órdenes y cuenta corriente de cada lado. Unificar entidades es una operación aparte, con su propio diseño.
- Una fixture de los tests usaba el mismo CUIT para dos fleteros distintos; ahora tiene uno propio.
- Vehículos queda en Configuración y se ve desde la ficha del fletero.

## ADR-041 — Las localidades se traen del catálogo de Argentina; los parajes son la excepción cargada a mano

**Contexto.** El humano (2026-10-08): «en Configuración tenemos Localidades, un listado que se fue cargando con los lugares donde se hicieron fletes. ¿Se puede traer una base con todas las localidades de Argentina y del Mercosur? Y que también se pueda poner a mano un paraje que no esté como localidad, como excepción, porque cargar las localidades es medio de gusto». LibraCore ya tiene el catálogo oficial de Argentina: 24 provincias y 4.027 localidades censales del INDEC, empaquetado y de sólo lectura (`libracore.geografia`). Y ya decía que el maestro editable tiene que seguir siendo del producto, porque hay lugares reales que no figuran en ningún recurso oficial. Medido en Suitrans: 120 localidades.
- **92 coinciden** con una sola localidad del catálogo.
- **28 no**:
  - partidos, como Exaltación de la Cruz o General Rodríguez;
  - abreviaturas duplicadas: «Pto. San Martín» y «Pto San Martín»;
  - parajes y puntos: Tomás Jofré, Ortiz Basualdo, Puerto Robles;
  - basura del legado: «Campo», «Shap», «(sin nombre)».

**Decisión.**
1. **El maestro sigue siendo el de las órdenes** (FK de origen y destino), y suma **`catalogo_id`** (código censal, único) y **`es_paraje`**. La unicidad pasa de `nombre` a **`(nombre, provincia)`** con `NULLS NOT DISTINCT`: entran «San Pedro» de Buenos Aires y de Jujuy, y dos «Suipacha» sin provincia siguen chocando.
2. **Una localidad se trae del catálogo** (`POST /api/localidades/desde-catalogo`): si ya está vinculada se devuelve; si hay una del mismo nombre y provincia se vincula; si no, se crea. El selector de origen y destino busca en las dos fuentes (`GET /api/localidades/buscar/combinado`).
3. **Un paraje se carga a mano, con provincia obligatoria** (`es_paraje`).
4. **Vincular** una existente al catálogo y **unificar** dos que son el mismo lugar. Unificar mueve el origen y el destino de las órdenes y da de baja la que sobra; lo hace sólo un administrador y queda en la auditoría con las órdenes movidas.
5. **La migración `0025` vincula sola** lo que coincide una sola vez y completa la provincia faltante. **No renombra ni borra**: lo demás queda «sin vincular» para revisar en la pantalla.
6. La búsqueda por código censal es del motor (`geografia.localidad(id)`, libracore v1.145.0).

**Consecuencias.**
- **Mercosur, todavía no:** el catálogo es sólo de Argentina. Brasil, Uruguay, Paraguay, Bolivia y Chile necesitan una fuente externa (GeoNames) y un formato distinto; se suma al motor si el humano lo confirma. Mientras tanto, un lugar del exterior se carga como paraje.
- El código de localidad **de ARCA** (para la Carta de Porte) es otro catálogo. Se mapea en la fase 4b, por nombre y provincia.

## ADR-042 — Las localidades del resto del Mercosur, del mismo catálogo; el tarifario en la semilla de la demo

**Contexto.** El humano (2026-10-08) confirmó sumar el Mercosur al catálogo de localidades (ADR-041 lo había dejado pendiente). LibraCore v1.146.0 agrega Brasil, Chile, Paraguay, Bolivia y Uruguay: 6.621 lugares de GeoNames (`cities1000`, CC-BY 4.0), con ids `{PAÍS}-{geonameid}` y el país en cada fila. Por omisión sigue siendo sólo Argentina. Aparte, el tarifario de referencia cargado a mano en la demo **desapareció con el reinicio nocturno** (05:00, `reset_libracargo.sh`), y la sección «Flete» de la demo quedó sin referencia.

**Decisión.**
1. **`localidades.pais`** (ISO de dos letras, `AR` para lo existente). `catalogo_id` pasa a 20 caracteres y la unicidad pasa a `(nombre, provincia, pais)` (migración `0026`).
2. El **buscador combinado** trae todo el Mercosur, Argentina primero; traer o vincular desde el catálogo copia el país. Un **paraje** puede ser de afuera, con su país y su división.
3. **La semilla de la demo carga el tarifario** de abril de 2026, que es público y del sector, desde un CSV junto al script. Lo hace por la API, como el resto de la semilla. El test de la semilla lo cubre; para eso, su adaptador ahora respeta el `Content-Type` del pedido.

**Consecuencias.**
- Un lugar de afuera que no esté entre los más de 1.000 habitantes de GeoNames (un puerto chico, una planta) se carga como paraje, igual que en Argentina.
- El mapeo al código de localidad **de ARCA** para la Carta de Porte es sólo para Argentina: un destino de afuera no lleva CPE de granos nacional.

## ADR-043 — Emitir la Carta de Porte desde la orden, con traba en producción, plantilla por titular y enlace para el chofer

**Contexto.** Fase 4 del plan de CTG y Carta de Porte. Suitrans emite cartas de porte **a nombre de un titular que le delegó** (Agropecuaria Pereiro) con un software de terceros, y quiere hacerlo desde el sistema. El protocolo está en libracore v1.144.0 (`arca_wscpe.emitir_cpe`, ADR-035 del motor): cerrojo por sucursal, guarda de timeout y el representado igual al solicitante. Una CPE real de Pereiro emitida con ese software (CTG 10135025133) mostró lo que se usa siempre: origen en campo, maíz, cosecha 2526, destino y destinatario en una planta, transportista = el fletero, pagador del flete = Pereiro, km y tarifa por tonelada. En homologación, una emisión exitosa necesita un certificado del titular; ya está pedido.

**Decisión.**
1. **Traba en producción** (`configuracion_empresa.cpe_emision_habilitada`, **apagada**): no se emite nada real hasta que un administrador la prende, y queda en la auditoría. Además, **cada** emisión real exige `confirmo: true`. En homologación no hace falta ninguna de las dos, porque no tiene efecto fiscal.
2. **La propuesta sale de la orden** (`GET /api/cartas-porte/emision/propuesta`):
   - del viaje: chofer (su CUIT), dominios (el vehículo), transportista (el fletero, o la empresa si no hay), pagador del flete (el cliente), kilos de carga, km y tarifa por tonelada (ADR-038);
   - de **la plantilla del titular** (`plantillas_cpe`, lo último usado con ese titular): origen, grano, cosecha, destino, planta, destinatario, intervinientes y fumigada;
   - lo que no se pudo completar va en `faltantes`.
3. **Los códigos de ARCA** de provincia y localidad son otro catálogo que el censal: se buscan por nombre en los catálogos de WSCPE, que se cachean 12 horas por ambiente. CABA y Tierra del Fuego tienen sinónimo, y una coincidencia que no es única no se adivina. Sólo Argentina.
4. **El titular tiene que estar entre las relaciones del ticket**; si no, 409 antes de llamar.
5. **Lo emitido se guarda** como una CPE más (`emitida = true`), vinculada a la orden y con su PDF. 🔴 **Si ARCA la autoriza y falla guardarla**, el error dice que se emitió, con el CTG, para traerla con «Traer de ARCA», y **no se vuelve a emitir**. Una emisión incierta (sin respuesta de ARCA) se informa con su sucursal y número.
6. **Anular** sólo las emitidas desde acá, y sólo un administrador.
7. **Enlace para el chofer**, que no tiene usuario: `GET /{id}/enlace` da una ruta **firmada con HMAC** (`SECRET_KEY`) que vence a los 7 días, y `/api/publico/cpe/{id}/{vence}/{firma}.pdf` sirve el PDF sin sesión. La pantalla lo comparte por WhatsApp con un enlace `wa.me`, sin la API de Meta (opción A del plan).

**Consecuencias.**
- Migración `0027`: `cartas_porte.emitida`, la traba y `plantillas_cpe`, todo vacío o apagado.
- Desvío, contingencia y confirmación de arribo siguen pendientes, en el motor primero.
- Antes de la primera emisión real: el certificado de homologación de Pereiro para una prueba completa, y prender la traba a propósito.
