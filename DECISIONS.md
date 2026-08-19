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
