// Guard: todo desplegable donde se elige información se busca escribiendo (ADR-039 del kit).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una pantalla se rompa —ninguna se rompe con un `<select>` de 300
// choferes— sino que **vuelva a nacer** un desplegable de datos que no se puede buscar, que es lo que el dueño pidió que no exista
// (2026-10-08). Eso no se ve en ningún render con datos de prueba; se ve en el JSX. El motor vive en `libra-ui/auditoria-de-selects`
// (uno para los nueve productos) y tiene sus propios tests allá; acá se lo corre sobre el `src/` de este producto.
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarSelects, describirInfracciones } from 'libra-ui/auditoria-de-selects'

const SRC = join(process.cwd(), 'src')

describe('los desplegables de datos se buscan escribiendo', () => {
  const r = auditarSelects(SRC)

  it('🔴 ningún desplegable de datos es un select sin búsqueda', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })

  it('🔴 el control — el guard midió desplegables (si no, una lista vacía no probaría nada)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.desplegables).toBeGreaterThan(0)
  })
})
