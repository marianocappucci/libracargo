# Tasks — LibraCargo

Trabajo concreto y vigente. Al completar o descartar una tarea se actualiza;
esto no es un historial.

## En curso

- [x] **F1** — Integrar LibraAuth: login, sesión por cookie firmada, tabla
      `usuarios` en la misma base.
- [x] **F1** — Frontend sobre `libra-ui`: layout con sidebar, sin barra
      superior, mismo origen que la API.
- [ ] **F1** — Desplegar en `dev.libracargo.com.ar` con `docker compose`.
      🔑 **No con `panel_admin.py`**, como decía acá: ese vive en
      LibraCore —que este producto no consume hasta F7— y provisiona
      instancias de **cliente** bajo `clientes/<slug>/`. Los `dev` del resto
      de la familia corren por compose desde el clon del repo en el VPS,
      sobre la red compartida `stack_stack-net`, y Nginx Proxy Manager los
      alcanza por alias de contenedor.

## Próximas

- [ ] **F2** — ABM de maestros sobre el esquema ya migrado.
- [ ] Verificar en cada instancia que «Datos de la empresa» tenga el CUIT y la condición de IVA, y que
      el CUIT de Configuración → ARCA sea el mismo (ADR-035: ya no hay razones sociales).
- [ ] Definir el catálogo inicial de `tipos_carga` con los valores distintos que
      haya en `carga_tipo` del legado.

- [ ] **Caja al motor en Suitrans** (ADR-055, revisión `0032`): respaldo, restauración de prueba, `scripts/comparar_caja.py`
      antes y después (saldos por tercero y F4), y recién ahí en la instancia real, con el OK del humano. Después,
      una `0033` que retire `movimientos_caja_legado`.

## Bloqueadas

- [ ] **Relevamiento con el cliente**: qué pantallas usa de verdad, y si hay operaciones con alícuota
      distinta del 21% que hoy se corrigen a mano.

## Deuda asumida a propósito

- **El plan es uno solo y sin precio** (ADR-049, 2026-10-14): `unico`, «Consultar precio». Falta
  que el negocio defina el precio; cuando lo haga, se carga en `PLAN_PRECIOS` de `plans.py` y nada más.
- **El backoffice no expone `smtp` ni `demos`**: este producto todavía no tiene
  pantalla de configuración de correo ni instancia de demo pública. Están fuera
  de `FEATURES` a propósito — declararlas sin que existan del otro lado daría
  pestañas que contestan 404.
- Sin frontend: la API existe y nadie la consume todavía.
- ~~`libracore` y `libraauth` están declarados y comentados en
  `pyproject.toml`~~ — los dos son dependencias reales desde que entraron el
  auth y el backup. Lo que sigue difiriéndose de LibraCore es su **alcance**
  (`pdf_generator` en F7, ARCA en F8), no el paquete. Ver ADR-016.
