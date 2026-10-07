# Changelog — LibraCargo

Cambios funcionales y releases. Las tareas internas van en `TASKS.md`.


## [Unreleased] — Configuración → ARCA muestra el CTG y la Carta de Porte

- La pantalla de ARCA tiene un bloque por servicio: **Facturación** y **CTG y Carta de Porte** (`wscpe`). Cada uno con su certificado y clave por ambiente, a nombre de qué CUIT está el certificado, cuándo vence y «Probar» contra ARCA para ese servicio (libracore v1.142.0, ADR-032; libra-ui v0.120.0, ADR-030).
- Pines: libracore v1.142.0 (migración 0022 del motor: tabla nueva), libra-ui v0.120.0.

## [Unreleased]

### Cambiado

- **Un solo emisor: «Datos de la empresa»; se retiran las razones sociales** (ADR-035). El CUIT del emisor estaba en tres lugares (la empresa, las razones sociales y la configuración de ARCA) que había que mantener iguales a mano; en Suitrans la razón social tenía el CUIT vacío y por eso el PDF salía sin logo. Ahora **«Datos de la empresa» es el único emisor** de toda factura, nota de crédito, pre factura y PDF, y **sólo se emite por ARCA con el CUIT de la empresa**.
  - **La condición de IVA de la empresa se elige de la lista del tercero** (responsable inscripto, monotributo, exento, consumidor final, no categorizado) en vez de escribirse a mano.
  - **ARCA sólo emite si el CUIT de su configuración es el de la empresa.** Si no, dice por qué (409) y la pre factura queda lista para cuando se resuelva: la empresa sin CUIT («cargá el CUIT en Configuración → Datos de la empresa»), ARCA sin configurar, los dos CUIT distintos (los nombra) o el certificado o la clave sin cargar. El CUIT de la configuración de ARCA es **el que factura**, aunque el certificado esté a nombre de otra persona que representa a la empresa. El punto de venta es el de la configuración de ARCA.
  - **Se quitan** la pantalla «Razones sociales» (Configuración), el selector de razón social en Órdenes, Facturar pendientes, pre facturas, Comprobantes y Reportes, la columna «Razón social» de los listados y el reporte «Facturado por razón social». El resumen de lo facturado sigue en «Resumen del período».
  - **El panel «Total facturado» de Comprobantes** muestra un solo total (comprobantes contra órdenes), ya no uno por razón social. API: `GET /api/comprobantes/totales` devuelve un objeto y no una lista.
  - **API**: se quitan `/api/razones-sociales`, `/api/reportes/por-razon-social`, `razon_social_id` de órdenes, pre facturas y comprobantes (y los filtros del mismo nombre), y de `GET /api/comprobantes/fce/corresponde`. `PUT /api/configuracion` valida `condicion_iva` contra el enum (422 si no lo es; `""` es «sin cargar»).
  - **Migración `0020`** (con `downgrade`): copia a la empresa el CUIT, la condición de IVA y el nombre de la razón social **sólo si a la empresa le faltan y la razón social es única** (la única que hay, o la única con CUIT); pasa el texto de la condición a la enumeración (lo que no se reconoce queda vacío, para elegirlo en la pantalla); quita `razon_social_id` de las cuatro tablas y borra `razones_sociales`. **Antes de desplegar en una instancia: respaldar, y revisar que «Datos de la empresa» tenga el CUIT y la condición de IVA correctos, y que el CUIT de Configuración → ARCA sea el mismo.**
  - La **demo** se siembra con una empresa ficticia.

### Agregado

