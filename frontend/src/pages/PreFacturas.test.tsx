import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

const { default: PreFacturas } = await import('./PreFacturas')

function pf(id: number, estado: string, extra: Record<string, unknown> = {}) {
  return {
    id, numero_interno: `PF-000${id}`, estado, cliente_id: 1, cliente_razon: 'Agro Norte',
    cliente_cuit: '30-12345678-1', razon_social_id: 5, razon_social: 'Suitrans',
    tipo_comprobante: 1, fecha_sugerida: '2026-08-20', fecha_vencimiento_pago: null,
    observaciones: '', items: [], orden_ids: [id], total: '1210.00', ...extra,
  }
}

const CONTEOS = { pendiente: 1, enviado: 1, aceptado: 1, facturado: 1, descartado: 1 }

function responder(items: unknown[] = []) {
  get.mockResolvedValue({ items, counts: CONTEOS })
}

function abrir() {
  render(
    <MemoryRouter initialEntries={['/pre-facturas']}>
      <Routes>
        <Route path="/pre-facturas" element={<PreFacturas />} />
        <Route path="/pre-facturas/:id" element={<p>Pantalla de la pre factura</p>} />
        <Route path="/comprobantes/facturar" element={<p>Pantalla de facturar pendientes</p>} />
      </Routes>
    </MemoryRouter>)
}

describe('Pre facturas', () => {
  beforeEach(() => { get.mockReset() })

  it('lista cada una con su número, cliente, comprobante, total y estado en castellano', async () => {
    responder([pf(1, 'pendiente'), pf(2, 'enviado'), pf(3, 'aceptado'), pf(4, 'facturado'),
               pf(5, 'descartado')])
    abrir()

    expect(await screen.findByText('PF-0001')).toBeInTheDocument()
    for (const estado of ['Pendiente', 'Enviada', 'Aceptada', 'Facturada', 'Anulada']) {
      // Una vez en la pastilla de la fila (y otra en la opción del filtro).
      expect(screen.getAllByText(estado).length).toBeGreaterThanOrEqual(1)
    }
    expect(screen.getAllByText('Agro Norte')).toHaveLength(5)
    expect(screen.getAllByText('Factura A')).toHaveLength(5)
    expect(screen.getAllByText('$ 1.210,00')).toHaveLength(5)
    expect(screen.getAllByText('20-08-2026').length).toBeGreaterThan(0)
  })

  it('el filtro de estado muestra cuántas hay de cada uno y pide sólo ese estado', async () => {
    responder([pf(1, 'aceptado')])
    abrir()
    await screen.findByText('PF-0001')

    const filtro = screen.getByLabelText('Estado')
    expect(screen.getByRole('option', { name: 'Enviada (1)' })).toBeInTheDocument()
    fireEvent.change(filtro, { target: { value: 'aceptado' } })

    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/pre-facturas?estado=aceptado'))
  })

  it('el filtro de cliente espera un respiro y busca por razón social o CUIT', async () => {
    responder([pf(1, 'pendiente')])
    abrir()
    await screen.findByText('PF-0001')
    get.mockClear()

    fireEvent.change(screen.getByLabelText('Cliente'), { target: { value: 'Agro' } })
    expect(get).not.toHaveBeenCalled()
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/pre-facturas?cliente=Agro'),
                  { timeout: 2000 })
  })

  it('hacer click en una fila lleva a la pre factura', async () => {
    responder([pf(3, 'pendiente')])
    abrir()
    fireEvent.click(await screen.findByText('PF-0003'))
    expect(await screen.findByText('Pantalla de la pre factura')).toBeInTheDocument()
  })

  it('sin pre facturas lo dice, y el botón lleva a generar una', async () => {
    responder([])
    abrir()
    expect(await screen.findByText('Todavía no hay pre facturas.')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Generar pre factura'))
    expect(await screen.findByText('Pantalla de facturar pendientes')).toBeInTheDocument()
  })

  it('si el servidor falla, muestra el motivo', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    get.mockRejectedValue(new ApiError(500, 'se cayó'))
    abrir()
    expect(await screen.findByRole('alert')).toHaveTextContent('se cayó')
  })
})
