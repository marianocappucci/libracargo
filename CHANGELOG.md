# Changelog — LibraCargo

Cambios funcionales y releases. Las tareas internas van en `TASKS.md`.

## [Unreleased]

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

### Agregado

- **Provincias y localidades se eligen de un catálogo** (24 y 4.027, de
  LibraCore) en el maestro de localidades y en la dirección de clientes,
  fleteros y proveedores. El campo sigue aceptando texto para lo que no está en
  el catálogo, y una localidad vieja que no matchea **abre en modo texto con su
  valor** en vez de aparecer vacía. Ver ADR-019.
  - La migración `0005` completa la provincia de **63 de las 121** localidades
    existentes: sólo donde el nombre no es ambiguo.

### Corregido

- 🔴 **El alta de una orden ahora asienta la comisión en la cuenta corriente del
  fletero.** No lo hacía: `comision` se leía sólo para los reportes, y la cuenta
  de un fletero sólo se movía cuando se le pagaba. Editar la orden corrige el
  asiento y anularla lo revierte con un contraasiento. Ver ADR-018.
- 🔴 **Pagarle a un fletero o a un proveedor bajaba mal el saldo**: el asiento de
  caja elegía la columna mirando sólo el tipo de movimiento, así que un egreso
  **aumentaba** lo que se le debía. Ahora la columna depende del rol de la cuenta,
  como en el sistema anterior y como los 22.645 movimientos migrados.

### Agregado

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
