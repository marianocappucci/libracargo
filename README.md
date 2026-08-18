# LibraCargo

Vertical de **agencia de cargas** de la familia Libra.

Una agencia de cargas no transporta: **intermedia**. Toma una orden de un
cliente, se la asigna a un fletero con su chofer y su equipo, le cobra al
cliente, le paga al fletero y vive de la comisión. De ahí las **tres cuentas
corrientes** que se mueven en direcciones opuestas sobre la misma operación, y
las **razones sociales propias** con las que se factura la misma actividad.

Nace del relevamiento de **Suitrans**, un sistema PHP de 2021 en producción que
resuelve este dominio. Ese sistema **no se toca**: LibraCargo se construye en
paralelo y la migración de datos es una copia de lectura.

## Estado

Fase **F1** — esqueleto. Modelo de datos completo, migración inicial y suite
contra PostgreSQL real; sin API de negocio ni frontend todavía.

- Entorno dev: `dev.libracargo.com.ar`
- Demo: `demo.libracargo.com.ar`
- Cliente Suitrans: `suitrans.libracargo.com.ar`
- Rama de desarrollo: `develop` · Rama de producción: `main`

## Correr local

```bash
cp .env.example .env          # completar POSTGRES_PASSWORD
docker compose up --build
curl http://localhost:8000/salud
```

Tests (exigen PostgreSQL real, no corren sobre SQLite):

```bash
export DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/libracargo_test
alembic upgrade head
pytest -q
```

## Documentación relacionada

- [ROADMAP.md](ROADMAP.md) · [TASKS.md](TASKS.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
- [CONVENTIONS.md](CONVENTIONS.md) · [DECISIONS.md](DECISIONS.md) · [CHANGELOG.md](CHANGELOG.md)

El contexto transversal —relevamiento del sistema legado, auditoría de
seguridad y plan de migración— vive en el wiki del ecosistema, no acá.
