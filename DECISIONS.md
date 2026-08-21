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
