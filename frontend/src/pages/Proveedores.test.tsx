/** Proveedores (ADR-045; era la pestaña Proveedores de «Entidades», ADR-040): una entrada propia del menú, con el contenido y el
 *  comportamiento de siempre. Se prueba el título, el «Nuevo» en la línea del título, el listado del rol, el alta con el rol marcado y que
 *  `?ver=` abra la ficha (sin la línea de Carta de porte, que es de los clientes).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { entidad, responder, simularMatchMedia } from '@/test/entidades-de-prueba'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: string
    detailData?: unknown
    constructor(status: number, detail: string, detailData?: unknown) {
      super(detail); this.status = status; this.detail = detail; this.detailData = detailData
    }
  }
  return { ApiError, api: { get, post, put, del: vi.fn(), postForm: vi.fn() } }
})
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'admin', name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: Proveedores } = await import('./Proveedores')

function Ubicacion() {
  const { pathname, search } = useLocation()
  return <p data-testid="ubicacion">{pathname + search}</p>
}

function abrir(url = '/proveedores') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/proveedores" element={<><Proveedores /><Ubicacion /></>} />
      </Routes>
    </MemoryRouter>,
  )
}
const ubicacion = () => screen.getByTestId('ubicacion').textContent

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset()
  responder(get)
  simularMatchMedia()
})

describe('Proveedores · pantalla', () => {
  it('tiene su título «Proveedores», lista sólo los proveedores y no tiene pestañas', async () => {
    abrir()
    expect(await screen.findByRole('heading', { name: 'Proveedores' })).toBeInTheDocument()
    expect(await screen.findByText('Ferretería Central')).toBeInTheDocument()
    // Una entidad que es fletero y proveedor está en las dos pantallas: es una fila.
    expect(screen.getByText('Transportes del Sur')).toBeInTheDocument()
    expect(screen.queryByText('Agro Norte SA')).toBeNull()
    expect(screen.queryByRole('tablist')).toBeNull()
    expect(get).toHaveBeenCalledWith('/api/terceros/rol/proveedor?solo_activos=false')
  })

  it('la columna Roles muestra los OTROS roles, no el de la pantalla', async () => {
    abrir()
    const fila = (await screen.findByText('Transportes del Sur')).closest('tr') as HTMLElement
    expect(within(fila).getByText('Fletero')).toBeInTheDocument()
    expect(within(fila).queryByText('Proveedor')).toBeNull()
  })

  it('🔑 el «Nuevo» está en la misma línea que el título, no debajo', async () => {
    abrir()
    const nuevo = await screen.findByRole('button', { name: 'Nuevo' })
    const fila = screen.getByRole('heading', { name: 'Proveedores' }).parentElement as HTMLElement
    expect(within(fila).getByRole('button', { name: 'Nuevo' })).toBe(nuevo)
    expect(screen.getAllByRole('button', { name: 'Nuevo' })).toHaveLength(1)
  })

  it('🔑 el alta marca proveedor, no cliente', async () => {
    post.mockResolvedValue(entidad(9, 'X', ['proveedor']))
    abrir()
    await screen.findByText('Ferretería Central')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('heading', { name: 'Nuevo proveedor' })).toBeInTheDocument()
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'X' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toMatchObject({ es_proveedor: true })
    expect(post.mock.calls[0][1].es_cliente).toBeFalsy()
  })
})

describe('Proveedores · ficha con ?ver=', () => {
  it('🔑 ?ver= abre la ficha de esa fila, sin pedir la línea de Carta de porte, y cerrarla limpia la URL', async () => {
    abrir('/proveedores?ver=3')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('heading', { name: 'Editar proveedor' })).toBeInTheDocument()
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Ferretería Central')
    expect(get.mock.calls.some(([r]) => String(r).includes('/titulares/de-tercero/'))).toBe(false)
    fireEvent.click(within(dialogo).getByText('Cancelar'))
    await waitFor(() => expect(ubicacion()).toBe('/proveedores'))
  })

  it('un fletero que también es proveedor abre con su ficha de proveedor, sin la sección de choferes', async () => {
    abrir('/proveedores?ver=2')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Transportes del Sur')
    expect(within(dialogo).queryByRole('region', { name: 'Ficha del fletero' })).toBeNull()
  })
})
