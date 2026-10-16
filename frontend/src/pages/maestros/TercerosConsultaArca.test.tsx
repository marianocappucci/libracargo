/** El alta de un cliente (la tabla `terceros`) trae el botón «Consultar en ARCA» junto al CUIT. */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { default: Clientes } = await import('@/pages/Clientes')

const fetchMock = vi.fn()
beforeEach(() => { get.mockReset(); get.mockResolvedValue([]); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock) })
afterEach(() => vi.unstubAllGlobals())

describe('Clientes · Consultar en ARCA', () => {
  it('con el CUIT cargado, completa razón social, dirección y condición de IVA del formulario', async () => {
    fetchMock.mockResolvedValue({
      ok: true, status: 200,
      json: () => Promise.resolve({
        nombre: 'ACME SA', domicilio: 'Ruta 8 km 5, Pilar, Buenos Aires',
        iva_condition: 'Monotributista', estado: 'ACTIVO',
      }),
    })
    render(<MemoryRouter><Clientes /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('CUIT'), { target: { value: '30-71111111-4' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: /Consultar en ARCA/ }))

    await waitFor(() => expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('ACME SA'))
    expect(fetchMock).toHaveBeenCalledWith('/api/consultar-cuit/30711111114', { credentials: 'include' })
    expect(within(dialogo).getByLabelText('Dirección')).toHaveValue('Ruta 8 km 5, Pilar, Buenos Aires')
    expect(within(dialogo).getByRole('combobox', { name: 'Condición de IVA' })).toHaveValue('Monotributo')
  })

  it('el formulario de un chofer no lo tiene: no es un tercero con razón social', async () => {
    const { Choferes } = await import('@/pages/maestros')
    render(<MemoryRouter><Choferes /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).queryByRole('button', { name: /Consultar en ARCA/ })).toBeNull()
  })
})
