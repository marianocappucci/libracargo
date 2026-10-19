/** Caja, «cuenta primero» (ADR-053, decisión del humano 2026-10-18).
 *
 *  Primero se elige la cuenta (cliente, fletero o proveedor) y después el tercero, entre los de ese rol y con alta en el lugar **en ese rol**.
 *  Un CUIT que ya es de otra entidad ofrece sumarle ese rol (el patrón del ADR-052, generalizado). Cambiar la cuenta deja el tercero sólo si
 *  tiene el rol nuevo. Y el movimiento se guarda con el tercero recién creado y su cuenta.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { cuitDuplicado, ENTIDADES } from '@/test/entidades-de-prueba'

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

const { default: Caja } = await import('./Caja')

const MOVIMIENTO = {
  id: 5, fecha: '2026-08-21', tipo: 'egreso', concepto: 'Pago', descripcion: null, tercero_id: 3,
  importe: '1000.00', medio_pago: 'efectivo', recibo: null, anulado: false,
}

// Agro Norte SA (1) es cliente; Transportes del Sur (2), fletero y proveedor; Ferretería Central (3), proveedor.
beforeEach(() => {
  get.mockReset(); post.mockReset()
  get.mockImplementation((ruta?: string) => {
    if (ruta?.startsWith('/api/terceros')) return Promise.resolve(ENTIDADES)
    if (ruta?.startsWith('/api/caja')) return Promise.resolve([MOVIMIENTO])
    return Promise.resolve([])
  })
})

async function nuevoMovimiento() {
  render(<MemoryRouter><Caja /></MemoryRouter>)
  await screen.findByText('Ferretería Central')   // la fila del movimiento, con los terceros ya cargados
  fireEvent.click(screen.getByRole('button', { name: /Nuevo movimiento/ }))
  const dialogo = await screen.findByRole('dialog')
  fireEvent.change(within(dialogo).getByLabelText('Concepto'), { target: { value: 'Pago' } })
  fireEvent.change(within(dialogo).getByLabelText('Importe'), { target: { value: '2500' } })
  return dialogo
}

const cuenta = (d: HTMLElement) => within(d).getByLabelText('Cuenta del tercero') as HTMLSelectElement
const tercero = (d: HTMLElement) => within(d).getByRole('combobox', { name: 'Tercero' }) as HTMLInputElement

function opcionesDelTercero(d: HTMLElement) {
  fireEvent.click(tercero(d))
  return screen.getAllByRole('option').map((o) => o.textContent)
}

describe('Caja · cuenta primero y alta del tercero en ese rol', () => {
  it('🔑 sin cuenta el tercero está deshabilitado; con la cuenta, se elige entre los de ese rol', async () => {
    const d = await nuevoMovimiento()
    // La cuenta va antes que el tercero en el formulario.
    expect(cuenta(d).compareDocumentPosition(tercero(d)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(cuenta(d).value).toBe('')
    expect(tercero(d)).toBeDisabled()
    expect(within(d).getByRole('button', { name: 'Agregar nuevo tercero' })).toBeDisabled()

    fireEvent.change(cuenta(d), { target: { value: 'fletero' } })
    expect(tercero(d)).not.toBeDisabled()
    const fleteros = opcionesDelTercero(d)
    expect(fleteros.some((t) => t?.includes('Transportes del Sur'))).toBe(true)
    expect(fleteros.some((t) => t?.includes('Agro Norte'))).toBe(false)
    expect(fleteros.some((t) => t?.includes('Ferretería Central'))).toBe(false)
  })

  it('🔑 «Agregar nuevo proveedor» lo da de alta como proveedor, queda elegido y el movimiento se guarda con él', async () => {
    post.mockImplementation((ruta: string, cuerpo: unknown) => ruta === '/api/terceros'
      ? Promise.resolve({ id: 77, razon_social: 'Gomería Ficticia', cuit: '30-71234567-8', es_proveedor: true })
      : Promise.resolve({ ...MOVIMIENTO, id: 9, ...(cuerpo as object) }))
    const d = await nuevoMovimiento()
    fireEvent.change(cuenta(d), { target: { value: 'proveedor' } })

    fireEvent.click(within(d).getByRole('button', { name: 'Agregar nuevo proveedor' }))
    const panel = await within(d).findByRole('group', { name: 'Nuevo proveedor' })
    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Gomería Ficticia' } })
    fireEvent.change(within(panel).getByLabelText('CUIT'), { target: { value: '30-71234567-8' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear proveedor' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros', {
      razon_social: 'Gomería Ficticia', es_proveedor: true, cuit: '30-71234567-8',
    }))
    await waitFor(() => expect(tercero(d)).toHaveValue('Gomería Ficticia'))
    expect(within(d).queryByRole('group', { name: 'Nuevo proveedor' })).toBeNull()

    fireEvent.click(within(d).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/caja', expect.objectContaining({
      tercero_id: 77, rol: 'proveedor', concepto: 'Pago', importe: '2500',
    })))
  })

  it('🔑 si el CUIT ya es de un cliente, ofrece sumarle el rol de fletero y el movimiento va a su cuenta de fletero', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    post.mockImplementation((ruta: string, cuerpo: unknown) => {
      if (ruta === '/api/terceros') {
        return Promise.reject(cuitDuplicado(ApiError as never, { id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] }))
      }
      if (ruta === '/api/terceros/1/roles/fletero') {
        return Promise.resolve({ id: 1, razon_social: 'Agro Norte SA', cuit: '30711111114', es_cliente: true, es_fletero: true })
      }
      return Promise.resolve({ ...MOVIMIENTO, id: 9, ...(cuerpo as object) })
    })
    const d = await nuevoMovimiento()
    fireEvent.change(cuenta(d), { target: { value: 'fletero' } })
    fireEvent.click(within(d).getByRole('button', { name: 'Agregar nuevo fletero' }))
    const panel = await within(d).findByRole('group', { name: 'Nuevo fletero' })
    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Agro Norte SA' } })
    fireEvent.change(within(panel).getByLabelText('CUIT'), { target: { value: '30-71111111-4' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear fletero' }))

    const pregunta = await screen.findByRole('alertdialog')
    expect(pregunta).toHaveTextContent('Sumar el rol de fletero a «Agro Norte SA»')
    fireEvent.click(within(pregunta).getByRole('button', { name: 'Sumar el rol de fletero' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros/1/roles/fletero'))
    expect(post.mock.calls.filter(([r]) => r === '/api/terceros')).toHaveLength(1)
    await waitFor(() => expect(tercero(d)).toHaveValue('Agro Norte SA'))

    fireEvent.click(within(d).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/caja', expect.objectContaining({ tercero_id: 1, rol: 'fletero' })))
  })

  it('si el CUIT ya es de un proveedor activo y la cuenta es de proveedor, se lo elige sin tocarlo', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    post.mockRejectedValue(cuitDuplicado(ApiError as never, { id: 3, razon_social: 'Ferretería Central', roles: ['proveedor'] }))
    const d = await nuevoMovimiento()
    fireEvent.change(cuenta(d), { target: { value: 'proveedor' } })
    fireEvent.click(within(d).getByRole('button', { name: 'Agregar nuevo proveedor' }))
    const panel = await within(d).findByRole('group', { name: 'Nuevo proveedor' })
    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Ferretería Central' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear proveedor' }))

    const pregunta = await screen.findByRole('alertdialog')
    expect(pregunta).toHaveTextContent('«Ferretería Central» ya es proveedor')
    fireEvent.click(within(pregunta).getByRole('button', { name: 'Elegirlo' }))
    await waitFor(() => expect(tercero(d)).toHaveValue('Ferretería Central'))
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('🔑 cambiar la cuenta deja el tercero si tiene el rol nuevo y lo limpia si no', async () => {
    const d = await nuevoMovimiento()
    fireEvent.change(cuenta(d), { target: { value: 'fletero' } })
    fireEvent.click(tercero(d))
    fireEvent.click(screen.getByRole('option', { name: /Transportes del Sur/ }))
    expect(tercero(d)).toHaveValue('Transportes del Sur')

    // También es proveedor: queda.
    fireEvent.change(cuenta(d), { target: { value: 'proveedor' } })
    expect(tercero(d)).toHaveValue('Transportes del Sur')

    // No es cliente: se limpia, y no se puede guardar a la cuenta de cliente de alguien que no lo es.
    fireEvent.change(cuenta(d), { target: { value: 'cliente' } })
    expect(tercero(d)).toHaveValue('Elegir…')   // la opción vacía
    fireEvent.click(within(d).getByRole('button', { name: 'Guardar' }))
    expect(await within(d).findByRole('alert')).toHaveTextContent('Falta el tercero')
    expect(post).not.toHaveBeenCalled()

    // «Ninguna» es un gasto general: tampoco lleva tercero.
    fireEvent.change(cuenta(d), { target: { value: 'fletero' } })
    fireEvent.click(tercero(d))
    fireEvent.click(screen.getByRole('option', { name: /Transportes del Sur/ }))
    fireEvent.change(cuenta(d), { target: { value: '' } })
    expect(tercero(d)).toHaveValue('Ninguno (gasto general)')
    expect(tercero(d)).toBeDisabled()
  })

  it('con cuenta y sin tercero no se guarda: se dice qué falta', async () => {
    const d = await nuevoMovimiento()
    fireEvent.change(cuenta(d), { target: { value: 'cliente' } })
    fireEvent.click(within(d).getByRole('button', { name: 'Guardar' }))
    expect(await within(d).findByRole('alert')).toHaveTextContent('Falta el tercero')
    expect(post).not.toHaveBeenCalled()
  })

  it('sin cuenta es un gasto general: se guarda sin tercero ni rol', async () => {
    post.mockResolvedValue({ ...MOVIMIENTO, id: 9, tercero_id: null })
    const d = await nuevoMovimiento()
    fireEvent.click(within(d).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/caja', expect.objectContaining({ tercero_id: null, rol: null })))
  })

  it('al editar, la cuenta se deduce si el tercero tiene un solo rol', async () => {
    render(<MemoryRouter><Caja /></MemoryRouter>)
    // La grilla muestra el nombre cuando ya llegaron los terceros: sin ellos no hay de dónde deducir la cuenta.
    await screen.findByText('Ferretería Central')
    fireEvent.click(screen.getByLabelText('Editar'))
    const d = await screen.findByRole('dialog')
    expect(cuenta(d).value).toBe('proveedor')
    expect(tercero(d)).toHaveValue('Ferretería Central')
  })
})
