# Changelog — LibraCargo

Cambios funcionales y releases. Las tareas internas van en `TASKS.md`.

## [Unreleased]

### Agregado

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