- **PDF de los comprobantes, con el logo y la razón social** (ADR-034). Antes los comprobantes no tenían PDF y el de la pre factura salía sin logo. Ahora la factura, la FCE y la nota de crédito emitidas por ARCA tienen su PDF (el mismo generador que usa toda la familia), y **todos los PDF** —también el de la pre factura— llevan el **logo cargado en «Datos de la empresa»** y los datos de **la razón social que emitió** (nombre, CUIT y condición de IVA; el domicilio, los ingresos brutos y el inicio de actividades de la empresa si son de esa razón social).
  - **En la pantalla** (detalle de un comprobante): «Ver PDF», «Descargar PDF» y «Enviar por correo» (con el correo del cliente prellenado), y un enlace «PDF» en cada nota de crédito. Sólo para lo que tiene **CAE**: lo registrado a mano y lo migrado del legado no tienen PDF, porque ARCA no los conoce.
  - **API**: `GET /api/comprobantes/{id}/pdf` y `POST /api/comprobantes/{id}/enviar-email` (`{"email": ...}`); 404 para un comprobante sin CAE, de homologación o que no es de LibraCargo.
  - **Al emitir** (factura y nota de crédito) el PDF se genera y se guarda **después** de guardar el comprobante: si el PDF falla, el comprobante queda emitido igual y el PDF se arma al pedirlo. Lo guardado es lo que salió: cambiar el logo después no reescribe los ya emitidos.
  - **Los comprobantes anteriores** se arman al pedirlos, con el membrete de hoy.
  - El inicio de actividades se imprime bien aunque se haya cargado como `31/01/2020` (antes salía `20-/1-31/0` en el PDF).
  - Sin migración. Pide libracore **v1.141.0** o posterior.

- **Reporte «Pre liquidación de transportistas»** (ADR-033). Con un rango de fechas obligatorio (por la fecha de la orden, extremos incluidos) y un transportista opcional, arma **un bloque por transportista** con sus fletes —fecha, orden, remito, cliente, origen → destino, cantidad, comisión, IVA y total—, el subtotal de cada uno y el total general. Se abre desde «Reportes» y se **imprime o se baja en PDF** (con el encabezado de la empresa y la leyenda «Pre liquidación — no es un comprobante»), para mandárselo al transportista antes de que facture.
  - **El valor de cada flete es la comisión de la orden** (lo que cobra el transportista y lo que se le asienta en su cuenta), no la tarifa. Entran las órdenes con fletero y comisión mayor que cero, pendientes o facturadas; **no entran** las anuladas ni las sin fletero.
  - **IVA según el transportista**: al **responsable inscripto** se le suma `comisión × alícuota de la orden`, redondeado a centavos por flete; al **monotributista y al exento**, nada. Un transportista **sin categorizar** o cargado como consumidor final va sin IVA y con un aviso para corregirlo en el maestro de terceros.
  - **API**: `GET /api/reportes/pre-liquidacion-transportistas?desde&hasta[&fletero_id]` (422 sin rango o con el rango al revés) y `GET /api/reportes/pre-liquidacion-transportistas/pdf` con los mismos parámetros. Mismo permiso que los otros reportes (cualquier usuario con sesión). Sin migración.

- **Pre factura** (ADR-032). Antes de facturar se genera una pre factura: un documento **sin valor fiscal** que se manda al cliente (PDF por correo desde la app, o se descarga) para que confirme los datos, y desde la que se **factura por ARCA**.
  - **«Facturar pendientes» ahora genera la pre factura.** Se elige cliente, razón social, tipo, fecha y órdenes (y el vencimiento de pago si es FCE). **Ya no pide punto de venta ni número.** Las órdenes quedan reservadas: no entran en otra pre factura.
  - **Pantalla nueva «Pre facturas»** (se llega desde Comprobantes > Clientes; no tiene entrada de menú): lista con estado y filtros, y el detalle con el PDF, **Enviar por correo** (con el email del cliente prellenado), **Editar** (órdenes, razón social, tipo y fecha), **Marcar aceptada**, **Anular** (con motivo) y **Facturar por ARCA** (confirma, y muestra la factura o el error). Estados: Pendiente, Enviada, Aceptada, Facturada, Anulada.
  - **API**: `POST /api/pre-facturas`, `PUT /api/pre-facturas/{id}`, `POST /api/pre-facturas/{id}/facturar`, y las del motor (`GET`, `/pdf`, `/enviar-email`, `/aceptar`, `/anular`). Las órdenes tienen los filtros `reservada` y `pre_factura_id`.
  - **Migración `0019`** (aditiva: `pre_facturas_cargo` y `pre_factura_ordenes`, vacías). Pide libracore **v1.140.0** o posterior, y que `libracore-migrar` corra antes.

- **La cuenta corriente vive en el libro de terceros del motor** (ADR-031). Cada asiento es una fila de `cc_asientos` de LibraCore, y lo propio (orden, cobro, gasto) va en `movimientos_cuenta_cargo`. Asienta, corrige y borra el motor, en la misma transacción que el documento.
  - **Revisión `0017`**: copia `movimientos_cuenta` a `cc_asientos` con el mismo id, pone la FK del tercero y deja la tabla vieja como `movimientos_cuenta_legado`. Pide libracore v1.136.0 o posterior.
  - La API, las pantallas y los saldos no cambian.

