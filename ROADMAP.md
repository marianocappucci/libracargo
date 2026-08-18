# Roadmap — LibraCargo

Dirección estratégica. Las tareas concretas están en `TASKS.md`.

## Objetivo actual

- [ ] **F1 — Esqueleto**: FastAPI + LibraAuth + libra-ui corriendo en
      `dev.libracargo.com.ar`, con login real.

## Hitos

### F0 — Prerrequisitos ✅

- Resultado: dominio `libracargo.com.ar` registrado con wildcard en el VPS,
  repo creado, CI en verde.
- Criterio de terminado: `develop` y `main` con CI verde, rama default `main`.

### F1 — Esqueleto

- Resultado: se entra con usuario real; el layout de la familia responde.
- Criterio: login funcionando en `dev`, healthcheck en verde, frontend servido
  desde el mismo origen que la API.
- Dependencias: deploy keys de `libraauth` y `libra-ui` cargadas como secrets.

### F2 — Maestros

- Resultado: ABM de terceros, localidades, choferes, vehículos, razones
  sociales y tipos de carga.
- Criterio: cobertura de tests sobre cada ABM.

### F3 — Órdenes de carga

- Resultado: el núcleo — alta, modificación, listados y filtros.
- Criterio: los filtros que hoy son once pantallas distintas resueltos en una.

### F4 — Cuentas corrientes y caja

- Resultado: las tres cuentas y la caja, con contrapartida transaccional.
- Criterio: el saldo de un tercero da igual calculado por dos caminos distintos.

### F5 — Comprobantes

- Resultado: registro de comprobantes y facturar pendientes.
- Criterio: totales por razón social reproducibles contra el sistema viejo.

### F6 — Migración de Suitrans

- Resultado: los datos históricos completos en `suitrans.libracargo.com.ar`.
- Criterio: **el reporte de diferencias de saldo por tercero, validado por el
  cliente.** No los conteos por tabla.

### F7 — Impresión

- Resultado: orden de carga y comprobantes en PDF vía `pdf_generator`.

## Futuro

- **F8 — Emisión ARCA** real vía LibraCore.
- Portal del cliente para consultar sus órdenes y su cuenta corriente.
- App del chofer para confirmar entrega — hoy no hay estado de viaje en
  ninguna parte.
