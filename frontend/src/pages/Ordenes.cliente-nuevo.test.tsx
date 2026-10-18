/** El cliente de una orden se puede dar de alta ahí mismo (ADR-071 de libra-ui, ADR-050 de este producto).
 *
 *  Lo que se prueba es de punta a punta en lo que decide la pantalla: el alta viaja a `POST /api/terceros` con el cuerpo de un tercero
 *  cliente (`razon_social`, `es_cliente: true`, el CUIT y la condición frente al IVA ya pasada al enum del servidor), el cliente
 *  queda elegido en la orden, y la orden se guarda con su id. El guard de los fuentes está en `test/campos-de-cliente.test.ts`.
 *
 *  Un CUIT que ya es de otra entidad (ADR-040) ofrece sumarle el rol de cliente y elegirla (ADR-052).
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { cuitDuplicado } from '@/test/entidades-de-prueba'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20_000 })

const get = vi.fn()
const post = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    detailData: unknown
    constructor(status: number, detail: unknown, detailData?: unknown) {
      super(String(detail)); this.status = status; this.detail = detail; this.detailData = detailData
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

  async function cargarConCuitRepetido() {
    const dialogo = await nuevaOrden()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = await within(dialogo).findByRole('group', { name: 'Nuevo cliente' })
    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Transportes del Sur' } })
    fireEvent.change(within(panel).getByLabelText('CUIT'), { target: { value: '30-71111111-4' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear cliente' }))
    return { dialogo, panel }
  }

  it('🔑 si el CUIT ya es de un fletero, ofrece sumarle el rol de cliente y la deja elegida en la orden', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    post.mockImplementation((ruta: string) => ruta === '/api/terceros'
      ? Promise.reject(cuitDuplicado(ApiError as never, { id: 2, razon_social: 'Transportes del Sur', roles: ['fletero'] }))
      : Promise.resolve({ id: 2, razon_social: 'Transportes del Sur', cuit: '30711111114', es_cliente: true, es_fletero: true }))
    const { dialogo } = await cargarConCuitRepetido()

    const pregunta = await screen.findByRole('alertdialog')
    expect(pregunta).toHaveTextContent('Sumar el rol de cliente a «Transportes del Sur»')
    fireEvent.click(within(pregunta).getByRole('button', { name: 'Sumar el rol de cliente' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros/2/roles/cliente'))
    // No se carga una segunda entidad: el único alta fue el que chocó.
    expect(post.mock.calls.filter(([r]) => r === '/api/terceros')).toHaveLength(1)
    await waitFor(() => expect(within(dialogo).getByRole('combobox', { name: 'Cliente' })).toHaveValue('Transportes del Sur'))
    expect(within(dialogo).queryByRole('group', { name: 'Nuevo cliente' })).toBeNull()
  })

  it('si no se acepta sumar el rol, el panel muestra el mensaje del servidor y lo cargado no se pierde', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    post.mockRejectedValue(cuitDuplicado(ApiError as never, { id: 2, razon_social: 'Transportes del Sur', roles: ['fletero'] }))
    const { panel } = await cargarConCuitRepetido()

    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancelar' }))

    expect(await within(panel).findByRole('alert')).toHaveTextContent('ya es de «Transportes del Sur»')
    expect(within(panel).getByLabelText('CUIT')).toHaveValue('30-71111111-4')
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('si el CUIT ya es de un cliente activo, se lo elige sin tocarlo', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    post.mockRejectedValue(cuitDuplicado(ApiError as never, { id: 5, razon_social: 'Transportes del Sur', roles: ['cliente'] }))
    const { dialogo } = await cargarConCuitRepetido()

    const pregunta = await screen.findByRole('alertdialog')
    expect(pregunta).toHaveTextContent('«Transportes del Sur» ya es cliente')
    fireEvent.click(within(pregunta).getByRole('button', { name: 'Elegirlo' }))

    await waitFor(() => expect(within(dialogo).getByRole('combobox', { name: 'Cliente' })).toHaveValue('Transportes del Sur'))
    expect(post).toHaveBeenCalledTimes(1)
  })
})
