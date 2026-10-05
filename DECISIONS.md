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

- Estado: aceptada
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

- Estado: aceptada
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