- **Aviso de FCE en «Facturar pendientes».** Antes de emitir, la pantalla pregunta si a ese comprobante le corresponde ser una factura de crédito electrónica (`GET /api/comprobantes/fce/corresponde`). Consulta el registro de FCE de ARCA con la regla del motor (`arca_wsfecred.corresponde_fce`, ADR-019 de LibraCore) y la configuración de la razón social elegida. Si corresponde, avisa y ofrece pasar a FCE, o dice qué cargar si la razón social todavía no puede emitirla. Es un aviso: nunca frena ni falla por ARCA.

- **El comprobante vive en `facturas` del motor** (ADR-030). Deja de haber un modelo de comprobantes propio: cada comprobante es una fila de `facturas`, con lo propio del producto en `comprobantes_cargo`. Lo crea y le guarda el CAE el motor, dentro de la misma transacción que las órdenes y la cuenta corriente.
  - **Revisión `0016`**: copia los comprobantes a `facturas` con el mismo id, pasa el de apertura a `comprobante_de_apertura` y reapunta las FK. La tabla vieja queda como `comprobantes_legado`. Pide la base unida (`0015`) y que `libracore-migrar` corra antes.
  - **Cambio de comportamiento**: dos razones sociales sin ARCA propio comparten talonario (mismo tipo, punto de venta y número chocan).
  - La API y las pantallas no cambian.

- **Una sola base** (ADR-029). El schema de LibraCore vuelve a vivir en la base del dominio. Es la salida A de la etapa 3 del diseño «LibraCargo sobre el modelo de comprobantes del motor».
  - **Revisión `0015`**: renombra la clave de `alembic_version_libracargo` para que la cadena del motor pueda migrar en la misma base.
  - **Alta y respaldo**: un cliente nuevo nace con una sola base, y el respaldo lleva el core como segunda base sólo si todavía es otra.
  - **Instancias existentes**: no se unen con este deploy; se unen con el procedimiento del ADR, cada una con su OK.
  - **Suite**: corre con una sola base.

- **Nota de crédito parcial, y la de una FCE** (ADR-028). `POST /api/comprobantes/{id}/nota-de-credito` acepta `importe` (con IVA): la nota
  acredita ese monto sin tocar las órdenes, con el tope acumulado del motor; cuando las notas suman el comprobante entero, el original queda
  anulado y sus órdenes vuelven a pendientes. Una **FCE** admite notas parciales por menos que su saldo (tipos 203, 208 y 213). Los totales,
  el resumen y lo facturado por razón social **restan** las notas con la fecha de la nota. El detalle trae las notas, lo acreditado y el saldo,
  y la pantalla ofrece «por el total» o «por un importe». **Migración `0014`** (valores de `ENUM` y el `CHECK` de las notas; no toca filas).
  Requiere **libracore `v1.131.0`**.
- **Nota de crédito contra ARCA** (`POST /api/comprobantes/{id}/nota-de-credito`, ADR-027). Un comprobante emitido por ARCA se revierte con una nota
  de crédito **total**, autorizada por ARCA y asociada a su factura; el original queda anulado, sus órdenes vuelven a pendientes y la cuenta del
  cliente recibe el abono. La lógica es la del motor (`libracore.notas_de_credito`): este producto sólo guarda la nota y cierra lo suyo. La
  pantalla de comprobantes ofrece «Emitir nota de crédito» (pide el motivo). **Migración `0013`, aditiva** (`comprobante_asociado_id`, `motivo`).
  Las notas no suman en los totales ni en los reportes. Una FCE todavía no tiene nota.

### Quitado

- **`postgres-init/10-bases-extra.sql`**, que creaba la base `libracargo_core` al inicializar el volumen de dev, y su montaje en `docker-compose.yml`. Desde la base unida (ADR-029) el core vive en la del dominio, y las `libracargo_core` de dev, demo y Suitrans se borraron el 2026-10-06.
- **El registro de comprobantes a mano** (ADR-032): punto de venta y número tipeados, sin ARCA. `POST /api/comprobantes` ya no existe, y las pantallas no los piden. **Una razón social sin certificado de ARCA no puede facturar**: su pre factura queda lista para cuando lo tenga (hoy, Suitrans). Lo registrado a mano y lo migrado del legado sigue ahí y se anula como siempre.
- **Una orden reservada en una pre factura no se edita ni se anula** hasta que se la quita de ahí o se anula la pre factura.
- **La demo no trae comprobantes sembrados** (no tiene certificado de ARCA): el seed deja tres pre facturas de ejemplo.

