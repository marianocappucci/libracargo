# Tasks — LibraCargo

Trabajo concreto y vigente. Al completar o descartar una tarea se actualiza;
esto no es un historial.

## En curso

- [ ] **F1** — Integrar LibraAuth: login, sesión por cookie firmada, tabla
      `usuarios` en la misma base.
- [ ] **F1** — Frontend sobre `libra-ui`: layout con sidebar, sin barra
      superior, mismo origen que la API.
- [ ] **F1** — Desplegar en `dev.libracargo.com.ar` con `panel_admin.py`.

## Próximas

- [ ] **F2** — ABM de maestros sobre el esquema ya migrado.
- [ ] Cargar las dos razones sociales reales (`Suitrans`, `Mauricio`) con CUIT
      y punto de venta — hoy sólo se conocen sus códigos del legado, `1` y `2`.
- [ ] Definir el catálogo inicial de `tipos_carga` con los valores distintos que
      haya en `carga_tipo` del legado.

## Bloqueadas

- [ ] **Relevamiento con el cliente**: qué pantallas usa de verdad, si las dos
      razones sociales están activas, y si hay operaciones con alícuota
      distinta del 21% que hoy se corrigen a mano.

## Deuda asumida a propósito

- Sin frontend: la API existe y nadie la consume todavía.
- `libracore` y `libraauth` están declarados y comentados en `pyproject.toml`:
  el esqueleto se construye y se prueba sin acceso a esos repos privados.
