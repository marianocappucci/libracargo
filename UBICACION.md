# ⚠️ Este árbol vive temporalmente dentro del repo del wiki

`libracargo/` es el **repositorio del producto**, escrito acá porque la sesión
que lo generó sólo tenía acceso a `llm-wiki-proyectos`.

**No es su lugar definitivo.** El contrato del wiki es explícito: el wiki
mantiene el contexto transversal del ecosistema, y los repos de producto viven
en WSL (`~/proyectos/<repo>`) y en GitHub. Tener el código en dos lugares es
exactamente la duplicación que el wiki previene.

## Qué hacer

1. Correr `herramientas/relevamiento/libracargo-bootstrap-wsl.sh` desde WSL:
   crea el repo en GitHub, copia **este árbol** a `~/proyectos/libracargo`,
   arma `develop` y deja el clon en el VPS.
2. **Borrar `libracargo/` de este repo** en el mismo momento, en un commit que
   lo diga.

Hasta que eso pase, **este árbol es la fuente de verdad** y no hay que editarlo
en dos lados.