### Cambiado

- **«Comprobantes» es una sola entrada del menú, con dos pestañas: «Clientes» y «Proveedores».** Antes eran tres entradas sueltas («Comprobantes», «Pre facturas» y «Comprobantes de proveedores»). Sólo frontend: la API y los reportes no cambian.
  - **Clientes** es la pantalla de siempre (facturas y notas emitidas), con arriba los botones **Facturar pendientes** y **Pre facturas**. **Proveedores** es la de comprobantes de proveedores, sin cambios de comportamiento.
  - **La pestaña va en la URL**: `/comprobantes` es Clientes y `/comprobantes?seccion=proveedores` es Proveedores (el mismo `?seccion=` de la Configuración). Elegir una pestaña la escribe en el historial, así que atrás y adelante vuelven a la anterior; un enlace guardado cae en la pestaña correcta. Al cambiar de pestaña se descarta el `?ver=` de la otra.
  - **Los enlaces de antes siguen andando**: `/gastos` y `/gastos?ver=5` redirigen a `/comprobantes?seccion=proveedores` (con su `ver`); `/comprobantes?ver=`, `/comprobantes/facturar`, `/pre-facturas`, `/pre-facturas/:id` y `/pre-facturas/:id/editar` no cambian. Los enlaces que arma la app hacia un comprobante de proveedor (cuenta corriente, caja, log de actividad) van directo a la pestaña.
  - **«Comprobantes» queda marcada en el menú** en todas esas pantallas (facturar pendientes, pre facturas y su detalle y edición). Las pantallas de pre facturas pasan a llevar el icono de Comprobantes y una flecha de vuelta a Clientes.
  - Las dos pestañas las ven los mismos roles que antes (todos los de personal): no hay nada que ocultar por rol.

- **libracore `v1.139.0`** (2026-10-06; antes `v1.138.0`). La cuenta corriente de clientes se lee **sólo** del libro (ADR-029 del motor): se retiran el saldo calculado y el interruptor `LIBRACORE_CC_DESDE_EL_LIBRO`. Sin migración. Lo cargado por fuera de los escritores del motor se ve después de `libro_de_clientes.reconstruir()`.
- **libracore `v1.138.0`** (2026-10-06; antes `v1.137.1`). Las lecturas de la cuenta corriente de clientes pueden salir del libro (ADR-028 del motor), detrás del interruptor por instancia `LIBRACORE_CC_DESDE_EL_LIBRO`, **apagado por defecto**: sin encenderlo no cambia nada. Sin migración.
- **libracore `v1.137.1`** (2026-10-06; antes `v1.136.1`). La cuenta corriente de clientes también como libro, **en sombra** (`libracore.db.libro_de_clientes`, ADR-027 del motor): los escritores del motor asientan cada pago, débito, cobro a cuenta y venta fiada en `cc_asientos`, y el saldo se sigue leyendo calculado. **Con migración del motor**: `0020_origen_del_asiento`, que agrega una columna vacía. La `v1.137.1` no rompe una base sin `cc_asientos`.
- **libracore `v1.136.1`** (2026-10-06; antes `v1.135.0`). Suma el libro de cuenta corriente de terceros, opcional (`cc_asientos` y `libracore.db.libro_de_terceros`, ADR-026 del motor). **Con migración del motor**: `0019_libro_de_terceros`, que crea una tabla vacía y deja `cc_asientos.created_at` y `cierres_diarios.created_at` en hora de Argentina. Este producto no lo usa: su comportamiento no cambia.

- **libracore `v1.135.0`** (2026-10-05; antes `v1.134.0`). Las funciones del comprobante aceptan `conn=` para emitir dentro de la transacción del producto (ADR-025 del motor; sin `conn`, nada cambia) y el dinero del motor se guarda exacto en PostgreSQL (ADR-024): **migración `0018` del motor**, que pasa 33 columnas de dinero de `DOUBLE PRECISION` a `NUMERIC` sin redondear. La lectura sigue siendo `float`: el comportamiento de este producto no cambia.

