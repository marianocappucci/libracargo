// Config de tests aparte del vite.config.ts, y no un bloque `test` adentro de
// él: así el build de producción no arrastra tipos ni opciones de Vitest. Se
// reusa la config de Vite (con su alias `@`) vía mergeConfig, para que los
// tests resuelvan los imports igual que la app.
import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    // `@vitejs/plugin-react` no toca node_modules, así que los .tsx de
    // `libra-ui` los transpila esbuild — y por defecto usa el runtime CLÁSICO,
    // que emite `React.createElement` sin que React esté importado: "React is
    // not defined" al primer render. Con `automatic` usa el mismo runtime que
    // el resto de la app.
    esbuild: { jsx: 'automatic' },
    test: {
      environment: 'jsdom',
      globals: true,
      // Zona fija. Sin esto, todo test que compare una fecha depende de la
      // zona de la máquina: el CI y WSL vienen en UTC, y a las 22:00 de
      // Argentina eso ya es mañana. Se pone la zona real de los usuarios.
      env: { TZ: 'America/Argentina/Buenos_Aires' },
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
)
