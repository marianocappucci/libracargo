/** Clientes (ADR-045; era la pestaña Clientes de «Entidades», ADR-040): una entrada propia del menú, con el contenido y el comportamiento de
 *  siempre. Se prueba que la pantalla tenga su título y su «Nuevo» en la línea del título, que liste los clientes, que el alta marque el
 *  rol, que `?ver=` abra la ficha (y cerrarla limpie la URL), que el CUIT repetido ofrezca sumar el rol y la línea de Carta de porte de la
 *  ficha (ADR-044).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { cuitDuplicado, entidad, responder, simularMatchMedia } from '@/test/entidades-de-prueba'

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

const { default: Clientes } = await import('./Clientes')
const { default: Proveedores } = await import('./Proveedores')
const { ApiError } = await import('libra-ui/api-client')

function Ubicacion() {
  const { pathname, search } = useLocation()
  return <p data-testid="ubicacion">{pathname + search}</p>
}

function abrir(url = '/clientes') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/clientes" element={<><Clientes /><Ubicacion /></>} />
        {/* A donde lleva el «Ver …» de un CUIT repetido que es de un proveedor. */}
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

describe('Clientes · pantalla', () => {
  it('tiene su título «Clientes», lista sólo los clientes y no tiene pestañas', async () => {
    abrir()
    expect(await screen.findByRole('heading', { name: 'Clientes' })).toBeInTheDocument()
    expect(await screen.findByText('Agro Norte SA')).toBeInTheDocument()
    expect(screen.queryByText('Transportes del Sur')).toBeNull()
    expect(screen.queryByText('Ferretería Central')).toBeNull()
    expect(screen.queryByRole('tablist')).toBeNull()
    expect(get).toHaveBeenCalledWith('/api/terceros/rol/cliente?solo_activos=false')
  })

  it('🔑 el «Nuevo» está en la misma línea que el título, no debajo', async () => {
    abrir()
    const nuevo = await screen.findByRole('button', { name: 'Nuevo' })
    const fila = screen.getByRole('heading', { name: 'Clientes' }).parentElement as HTMLElement
    expect(within(fila).getByRole('button', { name: 'Nuevo' })).toBe(nuevo)
    expect(screen.getAllByRole('button', { name: 'Nuevo' })).toHaveLength(1)
  })

  it('la columna Roles muestra los OTROS roles de la fila', async () => {
    conDosRoles()
    abrir()
    const fila = (await screen.findByText('Agro Norte SA')).closest('tr') as HTMLElement
    expect(within(fila).getByText('Proveedor')).toBeInTheDocument()
    expect(within(fila).queryByText('Cliente')).toBeNull()
  })

  it('🔑 el alta marca cliente de entrada y no los otros roles', async () => {
    post.mockResolvedValue(entidad(9, 'Nueva SA', ['cliente']))
    abrir()
    await screen.findByText('Agro Norte SA')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('heading', { name: 'Nuevo cliente' })).toBeInTheDocument()
    expect(within(within(dialogo).getByRole('group', { name: /Roles/ })).getByLabelText('Cliente')).toBeChecked()
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'Nueva SA' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toBe('/api/terceros')
    expect(post.mock.calls[0][1]).toMatchObject({ razon_social: 'Nueva SA', es_cliente: true })
    expect(post.mock.calls[0][1].es_fletero).toBeFalsy()
    expect(post.mock.calls[0][1].es_proveedor).toBeFalsy()
  })
})