- **libracore `v1.134.0`** (2026-10-05; antes `v1.132.0`). Trae el emisor opcional de cada comprobante (`facturas.emisor_id`, ADR-021 del motor), la anulación con rastro de un comprobante sin CAE (`POST /api/facturas/{id}/anular`, ADR-022) y el registro con número tipeado (ADR-023); incluye v1.133.0 (`libracore.spa`, la SPA del motor, que este producto no adopta todavía). **Con migración del motor**: `0016` y `0017` (columnas nuevas en `facturas` y el índice de numeración por emisor y ambiente); las aplica el arranque (`init_core_schema`) y `alembic upgrade head`. Para este producto no cambia el comportamiento: no pasa emisor.

- **libracore `v1.132.0`** (2026-10-05; antes `v1.131.0`). Suma `libracore.arca_wsfecred` (consultas al registro de FCE de ARCA) y `GET /api/facturas/fce/corresponde` (¿a esta factura le corresponde ser FCE?, para avisar antes de emitir; ADR-019 del motor). Nada cambia en la emisión. Sin migración.

- **libracore `v1.126.0`** (2026-10-04; antes `v1.124.0`). Suma el nucleo `libracore.notas_de_credito` (este producto todavia no lo usa); la guarda del CUIT del receptor deja de bloquear las notas (ARCA autoriza la nota de credito a un CUIT que no cierra, igual que la factura), e incluye v1.125.0 (los routers de libracore rechazan booleanos en los campos numericos). Sin migración.

- **libracore `v1.124.0` y la guarda del CUIT pasa al motor** (2026-10-04; antes `v1.123.0`). Un CUIT que no sirve
  se dice antes de ir a ARCA, y **esa lógica ya no vive en este repo** (regla del 2026-10-03: el arreglo de fondo
  vive siempre en el motor): `facturar` llama a `arca_wsfe.problema_del_receptor` de `libracore`, y `solicitar_cae`
  corre la misma guarda antes de cualquier llamada de red. Se borraron de acá el validador del dígito verificador, la
  lista de tipos que exigen CUIT y la reducción del CUIT a dígitos (el motor lo normaliza, también con puntos).
  Los clientes migrados de Suitrans traen un `1` de relleno como CUIT (12 de 75) y dos con el verificador mal.
  **Medido contra ARCA de homologación (2026-10-03):** una Factura A con CUIT `1` vuelve `[10013]` y `[10015]` (un 502
  que no explica nada); con el verificador mal, una **B** se rechaza (`10015`) y una **A ARCA la autoriza con CAE** y
  sólo avisa (`10238`: «la CUIT receptora no existe»). Por eso se exige CUIT de 11 dígitos en la clase A y en toda
  FCE, y un verificador válido en cualquier clase si tiene 11 dígitos. **No cambia** la ficha del cliente (acepta
  cualquier CUIT), ni registrar a mano, ni una B o una C a un consumidor final sin CUIT. El salto de pin no trae
  migración; trae además la nota de crédito repetida con 409, que este producto no usa.
- **libracore `v1.121.0`** (2026-10-02; antes `v1.119.0`). Dos cosas que llegan a este producto:
  la **clave privada de ARCA se guarda con permisos `0600`** (con el motor anterior quedaba en
  `644`, legible dentro del contenedor, y las instancias vivas la tienen así: se cierran solas
  la primera vez que se emite, porque toda emisión pasa por `paths_en_disco`), y la migración
  `0015` del motor (`facturas.cae_error`, aditiva: la tabla de facturas del motor, que este
  producto no usa). El `v1.120.0` es el que trae el motivo del rechazo de ARCA en las facturas
  del motor, que tampoco usa. Dos tests nuevos prueban lo primero **dentro de LibraCargo**:
  fallan con `v1.119.0` y pasan con este pin.
- **Un comprobante con CAE ya no se anula desde acá** (`409`, y la pantalla no ofrece el
  botón: dice que lo emitió ARCA y que hace falta una nota de crédito). Anular no llega a
  ARCA: el comprobante seguía vigente allá mientras sus órdenes volvían a pendientes y se
  podían facturar de nuevo, y la cuenta corriente quedaba revertida contra algo que ARCA y el
  cliente siguen teniendo. Lo registrado a mano y lo migrado del legado (`cae IS NULL`) se
  sigue anulando como siempre; hoy ningún comprobante de producción tiene CAE, así que **no
  cambia nada de lo existente**. Generaliza lo que el ADR-025 había cerrado sólo para la
  FCE. Ver ADR-026.
