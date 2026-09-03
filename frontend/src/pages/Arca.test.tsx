/** Lo único propio de esta pantalla es a dónde apunta.
 *
 *  El formulario, las validaciones y los dos pares los prueba `libra-ui` en su
 *  propia suite (`ArcaDosPares.test.tsx`); repetir eso acá sería medir el kit
 *  desde el consumidor. Lo que **sí** es de este producto es el `basePath`, y
 *  es lo que se rompe en silencio: la tarjeta compartida trae `/config/arca`
 *  por defecto y este producto publicó `/api/arca`. Con el default, la pantalla
 *  renderiza igual, pide una ruta que no existe y el catch-all del SPA le
 *  contesta el `index.html` con 200 — o sea que ni siquiera se ve como un error
 *  de red.
 *
 *  El slug de la empresa no se mira acá: no se renderiza en ningún campo, y lo
 *  que importa de él —que la emisión encuentre la fila aunque el slug no
 *  coincida— se prueba del lado del backend, que es donde vive la regla.
 */
import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', () => ({
  ApiError: class extends Error {},
  api: { get, post: vi.fn(), postForm: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { FacturacionArca } = await import('./Arca')

describe('la pantalla de ARCA', () => {
  it('le pide la configuración y el estado al router de ESTE producto', async () => {
    get.mockResolvedValue(null)
    render(<FacturacionArca />)

    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThanOrEqual(2))
    const rutas = get.mock.calls.map(([ruta]) => ruta as string)
    expect(rutas).toContain('/api/arca')
    expect(rutas).toContain('/api/arca/estado')
    // El default del kit. Si aparece, alguien sacó el `basePath`.
    expect(rutas.some((r) => r?.startsWith('/config/arca'))).toBe(false)
  })
})
