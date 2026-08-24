# Changelog — LibraCargo

Cambios funcionales y releases. Las tareas internas van en `TASKS.md`.

## [Unreleased]

### Agregado

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