- **libracore `v1.109.0` y libra-ui `v0.73.2`** (2026-09-17). La copia externa
  del backup sale cifrada con `rclone crypt`, o no sale —eso corre en el host y
  ya está desplegado ahí—. Lo que llega con este pin: la pantalla *Datos /
  Backup* nombra la **clave privada de ARCA** y dice que la copia externa va
  cifrada; el estado deja de dar "al día" una copia que subió sin cifrar; y el
  botón de backup arma el mismo ZIP que el cron (todas las carpetas de `data/`,
  `arca_certs/` incluida). Como el pin de `libra-ui` venía de `v0.72.1`, trae
  además lo de `0.73.0` y `0.73.1`: el aviso en un modal cuando el ticket no se
  puede imprimir, y las fechas `dd-mm-aaaa` en los listados de comercio.

### Agregado

- **Factura de Crédito Electrónica MiPyME (FCE).** Tres tipos nuevos de comprobante
  —`fce_a`, `fce_b` y `fce_c`, los códigos 201, 206 y 211 de ARCA— que se emiten
  desde *Facturar pendientes* con lo normalizado de la suite: el CBU del emisor y
  la modalidad (`SCA` o `ADC`) salen de la configuración de ARCA que ya existe
  (`fce_cbu` y `fce_transmision` de `PUT /api/arca`), y el vencimiento de pago se
  elige en la pantalla (a 30 días por defecto). Una FCE se emite **sólo por ARCA**
  y **a un receptor con CUIT**; sin eso se dice qué cargar antes de ir a ARCA. La
  migración `0012` suma los tres valores al `ENUM` y las columnas `fch_vto_pago`,
  `fce_cbu` y `fce_transmision` (nullable: no toca ni una fila). Probada contra
  ARCA de homologación (CAE para una FCE A). **Falta** cargar el CBU y la
  modalidad **desde la pantalla de ARCA**: hoy se hace por la API, y el kit
  compartido todavía no tiene esos campos. Ver ADR-025.
- **Emitir por ARCA y traer el CAE.** La razón social que tiene ARCA habilitado
  ya no registra el comprobante con un número tipeado a mano: el número lo pide
  ARCA (`FECompUltimoAutorizado + 1`), el punto de venta sale de la razón social
  y el comprobante nace con su CAE y su vencimiento. Ver ADR-024.
  - ⚠️ **La razón social que todavía no cargó su certificado sigue igual que
    antes**, con el número a mano. No hay que hacer nada para que siga
    andando — y en cuanto se carga el par y se habilita, esa razón social pasa a
    emitir.
  - 🔴 **Si ARCA rechaza, no queda comprobante**: las órdenes vuelven a
    pendientes y no se toma el número. Un comprobante con un número que ARCA no
    autorizó dejaría el correlativo tomado de este lado y libre del otro.
  - La migración `0010` agrega tres columnas nullable y **no toca ninguna
    fila**: los comprobantes que vinieron del legado no tienen CAE y nunca lo
    van a tener.

### Cambiado

- **Los listados se imprimen desde Reportes, y ahí hay que elegir fechas.** Se
  fue el botón **Imprimir** de arriba a la derecha de Órdenes, Comprobantes,
  Comprobantes de proveedores, Caja y el Log de actividad: apretarlo con la
  pantalla recién abierta mandaba al papel la tabla entera —las 4.337 órdenes
  son unas noventa hojas, y el log de Suitrans arranca con 15.884 registros—.
  - Reportes tiene ahora una sección **Listados para imprimir** con los cinco.
    Cada uno pide **desde** y **hasta**: sin las dos fechas no corre, y no hay
    botón que apretar. Ver ADR-023.
  - Traen los mismos filtros, las mismas columnas y los mismos totales que
    imprimía cada pantalla; el de caja además se puede acotar por medio de pago.
  - **El log sigue siendo sólo para administradores**: cambió de lugar, no de
    permiso.
  - Lo que **no** se movió: imprimir **una** orden —el ícono de la fila y el
    botón del detalle— y **una** cuenta corriente. Son una hoja, no un listado.
  - El Log de actividad, de paso, se queda sólo con su título: la línea que
    explicaba los registros migrados se sacó de la pantalla.

