// Guard: los reportes y el tablero toman sus íconos del catálogo de la familia (`libra-ui/iconos-indicador`, ADR-038 del kit).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una pantalla se rompa —ninguna se rompe con el ícono equivocado— sino
// que **vuelvan a divergir**: que la próxima tarjeta de un reporte importe un ícono de `lucide-react` porque quedaba bien, y que el menú diga
// una cosa y el reporte otra. Eso no se ve en ningún render; se ve en el `import`. El motor vive en `libra-ui/auditoria-de-indicadores`
// (uno para los nueve productos) y tiene sus propios tests allá; acá se lo corre sobre el `src/` de este producto.
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarIndicadores, describirInfracciones } from 'libra-ui/auditoria-de-indicadores'
import { INDICADORES } from 'libra-ui/iconos-indicador'
import { CONCEPTO_DE_REPORTE, conceptoDelReporte } from '@/conceptos-de-reportes'

const SRC = join(process.cwd(), 'src')

describe('los reportes y el tablero toman el ícono del catálogo', () => {
  it('🔴 ninguna pantalla de reporte o de tablero importa un ícono de concepto de lucide-react', () => {
    const r = auditarIndicadores(SRC)
    expect(describirInfracciones(r.infracciones)).toEqual([])
    // El control: un parser que no encuentra ninguna pantalla también deja `infracciones` vacío.
    expect(r.pantallas).toBeGreaterThan(0)
  })

  it('🔴 el control — el guard mide el tablero y el índice de reportes', () => {
    const r = auditarIndicadores(SRC, { esPantalla: (ruta) => /^pages\/(Inicio|ReportesIndice|Reporte)\.tsx$/.test(ruta) })
    expect(r.pantallas).toBe(3)
    expect(r.infracciones).toEqual([])
  })
})

describe('el concepto de cada reporte', () => {
  it('🔴 cada reporte del catálogo apunta a un concepto que existe', () => {
    for (const [slug, concepto] of Object.entries(CONCEPTO_DE_REPORTE)) {
      expect(INDICADORES[concepto], slug).toBeDefined()
    }
  })

  it('un reporte que el servidor sumó y acá no se conoce lleva el ícono de la sección, no queda sin ícono', () => {
    expect(conceptoDelReporte('un-reporte-nuevo')).toBe('reportes')
    expect(conceptoDelReporte('saldos')).toBe('saldos')
  })
})
