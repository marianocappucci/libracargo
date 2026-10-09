/** Los datos habituales de un titular en su propia página (2026-10-09). Lo del formulario está en
 *  `components/PlantillaDeTitular.test.tsx`; acá, que la página encuentra al titular y decide qué mostrar. */
import { configure, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

configure({ asyncUtilTimeout: 5000 })

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const sesion = { rol: 'admin' }
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: sesion.rol, name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: PlantillaDeTitularPagina } = await import('./PlantillaDeTitular')

const RUTA = '/api/cartas-porte'
const titular = (extra: Record<string, unknown>) => ({
  cuit: '30222222223', activo: true, notas: null, delegacion: 'delegado', tercero: null, tiene_plantilla: true, ...extra,
})

beforeEach(() => {
  get.mockReset()
  sesion.rol = 'admin'
  get.mockImplementation((ruta: string) => {
    if (ruta === `${RUTA}/titulares`) {
      return Promise.resolve({
        ambiente: 'produccion', verificado: true, motivo: null, cuit_para_catalogos: '30222222223',
        titulares: [
          titular({ id: 4, razon_social: 'Agropecuaria Los Talas', emite: 'nosotros' }),
          titular({ id: 5, cuit: '30111111118', razon_social: 'Agro Solo SA', emite: 'titular' }),
        ],
        sin_cargar: [],
      })
    }
    if (ruta === `${RUTA}/titulares/4/plantilla`) {
      return Promise.resolve({ datos: { cod_grano: 19, cosecha: 2526 }, existe: true, actualizada: null })
    }
    return Promise.resolve([])
  })
})

function abrir(id: string) {
  render(
    <MemoryRouter initialEntries={[`/cartas-porte/titulares/${id}/plantilla`]}>
      <Routes>
        <Route path="/cartas-porte/titulares/:id/plantilla" element={<PlantillaDeTitularPagina />} />
      </Routes>
    </MemoryRouter>)
}

describe('Datos habituales para emitir · la página', () => {
  it('muestra la plantilla del titular de la URL, con su nombre, y se vuelve a su ficha', async () => {
    abrir('4')
    expect(screen.getByRole('heading', { name: 'Datos habituales para emitir' })).toBeInTheDocument()
    expect(await screen.findByText('Agropecuaria Los Talas')).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Datos habituales para emitir' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Cosecha')).toHaveValue('2526')
    expect(get).toHaveBeenCalledWith(`${RUTA}/titulares/4/plantilla`)
    expect(screen.getByRole('button', { name: 'Guardar plantilla' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver al titular' }))
      .toHaveAttribute('href', '/cartas-porte?pestana=titulares&ver=4')
  })

  it('un operador la ve y no la guarda', async () => {
    sesion.rol = 'staff'
    abrir('4')
    expect(await screen.findByLabelText('Cosecha')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Guardar plantilla' })).toBeNull()
  })

  it('un titular que emite él no lleva plantilla', async () => {
    abrir('5')
    expect(await screen.findByText(/emite sus propias cartas de porte/)).toBeInTheDocument()
    expect(get).not.toHaveBeenCalledWith(`${RUTA}/titulares/5/plantilla`)
  })

  it('un titular que no está en la lista lo dice', async () => {
    abrir('99')
    expect(await screen.findByRole('alert')).toHaveTextContent('No hay un titular con ese número')
  })
})
