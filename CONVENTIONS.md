# Convenciones — LibraCargo

Reglas específicas de este repositorio. Las generales del ecosistema están en
`AGENTS.md`/`CLAUDE.md` y en el wiki.

## Código

- Python 3.12, SQLAlchemy 2.0 con `Mapped`/`mapped_column`.
- **Dominio y base de datos en español** (`ordenes_carga`, `terceros`,
  `movimientos_cuenta`): es el vocabulario del negocio y del cliente.
- Todo importe es `Numeric(14, 2)` y se maneja como `Decimal`. **Nunca `float`
  para plata**, en ninguna capa.
- Fechas operativas en `Date`; marcas de tiempo en `DateTime(timezone=True)`.
- El formateo `dd-mm-aaaa` vive **sólo** en `app/tiempo.py`, nunca repetido por
  vista. Las APIs y los parámetros de URL siguen en ISO 8601.
- Sin SQL armado por concatenación. Nunca.

## Tests

- **La suite corre contra PostgreSQL real.** `conftest.py` verifica el dialecto
  y falla si no lo es.
- Cada restricción del esquema tiene un test que la prueba **rompiéndola**: un
  `CHECK` que nadie intentó violar no está verificado.
- Los tests del esquema referencian el defecto real del sistema legado que
  vienen a impedir, no una regla inventada.

## Migraciones

- Cadena Alembic numerada desde `0001`.
- Toda migración que cree un tipo `ENUM` **debe** borrarlo en `downgrade()`.
- El ciclo `upgrade → downgrade → upgrade` es parte de la suite.

## Git y ramas

- `develop`: desarrollo e integración. `main`: producción, vía Pull Request.
- Auxiliares: `feature/...`, `fix/...`, `chore/...`, `hotfix/...`.
- Después de promover a `main`, **back-merge a `develop`**: el merge commit no
  vuelve solo y el desfase se acumula PR a PR.

## Seguridad y configuración

- Ningún secreto en el código. Todo por variables de entorno.
- Acceso a repos privados por **deploy key SSH de sólo lectura**, nunca un PAT.
- El contenedor corre como usuario sin privilegios.

## Dónde se arregla (regla de la familia, 2026-10-03)

**El arreglo de fondo vive siempre en el motor** (`libracore`; `libracommerce` y `libra-ui` para
lo suyo), **nunca en este repo.** Lo que otro producto comparte o podría compartir —el protocolo
con ARCA, las reglas fiscales y sus validaciones, las guardas contra duplicados, la numeración, la
cuenta corriente, los componentes de pantalla compartidos— se escribe y se arregla en el motor.
Este repo sólo aporta **costuras** (los hooks que el motor ya expone) y lo suyo: pantallas,
textos y su modelo de datos propio. Si falta la costura, se agrega al motor; si el arreglo hace
falta antes, igual se hace en el motor (PR y tag) y acá se sube el pin: nada «provisorio» en este
repo. Un hueco que se encuentra acá se busca en los demás productos antes de darlo por acotado.
Detalle y motivo: `reglas/producto.md` del wiki.
