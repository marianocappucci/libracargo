/** El cliente de una orden se puede dar de alta ahí mismo (ADR-071 de libra-ui, ADR-050 de este producto).
 *
 *  Lo que se prueba es de punta a punta en lo que decide la pantalla: el alta viaja a `POST /api/terceros` con el cuerpo de un tercero
 *  cliente (`razon_social`, `es_cliente: true`, el CUIT y la condición frente al IVA ya pasada al enum del servidor), el cliente
 *  queda elegido en la orden, y la orden se guarda con su id. El guard de los fuentes está en `test/campos-de-cliente.test.ts`.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20_000 })

const get = vi.fn()
const post = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post, put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { default: Ordenes } = await import('./Ordenes')

beforeEach(() => {
  get.mockReset(); post.mockReset()
  get.mockImplementation((ruta?: string) => {
    if (ruta?.startsWith('/api/terceros')) {
      return Promise.resolve([{ id: 1, razon_social: 'Agro Norte', es_cliente: true }])
    }
    if (ruta?.startsWith('/api/localidades')) return Promise.resolve([{ id: 1, nombre: 'Suipacha' }])
    if (ruta?.startsWith('/api/configuracion')) return Promise.resolve({})
    return Promise.resolve([])
  })
})

async function nuevaOrden() {
  render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: /Nueva/ }))
  const dialogo = await screen.findByRole('dialog')
  // Las opciones llegan después de abrir: sin esperarlas, el cliente creado se mezclaría con la carga.
  await waitFor(() => expect(get).toHaveBeenCalledWith(expect.stringContaining('/api/terceros')))
  return dialogo
}

describe('Órdenes · alta de cliente desde el campo «Cliente»', () => {
  it('🔑 «Agregar nuevo cliente» crea un tercero cliente y lo deja elegido en la orden', async () => {
    post.mockResolvedValue({ id: 77, razon_social: 'Cereales del Sur', cuit: '30-71234567-8', es_cliente: true })
    const dialogo = await nuevaOrden()

    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = await within(dialogo).findByRole('group', { name: 'Nuevo cliente' })
    // Acá se factura: además del contacto, se piden el CUIT y la condición frente al IVA.
    expect(within(panel).getByLabelText('CUIT')).toBeInTheDocument()
    expect(within(panel).getByLabelText('Condición frente al IVA')).toBeInTheDocument()

    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Cereales del Sur' } })
    fireEvent.change(within(panel).getByLabelText('CUIT'), { target: { value: '30-71234567-8' } })
    fireEvent.change(within(panel).getByLabelText('Teléfono'), { target: { value: '2226 444555' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear cliente' }))

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post).toHaveBeenCalledWith('/api/terceros', {
      razon_social: 'Cereales del Sur', es_cliente: true, cuit: '30-71234567-8', telefono: '2226 444555',
    })
    // Queda elegido, con el nombre y no con el id, y el panel se cierra.
    await waitFor(() => expect(within(dialogo).getByRole('combobox', { name: 'Cliente' })).toHaveValue('Cereales del Sur'))
    expect(within(dialogo).queryByRole('group', { name: 'Nuevo cliente' })).toBeNull()
  })

  it('la condición frente al IVA viaja como el enum del servidor; las que no tienen equivalente no viajan', async () => {
    post.mockResolvedValue({ id: 78, razon_social: 'Dos Hermanos', es_cliente: true })
    const dialogo = await nuevaOrden()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = await within(dialogo).findByRole('group', { name: 'Nuevo cliente' })

    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Dos Hermanos' } })
    fireEvent.click(within(panel).getByRole('combobox', { name: 'Condición frente al IVA' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Monotributista' }))
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear cliente' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros', {
      razon_social: 'Dos Hermanos', es_cliente: true, condicion_iva: 'monotributo',
    }))
  })

  it('si el servidor lo rechaza (CUIT repetido) se dice dentro del panel y lo cargado no se pierde', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    post.mockRejectedValue(new (ApiError as unknown as new (s: number, d: string) => Error)(
      409, 'El CUIT 30-71234567-8 ya es de «Cereales del Sur» (fletero). Sumale el rol en vez de cargarla de nuevo.'))
    const dialogo = await nuevaOrden()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = await within(dialogo).findByRole('group', { name: 'Nuevo cliente' })

    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Cereales del Sur' } })
    fireEvent.change(within(panel).getByLabelText('CUIT'), { target: { value: '30-71234567-8' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear cliente' }))

    expect(await within(panel).findByRole('alert')).toHaveTextContent('ya es de «Cereales del Sur»')
    expect(within(panel).getByLabelText('CUIT')).toHaveValue('30-71234567-8')
  })
})