describe('Clientes · ficha con ?ver=', () => {
  it('🔑 ?ver= abre la ficha de esa fila al cargar, sin la sección del fletero, y cerrarla limpia la URL', async () => {
    abrir('/clientes?ver=1')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('heading', { name: 'Editar cliente' })).toBeInTheDocument()
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    expect(within(dialogo).queryByRole('region', { name: 'Ficha del fletero' })).toBeNull()
    fireEvent.click(within(dialogo).getByText('Cancelar'))
    await waitFor(() => expect(ubicacion()).toBe('/clientes'))
  })

  it('abrir una fila con un click abre la ficha del cliente', async () => {
    abrir()
    fireEvent.click(await screen.findByText('Agro Norte SA'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
  })

  it('un ?ver= que no es un id se ignora', async () => {
    abrir('/clientes?ver=abc')
    await screen.findByText('Agro Norte SA')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('Clientes · CUIT repetido (409)', () => {
  async function altaRepetida(existente: Parameters<typeof cuitDuplicado>[1]) {
    post.mockRejectedValue(cuitDuplicado(ApiError, existente))
    abrir()
    await screen.findByText('Agro Norte SA')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'Ferretería' } })
    fireEvent.change(within(dialogo).getByLabelText('CUIT'), { target: { value: '30711111114' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    return dialogo
  }

  it('🔑 ofrece sumarle el rol de cliente a la entidad existente, y verla', async () => {
    const dialogo = await altaRepetida({ id: 3, razon_social: 'Ferretería Central', roles: ['proveedor'] })
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('ya es de «Ferretería Central»')
    expect(within(dialogo).getByRole('button', { name: 'Sumarle el rol de cliente' })).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Ver Ferretería Central' })).toBeInTheDocument()
  })

  it('«Sumarle el rol de cliente» llama al endpoint y cierra el diálogo', async () => {
    post.mockReset()
    post.mockRejectedValueOnce(cuitDuplicado(ApiError, { id: 3, razon_social: 'Ferretería Central', roles: ['proveedor'] }))
    post.mockResolvedValueOnce(entidad(3, 'Ferretería Central', ['proveedor', 'cliente']))
    abrir()
    await screen.findByText('Agro Norte SA')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'Ferretería' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    fireEvent.click(await within(dialogo).findByRole('button', { name: 'Sumarle el rol de cliente' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros/3/roles/cliente'))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('🔑 «Ver …» de un proveedor lleva a su ficha en Proveedores (/proveedores?ver=)', async () => {
    const dialogo = await altaRepetida({ id: 3, razon_social: 'Ferretería Central', roles: ['proveedor'] })
    fireEvent.click(await within(dialogo).findByRole('button', { name: 'Ver Ferretería Central' }))
    await waitFor(() => expect(ubicacion()).toBe('/proveedores?ver=3'))
    const ficha = await screen.findByRole('dialog')
    expect(within(ficha).getByRole('heading', { name: 'Editar proveedor' })).toBeInTheDocument()
    expect(within(ficha).getByLabelText('Razón social')).toHaveValue('Ferretería Central')
  })

  it('«Ver …» de un cliente se queda en Clientes con su ficha abierta', async () => {
    const dialogo = await altaRepetida({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] })
    fireEvent.click(await within(dialogo).findByRole('button', { name: 'Ver Agro Norte SA' }))
    await waitFor(() => expect(ubicacion()).toBe('/clientes?ver=1'))
    expect(within(await screen.findByRole('dialog')).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
  })
})

describe('Clientes · la línea de Carta de porte en la ficha del cliente (ADR-044)', () => {
  const titularDe = (extra: Record<string, unknown>) => ({
    id: 4, cuit: '30111111118', razon_social: 'Agro Norte SA', emite: 'nosotros', activo: true, notas: null,
    delegacion: 'delegado', tercero: { id: 1, razon_social: 'Agro Norte SA' }, tiene_plantilla: false, motivo: null,
    ...extra,
  })
  /** El servidor contesta `null` si el cliente no es titular. */
  function conTitular(valor: unknown) {
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta: string) => ruta === '/api/cartas-porte/titulares/de-tercero/1'
      ? Promise.resolve(valor) : base(ruta))
  }

  it.each([
    [{ delegacion: 'delegado' }, 'Carta de porte: delegó a nosotros ✓'],
    [{ delegacion: 'pendiente' }, 'Carta de porte: pendiente'],
    [{ emite: 'titular', delegacion: 'delegado' }, 'Carta de porte: emite él · consulta habilitada ✓'],
    [{ emite: 'titular', delegacion: 'pendiente' }, 'Carta de porte: emite él · falta que delegue'],
  ])('🔑 un cliente titular dice cómo está (%o) y lleva a su titular', async (extra, texto) => {
    conTitular(titularDe(extra))
    abrir('/clientes?ver=1')
    const dialogo = await screen.findByRole('dialog')
    expect(await within(dialogo).findByText(new RegExp(texto))).toBeInTheDocument()
    expect(within(dialogo).getByRole('link', { name: 'Ver titular' }))
      .toHaveAttribute('href', '/cartas-porte?pestana=titulares&ver=4')
    expect(get).toHaveBeenCalledWith('/api/cartas-porte/titulares/de-tercero/1')
  })

  it('un cliente que no es titular no muestra nada', async () => {
    conTitular(null)
    abrir('/clientes?ver=1')
    const dialogo = await screen.findByRole('dialog')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/cartas-porte/titulares/de-tercero/1'))
    expect(within(dialogo).queryByText(/Carta de porte:/)).toBeNull()
  })

  it('si la consulta falla, la ficha sigue sin la línea', async () => {
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta: string) => ruta.startsWith('/api/cartas-porte/')
      ? Promise.reject(new Error('sin red')) : base(ruta))
    abrir('/clientes?ver=1')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    expect(within(dialogo).queryByText(/Carta de porte:/)).toBeNull()
  })
})

/** Hace que «Agro Norte SA» sea además proveedor, para ver las pastillas de los otros roles. */
function conDosRoles() {
  const base = get.getMockImplementation()!
  get.mockImplementation((ruta: string) => ruta.startsWith('/api/terceros/rol/cliente')
    ? Promise.resolve([entidad(1, 'Agro Norte SA', ['cliente', 'proveedor'])]) : base(ruta))
}
