# LibraCargo

Vertical de **agencia de cargas** de la familia Libra.

Una agencia de cargas no transporta: **intermedia**. Toma una orden de un
cliente, se la asigna a un fletero con su chofer y su equipo, le cobra al
cliente, le paga al fletero y vive de la comisión. De ahí las **tres cuentas
corrientes** que se mueven en direcciones opuestas sobre la misma operación. Se
factura con un **único emisor**: los «Datos de la empresa» (ADR-035).

Nace del relevamiento de **Suitrans**, un sistema PHP de 2021 en producción que
resuelve este dominio. Ese sistema **no se toca**: LibraCargo se construye en
paralelo y la migración de datos es una copia de lectura.

## Estado

Fase **F1** — esqueleto. Modelo de datos completo, migración inicial y suite
contra PostgreSQL real; sin API de negocio ni frontend todavía.

- Entorno dev: `dev.libracargo.com.ar`
- Demo: `demo.libracargo.com.ar` — **el nombre resuelve pero la instancia no
  existe** (verificado el 2026-08-20): sin contenedor ni proxy host, contesta
  el sitio por defecto de NPM.
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

LibraCargo corre con **una sola base** (ADR-029): el schema de LibraCore vive en la del dominio y alcanza con
`DATABASE_URL`. `LIBRACARGO_LIBRACORE_DATABASE_URL` ya no hace falta (ADR-054); si está, tiene que apuntar a la
misma base, o la app no arranca.

## Tareas programadas

Una, y **no corre sola**: vive en el cron del host de la instancia, y sin su línea el producto no falla, simplemente
deja de hacer esa parte del trabajo (ADR-051).

| Script | Cada | Qué pasa si no está |
|---|---|---|
| `scripts/refrescar_cartas_porte.py` | 30 min | Las cartas de porte abiertas sólo se actualizan con el botón «Actualizar abiertas» |

```bash
*/30 * * * * docker exec libracargo-<instancia> python /app/scripts/refrescar_cartas_porte.py >> /var/log/libracargo_cpe_refresco.log 2>&1
```

- **Sólo consulta a ARCA** (no emite ni anula) y está **apagado de fábrica**: además de la línea del cron, un administrador
  prende «Refrescar solas las cartas de porte abiertas» en Configuración / ARCA. La pantalla muestra cuándo corrió por
  última vez. En una demo, sin certificado de «CTG y Carta de Porte» o con otra corrida en curso, termina sin hacer nada y
  lo dice en una línea.
- Un cron nuevo lleva su log a `/etc/logrotate.d/libra-crons` (lista explícita, no un glob), y se verifica en las tres
  capas del README de LibraClub: a mano, con el `env -i` del cron, y viéndolo disparar solo.

## Versión de escritorio (nodo de LibraEdge)

La oficina puede correr un **nodo**: la misma app en su PC, que sigue operando sin internet y sincroniza con el central
(ADR-056). **Con un nodo vinculado la oficina opera y la web consulta**: órdenes, caja, asientos, facturas y CPE se escriben
sólo en el nodo y, en el central, esas escrituras contestan 409 `solo_en_el_nodo`. Sin nodo vinculado nada cambia.

```bash
# En el central, una vez (publica la referencia que el nodo va a espejar) y por cada nodo:
LIBRAEDGE_APROVISIONAMIENTO=app.offline:aprovisionamiento libraedge-central nodo publicar
# El alta del nodo y su código de vinculación salen de la pantalla «Sucursal sin internet» (sólo administradores).
# Lo que el central rechaza de un nodo queda en revisión manual:
LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador libraedge-central revision listar
```

- **Sin internet** el nodo consulta todo, carga órdenes y opera la caja y las cuentas; **las facturas y las CPE quedan en
  cola y se emiten solas al volver** (`GET /api/nodo/cola`). Mientras una CPE esté en cola no hay CPE válida para viajar.
- El nodo instalado necesita `LIBRAEDGE_CARGA_INICIAL=app.servicios.carga_inicial:aplicar_carga_inicial` (lo declara el
  instalador de libraedge): al vincular baja lo que el central ya tenía.
- **Vincular el nodo de un cliente real es una decisión aparte**, con su respaldo y su restauración de prueba.

## Documentación relacionada

- [ROADMAP.md](ROADMAP.md) · [TASKS.md](TASKS.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
- [CONVENTIONS.md](CONVENTIONS.md) · [DECISIONS.md](DECISIONS.md) · [CHANGELOG.md](CHANGELOG.md)

El contexto transversal —relevamiento del sistema legado, auditoría de
seguridad y plan de migración— vive en el wiki del ecosistema, no acá.
