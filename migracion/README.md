# F6 — migración de Suitrans

El sistema viejo es [`suitrans.com.ar/sistema`](https://suitrans.com.ar/sistema):
PHP plano + MariaDB, 14 tablas, **52.526 filas desde 2021**. Se migra el
histórico completo, no un corte con saldo inicial.

Los pasos van en orden y **cada uno tiene un gate**. Sin los gates no hay forma
de saber si la migración salió bien o sólo salió sin errores.

| Paso | Qué hace | Gate | Estado |
|---|---|---|---|
| 1. Extraer | `01-extraer.sh` en la cuenta cPanel | El dump termina con la marca `Dump completed` | ✅ corrido el 2026-08-18 |
| 2. Cargar | `cargar.py` — dump → staging, todo `TEXT` | Conteos iguales al origen y sin doble encoding | ✅ |
| 3. Perfilar | `perfilar.py` — mide, no arregla | El informe, leído por una persona | ✅ |
| 4. Decidir | Cada caso raro del informe, uno por uno | Escrito en `DECISIONS.md` | ✅ ADR-009 a ADR-015 |
| 5. Transformar y cargar | staging → schema de LibraCargo | Sin huérfanos, secuencias al día | ✅ **corrida sobre los datos reales** |
| 6. Verificar | Saldo viejo contra saldo nuevo, por tercero | **El reporte de diferencias, validado por el cliente** | ✅ generado — ⏳ falta la validación |

## 1. Extraer

Se corre **en la cuenta cPanel `suitrans`**, no acá:

```
DB_NAME=xxx DB_USER=xxx DB_PASS='xxx' bash 01-extraer.sh
```

`mysqldump` completo con `--single-transaction` —InnoDB, así que no bloquea
producción— y `--default-character-set=latin1`, que devuelve los bytes tal como
están guardados. Deja también los conteos exactos por tabla y una **sonda de
encoding**: el HEX de unos pocos valores con acentos, que es lo único que dice
si adentro de esas columnas hay bytes latin1 (`E9`) o UTF-8 (`C3A9`).

> 🔴 El `.tar.gz` que sale tiene los datos reales de los clientes de Suitrans.
> Canal privado, y **no entra a ningún repositorio**.

## 2. Cargar al staging

```
python -m migracion.cargar --dump dump-suitrans.sql \
    --destino "postgresql://usuario@host:5432/libracargo_staging"
```

El dump **no se parsea**: se restaura en un MariaDB efímero —el mismo motor que
lo escribió— y desde ahí se leen las filas. Un parser propio de `INSERT` tiene
que reimplementar el escapado, las comillas y las filas múltiples, y falla en
silencio sobre la fila rara.

Entra todo como `TEXT` y sin una sola restricción (`espejo.sql`). Transformar
durante la carga mezcla el error que trae el dato con el que mete la conversión.

Dos cosas que decide este paso, y las dos **midiendo**:

- **La codificación.** Si aparecen valores que decodifican como UTF-8 y otros
  que no, el script **para**: una base con las dos mezcladas necesita una
  decisión humana.
- **Los conteos**, comparados fila por fila contra el MariaDB de origen. Un
  `COPY` que escribió de menos no falla: deja una tabla más corta.

## 3. Perfilar

```
python -m migracion.perfilar --origen "postgresql://…/libracargo_staging" \
    --salida informe-perfilado.md
```

Diez secciones: conteos, huérfanos de cada relación implícita, fechas
(`0000-00-00` incluido), texto cortado por el límite de la columna, las
cantidades que no son números, CUITs repetidos, la pérdida del `float(10,2)`,
si `importe1`/`importe2` son debe y haber, las razones sociales sin tabla, y el
**saldo por tercero calculado como lo calcula el legado** — que es el lado
izquierdo del gate del paso 6.

## Cómo se prueba esto sin los datos reales

`tests/test_migracion.py` arma un dump **de verdad**: levanta MariaDB, aplica
`legado-schema.sql` —el esquema real, salido del relevamiento— y le mete
`tests/legado_sintetico.sql`, que son datos inventados con las patologías
documentadas: huérfanos, `0000-00-00`, texto cortado a 50, cantidades que no son
números, CUITs repetidos y un importe que el `float` no representa.

**Cada patología convive con su control.** Una relación con huérfanos y otra
sin, una columna truncada y otra no: los tests afirman los ceros además de los
positivos, así un perfilado que contara siempre cero no pasaría igual.

Hacen falta Docker y un PostgreSQL (el mismo `DATABASE_URL` de la suite). Si no
hay Docker, el módulo entero se saltea con motivo — no en silencio.
