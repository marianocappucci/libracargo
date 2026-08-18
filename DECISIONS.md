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
