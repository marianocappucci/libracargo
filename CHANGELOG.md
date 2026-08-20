# Changelog — LibraCargo

Cambios funcionales y releases. Las tareas internas van en `TASKS.md`.

## [Unreleased]

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
