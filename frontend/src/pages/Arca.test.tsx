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
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', () => ({
  ApiError: class extends Error {},
  api: { get, post: vi.fn(), postForm: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { FacturacionArca } = await import('./Arca')

describe('la pantalla de ARCA', () => {
  it('le pide la configuración y el estado al router de ESTE producto', async () => {
    // Los datos de la empresa (de ahí sale la razón social del pedido de certificado); lo demás, nada.
    get.mockImplementation(async (ruta: string) => (ruta === '/api/configuracion' ? { razon_social: 'Transportes Demo S.A.' } : null))
    render(<FacturacionArca />)

    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThanOrEqual(2))
    const rutas = get.mock.calls.map(([ruta]) => ruta as string)
    expect(rutas).toContain('/api/arca')
    expect(rutas).toContain('/api/arca/estado')
    // El default del kit. Si aparece, alguien sacó el `basePath`.
    expect(rutas.some((r) => r?.startsWith('/config/arca'))).toBe(false)
  })

  it('trae el tutorial de Padrón A13, el servicio que necesita «Consultar en ARCA», nombrando a este producto', async () => {
    get.mockImplementation(async () => null)
    render(<FacturacionArca />)

    const tutorial = (await screen.findByText(/consultar datos de clientes por CUIT/)).closest('details')!
    // Es a donde apunta el enlace del error de la consulta (`URL_TUTORIAL_PADRON`): el ancla la pone el kit.
    expect(tutorial).toHaveTextContent('el certificado que ya configuraste en LibraCargo')
  })
})