### Arreglado

- **La hoja del log imprimía 500 registros y decía que estaba completa.** El
  endpoint devuelve como mucho 500 por pedido y la impresión comparaba contra
  1.000, así que la primera tanda parecía la última y el aviso de "corta en el
  tope" nunca salía.
- **La hoja de caja pedía una sola tanda** y lo que no entraba se perdía sin
  avisar. `GET /api/caja` era el único listado sin paginación; ahora la tiene.

### Agregado

- **Editar y anular movimientos de caja**, lo último que faltaba del bloque
  NOVEDAD del sistema viejo. Editar corrige el movimiento **y su contrapartida**
  en la cuenta corriente, en el lugar; anular **no borra**: el movimiento queda
  marcado, su asiento se revierte y el número de recibo no deja un hueco sin
  explicación.
  - 🔴 **Un movimiento anulado sigue en el listado pero deja de sumar en los
    totales** — el resumen del período y el reporte de caja lo excluyen. Ver
    ADR-022.

- **Gastos de proveedor**, el último bloque del sistema viejo que no tenía
  equivalente. Lo que el proveedor entrega y **se le descuenta al fletero**: un
  gasto mueve dos cuentas —proveedor al debe, fletero al haber— en una sola
  transacción, y la pantalla lo dice antes de guardar.
  - Se puede editar —corrige los dos asientos, sin duplicarlos— y anular, que
    **no borra**: deja las dos líneas y agrega sus contrapartidas.
  - Desde la cuenta corriente, cada línea que salió de un gasto **lleva al
    gasto**.
  - No es una factura de compra, y no por simplificar: de los 3.347 registros
    del legado, **2.799 son gastos, los 2.799 están imputados a un fletero y
    ninguno tiene número de comprobante**. Ver ADR-021.

- **Configuración de ARCA**, en Configuración → Facturación (ARCA): se cargan el
  certificado y la clave privada de cada razón social, se elige el ambiente
  —homologación por omisión— y se habilita la facturación electrónica.
  - **Verifica los archivos al subirlos**, que es lo que evita descubrir el
    problema recién al emitir: rechaza el `.csr` en lugar del `.crt`, la clave
    con passphrase y el archivo cambiado de campo; avisa **cuándo vence** el
    certificado; y 🔑 avisa cuando **el certificado y la clave no son pareja**,
    que son dos archivos válidos que juntos no autentican.
  - No se puede habilitar sin las dos mitades, y cambiar una **apaga** la
    habilitación.
  - **Todavía no emite**: los comprobantes se siguen registrando con el número
    que se tipea. Ver ADR-020.

- **Todo es clickeable.** Había **nueve tablas y ningún `onRowClick`**: para ver
  el detalle de una orden había que encontrar el botón de la columna de
  acciones, y desde un movimiento de cuenta corriente no se llegaba al documento
  que lo explica de ninguna forma.
  - **Cuenta corriente**: cada línea lleva a su comprobante, a su orden o al
    movimiento de caja que la originó. Las del histórico migrado que no tienen
    origen no son clickeables.
  - **Tablero**: las órdenes recientes abren su detalle y los saldos abren la
    cuenta.
  - **Caja** lleva a la cuenta del tercero; **el log de actividad**, a la
    entidad que se tocó; **los reportes por tercero**, a su cuenta corriente; y
    **los maestros**, al formulario de edición.
  - Enlaces profundos: `/ordenes?ver=123`, `/comprobantes?ver=123`,
    `/cuentas?rol=fletero&tercero=5`. Se piden **por id** y no se buscan en la
    grilla, así el enlace funciona aunque los filtros de esa pantalla no
    incluyan la fila.
  - Los reportes que son **agregados puros** —caja por medio de pago, rutas más
    transitadas— no son clickeables a propósito: la fila es una suma, no una
    cosa.


- **Provincias y localidades se eligen de un catálogo** (24 y 4.027, de
  LibraCore) en el maestro de localidades y en la dirección de clientes,
  fleteros y proveedores. El campo sigue aceptando texto para lo que no está en
  el catálogo, y una localidad vieja que no matchea **abre en modo texto con su
  valor** en vez de aparecer vacía. Ver ADR-019.
  - La migración `0005` completa la provincia de **63 de las 121** localidades
    existentes: sólo donde el nombre no es ambiguo.


