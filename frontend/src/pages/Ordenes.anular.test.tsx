/** «Anular» una orden pide confirmación (decisión del humano, 2026-10-14).
 *
 * Anular no se deshace —la orden queda `anulada` y no se modifica más— y revierte el cargo de la cuenta del fletero, así
 * que un clic suelto en el ícono no puede bastar. Lo que se prueba: sin confirmar no sale ningún `DELETE`, «No» y
 * Escape no anulan, «Sí» manda uno solo (un doble clic no manda dos) y el error del servidor llega a la pantalla.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

configure({ asyncUtilTimeout: 5000 })

const get = vi.fn()
const put = vi.fn()
const del = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put, del, postForm: vi.fn() } }
})

const { default: Ordenes } = await import('./Ordenes')

const orden = (id: number, extra: Record<string, unknown> = {}) => ({
  id, fecha: '2026-10-05', cliente_id: 1, origen_id: 1, destino_id: 2,
  fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
  remito: `R-${id}`, cantidad: null, unidad: null,
  tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
  comision: '0.00', estado: 'pendiente', comprobante_id: null,
  observaciones: null, cantidad_legado: null, origen_legado: null,
  etapa: 'asignada',
  kg_bruto_carga: null, kg_tara_carga: null, kg_neto_carga: null,
  kg_bruto_descarga: null, kg_tara_descarga: null, kg_neto_descarga: null,
  km: null, tarifa_tonelada: null,
  ...extra,
})

async function error(status: number, detail: string) {
  const { ApiError } = await import('libra-ui/api-client')
  return new (ApiError as unknown as new (s: number, d: string) => Error)(status, detail)
}

function responder(ordenes: unknown[]) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) {
      return Promise.resolve([{ id: 1, razon_social: 'Agro Norte', es_cliente: true }])
    }
    if (ruta.startsWith('/api/localidades')) {
      return Promise.resolve([{ id: 1, nombre: 'Suipacha' }, { id: 2, nombre: 'Rosario' }])
    }
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({})
    return Promise.resolve([])
  })
}

/** Cuántas veces se pidió el listado de órdenes (la carga inicial más cada recarga). */
const listados = () => get.mock.calls.filter(([r]) => r === '/api/ordenes' || String(r).startsWith('/api/ordenes?')).length

/** Abre la pantalla y toca «Anular» de la fila de esa orden. */
async function tocarAnular(remito: string) {
  render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
  const fila = (await screen.findByText(remito)).closest('tr') as HTMLElement
  fireEvent.click(within(fila).getByRole('button', { name: 'Anular' }))
}

beforeEach(() => {
  get.mockReset(); put.mockReset(); del.mockReset()
  responder([orden(7)])
})

describe('Órdenes · anular pide confirmación', () => {
  it('al tocar «Anular» no se llama a la API: aparece el diálogo con el número y el cliente', async () => {
    await tocarAnular('R-7')

    const dialogo = await screen.findByRole('alertdialog')
    expect(within(dialogo).getByText('¿Anular la orden Nº 00000007?')).toBeInTheDocument()
    expect(within(dialogo).getByText(/Cliente: Agro Norte\./)).toBeInTheDocument()
    // Qué pasa, dicho sin vueltas: no se borra, mueve la cuenta del fletero y no vuelve atrás.
    expect(within(dialogo).getByText(/no se borra/)).toBeInTheDocument()
    expect(within(dialogo).getByText(/contraasiento/)).toBeInTheDocument()
    expect(within(dialogo).getByText(/no se puede deshacer/)).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Sí, anular la orden' })).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'No' })).toBeInTheDocument()
    expect(del).not.toHaveBeenCalled()
  })

  it('«No» cierra sin anular', async () => {
    await tocarAnular('R-7')
    const dialogo = await screen.findByRole('alertdialog')

    fireEvent.click(within(dialogo).getByRole('button', { name: 'No' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(del).not.toHaveBeenCalled()
  })

  it('Escape cierra sin anular', async () => {
    await tocarAnular('R-7')
    const dialogo = await screen.findByRole('alertdialog')

    fireEvent.keyDown(dialogo, { key: 'Escape' })

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(del).not.toHaveBeenCalled()
  })

  it('el foco queda en «No»: Enter sin pensar no anula', async () => {
    await tocarAnular('R-7')
    const dialogo = await screen.findByRole('alertdialog')

    await waitFor(() => expect(within(dialogo).getByRole('button', { name: 'No' })).toHaveFocus())
  })

  it('«Sí, anular la orden» llama una sola vez a DELETE /api/ordenes/{id} y recarga', async () => {
    del.mockResolvedValue(orden(7, { estado: 'anulada' }))
    await tocarAnular('R-7')
    const antes = listados()
    const dialogo = await screen.findByRole('alertdialog')

    fireEvent.click(within(dialogo).getByRole('button', { name: 'Sí, anular la orden' }))

    await waitFor(() => expect(del).toHaveBeenCalledTimes(1))
    expect(del).toHaveBeenCalledWith('/api/ordenes/7')
    await waitFor(() => expect(listados()).toBe(antes + 1))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  })

  it('mientras anula los botones quedan deshabilitados: un segundo clic no manda otro pedido', async () => {
    let terminar!: (o: unknown) => void
    del.mockImplementation(() => new Promise((r) => { terminar = r }))
    await tocarAnular('R-7')
    const dialogo = await screen.findByRole('alertdialog')
    const si = within(dialogo).getByRole('button', { name: 'Sí, anular la orden' })

    fireEvent.click(si)
    await waitFor(() => expect(si).toBeDisabled())
    expect(within(dialogo).getByRole('button', { name: 'No' })).toBeDisabled()
    fireEvent.click(si)
    // Escape tampoco lo cierra a mitad de camino.
    fireEvent.keyDown(dialogo, { key: 'Escape' })
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(del).toHaveBeenCalledTimes(1)

    terminar(orden(7, { estado: 'anulada' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(del).toHaveBeenCalledTimes(1)
  })

  it('un 409 del servidor se muestra en la pantalla y el diálogo se cierra', async () => {
    del.mockRejectedValue(await error(409, 'la orden esta facturada: primero hay que anular el comprobante'))
    await tocarAnular('R-7')
    const dialogo = await screen.findByRole('alertdialog')

    fireEvent.click(within(dialogo).getByRole('button', { name: 'Sí, anular la orden' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('la orden esta facturada: primero hay que anular el comprobante')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(del).toHaveBeenCalledTimes(1)
  })

  it('una orden facturada avisa en el diálogo que el servidor no la anula', async () => {
    responder([orden(8, { estado: 'facturada', comprobante_id: 3 })])
    await tocarAnular('R-8')

    const dialogo = await screen.findByRole('alertdialog')
    expect(within(dialogo).getByText(/primero hay que anular el comprobante/)).toBeInTheDocument()
    expect(del).not.toHaveBeenCalled()
  })

  it('una orden anulada no se puede anular otra vez: el botón está deshabilitado', async () => {
    responder([orden(9, { estado: 'anulada' })])
    render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
    const fila = (await screen.findByText('R-9')).closest('tr') as HTMLElement

    const boton = within(fila).getByRole('button', { name: 'Anular' })
    expect(boton).toBeDisabled()
    fireEvent.click(boton)
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(del).not.toHaveBeenCalled()
  })
})
