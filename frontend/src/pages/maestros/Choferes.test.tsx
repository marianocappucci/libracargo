/** El CUIT del chofer (ADR-037): es el que trae la Carta de Porte, y con él se cruza el chofer de la CPE con el
 *  de la orden. Se escribe con guiones, el servidor lo guarda en once dígitos y valida el verificador. */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post, put, del: vi.fn() } }
})

const { Choferes } = await import('./index')

const chofer = (id: number, extra: Record<string, unknown> = {}) => ({
  id, nombre: `Chofer ${id}`, dni: null, cuit: null, telefono: null, fletero_id: null,
  observaciones: null, activo: true, ...extra,
})

function abrir() {
  render(<MemoryRouter><Choferes /></MemoryRouter>)
}

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset()
})

describe('Choferes · CUIT', () => {
  it('el listado tiene la columna CUIT y lo muestra con guiones; sin CUIT queda vacío', async () => {
    get.mockResolvedValue([chofer(1, { cuit: '20333333336' }), chofer(2)])
    abrir()
    expect(await screen.findByText('20-33333333-6')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /CUIT/ })).toBeInTheDocument()
  })

  it('se busca por el CUIT, con o sin guiones', async () => {
    get.mockResolvedValue([chofer(1, { cuit: '20333333336' }), chofer(2, { nombre: 'Otro' })])
    abrir()
    await screen.findByText('20-33333333-6')
    fireEvent.change(screen.getByPlaceholderText(/Buscar en choferes/i), { target: { value: '20-33333333' } })
    await waitFor(() => expect(screen.queryByText('Otro')).toBeNull())
    expect(screen.getByText('Chofer 1')).toBeInTheDocument()
  })

  it('el formulario tiene el campo CUIT y le pone los guiones mientras se escribe', async () => {
    get.mockResolvedValue([])
    abrir()
    fireEvent.click(await screen.findByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    const campo = within(dialogo).getByLabelText('CUIT')

    fireEvent.change(campo, { target: { value: '2012345678' } })
    expect(campo).toHaveValue('20-12345678')
    fireEvent.change(campo, { target: { value: '20123456786' } })
    expect(campo).toHaveValue('20-12345678-6')
    // Letras y de más: sólo once dígitos.
    fireEvent.change(campo, { target: { value: '20-12345678-6-99ab' } })
    expect(campo).toHaveValue('20-12345678-6')
  })

  it('al guardar manda el CUIT con guiones (el servidor lo normaliza); vacío es null', async () => {
    get.mockResolvedValue([])
    post.mockResolvedValue(chofer(9))
    abrir()
    fireEvent.click(await screen.findByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Nombre'), { target: { value: 'Juan Pérez' } })
    fireEvent.change(within(dialogo).getByLabelText('CUIT'), { target: { value: '20123456786' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toBe('/api/choferes')
    expect(post.mock.calls[0][1]).toMatchObject({ nombre: 'Juan Pérez', cuit: '20-12345678-6' })

    // Y borrarlo deja null, no un texto vacío.
    fireEvent.click(await screen.findByText('Nuevo'))
    const otro = await screen.findByRole('dialog')
    const campo = within(otro).getByLabelText('CUIT')
    fireEvent.change(campo, { target: { value: '20' } })
    fireEvent.change(campo, { target: { value: '' } })
    fireEvent.change(within(otro).getByLabelText('Nombre'), { target: { value: 'Ana' } })
    fireEvent.click(within(otro).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    expect(post.mock.calls[1][1].cuit).toBeNull()
  })

  it('editar un chofer trae su CUIT con guiones, y el 422 del verificador se muestra tal cual', async () => {
    get.mockResolvedValue([chofer(1, { cuit: '20333333336' })])
    const { ApiError } = await import('libra-ui/api-client')
    put.mockRejectedValue(new (ApiError as unknown as new (s: number, d: string) => Error)(
      422, 'el CUIT del chofer no es válido: tienen que ser 11 dígitos con el verificador correcto'))
    abrir()
    fireEvent.click(await screen.findByText('Chofer 1'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('CUIT')).toHaveValue('20-33333333-6')

    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await screen.findByRole('alert')).toHaveTextContent('el CUIT del chofer no es válido')
  })
})
