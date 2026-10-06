# Arquitectura — LibraCargo

Estado técnico actual. Los motivos de cada decisión están en `DECISIONS.md`.

## Componentes

- **Aplicación**: FastAPI (Python 3.12), SQLAlchemy 2.0.
- **Persistencia**: PostgreSQL 16. Es el único motor: `app/config.py` rechaza
  cualquier `DATABASE_URL` que no sea PostgreSQL, y no hay default a SQLite.
- **Migraciones**: Alembic, cadena desde `0001`.
- **Frontend**: React + TypeScript + Vite + Tailwind + shadcn/ui sobre
  `libra-ui` — pendiente, entra en F1.
- **Identidad**: `libraauth` (sesión por cookie firmada, PBKDF2) — pendiente.
- **Motor**: `libracore` **consumido parcialmente** (`pdf_generator`,
  `config_manager`). Sin facturación ARCA en esta etapa.
- **Infraestructura**: VPS Donweb. Una instancia por cliente, cada una con su
  red Docker y su sidecar PostgreSQL **sin puerto publicado**. Provisioning y
  deploy con `panel_admin.py` de LibraCore; dominio y SSL por Nginx Proxy
  Manager sobre el wildcard `*.libracargo.com.ar`.

## Modelo de datos

Once tablas, **18 claves foráneas, 36 índices y 9 restricciones CHECK**. El
sistema legado tenía cero FK y dos índices fuera de las claves primarias.

- **`terceros`** — cliente, fletero y/o proveedor en una sola tabla, con los
  roles como atributos. Una cuenta corriente por par *(tercero, rol)*.
- **`localidades`** — orígenes y destinos unificados.
- **`choferes`** y **`vehiculos`** — separados: un chofer maneja distintos
  equipos.
- **`razones_sociales`** — las razones sociales propias con CUIT y punto de venta.
- **`ordenes_carga`** — el núcleo. Estado explícito, comisión propia, FK real al
  comprobante.
- **El comprobante vive en `facturas` del motor** (ADR-030). Lo propio de acá
  (razón social, tercero, anulado, origen en el legado) va en
  `comprobantes_cargo`, con el mismo id. La numeración es única por *(emisor,
  ambiente, tipo, punto de venta, número)*: el emisor es la fila de ARCA del
  CUIT de la razón social. El comprobante de apertura del legado, que no es
  fiscal, está en `comprobante_de_apertura`. La tabla vieja quedó como
  `comprobantes_legado`, de sólo lectura.
- **La pre factura vive en `comprobantes_pendientes` del motor** (ADR-032), con
  número interno `PF-0001` y su ciclo. Lo propio de acá va en dos tablas:
  `pre_facturas_cargo` (la razón social y el tercero, con el mismo id) y
  `pre_factura_ordenes` (la reserva: `orden_id` es la clave primaria, así una
  orden está en a lo sumo una pre factura abierta).
- **La cuenta corriente vive en `cc_asientos`**, el libro de terceros del motor
  (ADR-031): las tres cuentas —cliente, fletero, proveedor— con `debe`/`haber` y
  descripción sin límite de largo, y lo propio (orden, cobro, gasto) en
  `movimientos_cuenta_cargo`. Sin saldo materializado: se suma con índice. La
  tabla vieja quedó como `movimientos_cuenta_legado`, de sólo lectura.
- **`movimientos_caja`** — cobros y pagos, con contrapartida en la misma
  transacción.
- **`auditoria`** — qué cambió, en `JSONB`, no sólo que algo pasó.

Todo importe es `NUMERIC(14,2)`; las cantidades, `NUMERIC(12,3)`.

## Flujo principal

1. Se carga una **orden de carga**: cliente, origen, destino, fletero, chofer,
   equipo, tarifa y comisión. Nace `pendiente`.
2. El **IVA se calcula en el servidor** a partir de la alícuota del tercero.
3. Se genera la **pre factura** de una o más órdenes del cliente (se reservan),
   se manda al cliente y, cuando está de acuerdo, se **factura por ARCA**: se
   emite el **comprobante** (el número lo da ARCA), las órdenes pasan a
   `facturada` y quedan ligadas por FK. No hay otra forma de crear un
   comprobante (ADR-032).
4. Cada operación asienta en las **cuentas corrientes** correspondientes:
   el cliente debe, el fletero cobra.
5. Los cobros y pagos entran por **caja** y generan su contrapartida en cuenta
   corriente **dentro de la misma transacción**.

## Entornos y deploy

- **Dev**: `dev.libracargo.com.ar`
- **Demo**: `demo.libracargo.com.ar`
- **Cliente**: `suitrans.libracargo.com.ar`

Flujo: editar en WSL → `git push` → `panel_admin.py actualizar` → verificar la
imagen del contenedor antes y después. Nunca editar en el servidor.

## Riesgos y límites conocidos

- **Consumo parcial de LibraCore**: `init_core_schema()` no es componible por
  tabla y el DDL de sus `CREATE TABLE` no es el schema real —hay columnas que
  agrega una migración aparte—. LibraDesk ya pagó ese costo; leer su caso antes
  de F1.
- **Migración desde Suitrans**: los datos vienen en `latin1` dentro de tablas
  `utf8mb3`, con importes en `float` de precisión simple y sin una sola FK. Los
  gates del plan de migración no son opcionales.
- **Sin frontend todavía**: la API existe pero nadie la consume.
