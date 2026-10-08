// Guard: una pantalla no agrega relleno propio arriba de lo que ya le da el `Layout` (ADR-040 del kit).
//
// 🔴 **Lee los FUENTES, no el DOM.** Una pantalla con un `p-6` de más no se rompe: se ve «un espacio vacío arriba» y el título más abajo
// que el nombre de la app (pedido del dueño, 2026-10-08, con la captura del Dashboard). Y vuelve sola: la próxima pantalla copia el
// `<div className="p-6">` de la de al lado. El motor vive en `libra-ui/auditoria-de-relleno` y tiene sus propios tests allá.
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarRelleno, describirInfracciones, describirSobrantes, esPantallaDeProducto } from 'libra-ui/auditoria-de-relleno'

const SRC = join(process.cwd(), 'src')

/** Las pantallas de `pages/` y `AbmMaestro`, que es la raíz de las de `maestros/` (Clientes, Fleteros, Choferes…) y por eso cuenta como una. */
const esPantalla = (ruta: string) => esPantallaDeProducto(ruta) || ruta === 'components/AbmMaestro.tsx'

/** Ruta relativa a `src/` → por qué esa pantalla sí lleva relleno propio (se dibuja fuera del `Layout`). */
const EXCEPCIONES: Record<string, string> = {}

describe('las pantallas no duplican el relleno del Layout', () => {
  const r = auditarRelleno(SRC, { esPantalla, excepciones: EXCEPCIONES })

  it('🔴 ninguna pantalla arranca con p-N / py-N / pt-N / mt-N en su raíz', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })

  it('🔴 ninguna excepción sobra', () => {
    expect(describirSobrantes(r.sobrantes)).toEqual([])
  })

  it('🔴 el control — el guard midió pantallas y raíces (si no, una lista vacía no probaría nada)', () => {
    expect(r.pantallas).toBeGreaterThan(0)
    expect(r.raices).toBeGreaterThanOrEqual(r.pantallas)
  })
})