- **Backoffice**: `admin.libracargo.com.ar`, la misma instancia de
  `libra-backoffice` que administra a los otros seis productos. Da de alta
  clientes, los pausa y reanuda, les hace backup y les administra los usuarios.
  - El producto sólo aporta el envoltorio de configuración —`scripts/`,
    `plans.py`— porque la lógica vive en `libracore.provisioning`.
  - **La sonda de salud también se sirve en `/health`**, además de `/salud`.
    Es la ruta que el alta le estampa al healthcheck de cada instancia nueva y
    la que sirven los otros seis. Son dos rutas sobre el mismo handler: no
    pueden divergir.
  - El router de usuarios acepta **rol admin o token de servicio**. Sin
    `LIBRA_SERVICE_TOKEN` en el entorno se comporta igual que antes.

- **Backup y restauración de los datos**, en Configuración → Datos / Backup.
  El cliente se baja un ZIP con la base entera y puede reponerlo. Es el motor
  de la familia (`libracore.respaldo` + `build_backup_router`) y la pantalla
  compartida de `libra-ui`: acá no se reimplementó nada, sólo se le puso la
  dependencia de rol de este producto.
  - En LibraCargo el ZIP es **exactamente un dump**: hay una sola base y el
    logo del membrete vive adentro de ella, así que no hay archivos en disco
    que se puedan quedar afuera de la copia.
  - Restaurar **siempre hace un backup previo** antes de tocar nada, y valida
    que el archivo sea de este producto: el ZIP de otro sistema de la familia
    se rechaza con un mensaje que nombra las dos bases.
  - La imagen incluye `postgresql-client-16`, clavado en la major del servidor.

- Esqueleto del repositorio según el estándar de producto de la familia Libra.
- Modelo de datos completo del dominio de agencia de cargas: 11 tablas,
  18 claves foráneas, 36 índices y 9 restricciones `CHECK`.
- Migración inicial `0001`, con el ciclo `upgrade → downgrade → upgrade`
  verificado sobre PostgreSQL 16.
- Suite de 17 tests contra PostgreSQL real. Cada test del esquema prueba una
  restricción **rompiéndola**, y referencia el defecto del sistema legado que
  viene a impedir.
- API con sonda de salud que consulta la base: falla cerrado.
- Dockerfile con huso horario de Argentina, usuario sin privilegios y
  healthcheck; `docker-compose.yml` para desarrollo.
- CI con tests sobre `postgres:16` y `develop` en el trigger.

### Corregido

- 🔴 **Los proveedores no aparecían en ningún select del sistema.** La pantalla
  de cuenta corriente ofrecía el rol "Proveedor" y mostraba la lista de
  **clientes**; caja no los incluía, así que no se podía registrarles un pago y
  un movimiento con un proveedor mostraba el **nombre en blanco** en la grilla
  y en la impresión. Los 15 proveedores de la instancia del cliente son
  proveedor-puro: ninguno era alcanzable, y sus 3.347 movimientos migrados no
  tenían forma de abrirse.
- 🔴 **Los selects mostraban sólo los primeros 200 registros.** El listado de la
  API pagina de a 200 por omisión y las opciones se pedían sin `limite`: con
  **276 terceros activos**, 76 no aparecían en ninguna pantalla y nada lo
  delataba. Ahora se pagina hasta agotar, en vez de subir el tope — cualquier
  número elegido a mano se vuelve a cruzar, y la próxima vez tampoco avisaría.
- Un tercero con dos roles aparecía **dos veces** en las listas de caja y en el
  filtro de terceros de los reportes, que concatenaban clientes y fleteros.


- 🔴 **El alta de una orden ahora asienta la comisión en la cuenta corriente del
  fletero.** No lo hacía: `comision` se leía sólo para los reportes, y la cuenta
  de un fletero sólo se movía cuando se le pagaba. Editar la orden corrige el
  asiento y anularla lo revierte con un contraasiento. Ver ADR-018.
- 🔴 **Pagarle a un fletero o a un proveedor bajaba mal el saldo**: el asiento de
  caja elegía la columna mirando sólo el tipo de movimiento, así que un egreso
  **aumentaba** lo que se le debía. Ahora la columna depende del rol de la cuenta,
  como en el sistema anterior y como los 22.645 movimientos migrados.
