import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
  return { ApiError, api: { get, post, put: vi.fn(), del: vi.fn() } }
})

const { default: Comprobantes } = await import('./Comprobantes')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]
const RAZONES = [
  { id: 5, nombre: 'Suitrans' },
  { id: 6, nombre: 'Mauricio' },
]

type Respuestas = {
  totales?: unknown[]
  comprobantes?: unknown[]
  ordenes?: unknown[]
}

function responder({ totales = [], comprobantes = [], ordenes = [] }: Respuestas) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    // `/totales` primero: `/api/comprobantes` es prefijo suyo, y al reves esta
    // ruta contestaria la lista y el panel del gate quedaria siempre vacio.
    if (ruta.startsWith('/api/comprobantes/totales')) return Promise.resolve(totales)
    if (ruta.startsWith('/api/comprobantes')) return Promise.resolve(comprobantes)
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/razones-sociales')) return Promise.resolve(RAZONES)
    return Promise.resolve([])
  })
}

function total(extra: Record<string, unknown> = {}) {
  return {
    razon_social_id: 5, cantidad_comprobantes: 1,
    neto_comprobantes: '1000.00', iva_comprobantes: '210.00',
    total_comprobantes: '1210.00',
    cantidad_ordenes: 1, neto_ordenes: '1000.00', iva_ordenes: '210.00',
    total_ordenes: '1210.00', coinciden: true, ...extra,
  }
}

/** El detalle de un comprobante, como lo devuelve `GET /api/comprobantes/9`. */
function detalleDe(cae: string | null, tipo = 'factura_a', extra: Record<string, unknown> = {}) {
  return {
    comprobante: {
      id: 9, razon_social_id: 5, tipo, punto_venta: 5, numero: 42,
      fecha: '2026-08-15', cliente_id: 1, neto: '1000.00', iva: '210.00', total: '1210.00',
      anulado: false, origen_legado: null, cae,
    },
    ordenes: [],
    suma_de_ordenes: { cantidad: 0, neto: '0.00', iva: '0.00', total: '0.00' },
    coinciden: true,
    ...extra,
  }
}

function abrirDetalle(cae: string | null, tipo = 'factura_a', extra: Record<string, unknown> = {}) {
  responder({})
  const base = get.getMockImplementation()!
  get.mockImplementation((ruta?: string) =>
    ruta === '/api/comprobantes/9' ? Promise.resolve(detalleDe(cae, tipo, extra)) : base(ruta))
  render(<MemoryRouter initialEntries={['/comprobantes?ver=9']}><Comprobantes /></MemoryRouter>)
}

describe('Comprobantes', () => {
  beforeEach(() => { get.mockReset(); post.mockReset() })

  it('🔴 avisa cuando los dos lados de una razón social NO coinciden', async () => {
    // Es la razon de que el endpoint devuelva los dos totales. Mostrar solo uno
    // haria que un total divergente se viera igual de confiable que uno sano.
    responder({ totales: [total({ total_ordenes: '0.00', cantidad_ordenes: 0, coinciden: false })] })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toContain('NO')
    // Los dos numeros a la vista, no solo el de los comprobantes.
    expect(screen.getByText('1210.00')).toBeInTheDocument()
    expect(screen.getByText('0.00')).toBeInTheDocument()
  })

  it('con los dos totales iguales no aparece ninguna alarma', async () => {
    // El control del test de arriba: sin este, una pantalla que gritara SIEMPRE
    // pasaria igual y la alarma dejaria de significar algo.
    responder({ totales: [total()] })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)

    await waitFor(() => expect(screen.getAllByText('1210.00').length).toBe(2))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  // Los tests de facturar viven en `FacturarPendientes.test.tsx`: el flujo
  // dejo de ser un modal de esta pantalla y paso a ser una pantalla propia.
  // 🔴 Un comprobante con CAE no se anula desde acá: anular no llega a ARCA y el
  // comprobante seguiría vigente allá mientras sus órdenes se podrían facturar de nuevo.
  it('un comprobante con CAE no ofrece anular y dice por qué', async () => {
    abrirDetalle('75123456789012')

    const nota = await screen.findByRole('note')
    expect(nota).toHaveTextContent('75123456789012')
    expect(nota).toHaveTextContent('no se anula desde acá')
    expect(screen.queryByText('Anular comprobante')).toBeNull()
    expect(nota).toHaveTextContent('emití una nota de crédito')
  })

  // La nota de crédito sale de ARCA (motor) y es la forma de revertir lo que tiene CAE.
  it('una factura con CAE ofrece la nota de crédito, que pide un motivo y se confirma aparte', async () => {
    abrirDetalle('75123456789012')
    post.mockResolvedValue({ id: 10, tipo: 'nota_credito_a' })

    fireEvent.click(await screen.findByText('Emitir nota de crédito'))
    const confirmar = await screen.findByText('Confirmar nota de crédito')
    expect(confirmar).toBeDisabled() // sin motivo no se puede
    fireEvent.change(screen.getByLabelText('Motivo de la nota de crédito'),
      { target: { value: 'Error de tarifa' } })
    expect(confirmar).toBeEnabled()
    fireEvent.click(confirmar)

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/nota-de-credito', { motivo: 'Error de tarifa' }))
    // Sin importe, fecha ni tipo: los decide el servidor.
    expect(Object.keys(post.mock.calls[0][1])).toEqual(['motivo'])
  })

  it('contra homologación avisa que fue un ensayo y no se guardó nada', async () => {
    abrirDetalle('75123456789012')
    post.mockResolvedValue({ ensayo: true, ambiente: 'homologacion', cae: '99', tipo: 'nota_credito_a' })

    fireEvent.click(await screen.findByText('Emitir nota de crédito'))
    fireEvent.change(await screen.findByLabelText('Motivo de la nota de crédito'),
      { target: { value: 'Prueba' } })
    fireEvent.click(screen.getByText('Confirmar nota de crédito'))

    expect(await screen.findByRole('status')).toHaveTextContent('no se guardó nada')
  })

  // ── La nota parcial (ADR-028): el servidor manda lo acreditado y el saldo ──
  const SIN_NOTAS = { notas: [], acreditado: '0.00', saldo_acreditable: '1210.00' }

  function abrirNota(motivo = 'Diferencia de kilos') {
    return screen.findByText('Emitir nota de crédito').then((b) => {
      fireEvent.click(b)
      fireEvent.change(screen.getByLabelText('Motivo de la nota de crédito'), { target: { value: motivo } })
    })
  }

  it('con el saldo a la vista, la nota puede ser por un importe, que viaja como texto', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    post.mockResolvedValue({ id: 10, tipo: 'nota_credito_a' })
    await abrirNota()

    fireEvent.click(screen.getByLabelText('Por un importe'))
    fireEvent.change(screen.getByLabelText('Importe a acreditar (con IVA)'), { target: { value: '121,5' } })
    fireEvent.click(screen.getByText('Confirmar nota de crédito'))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/nota-de-credito', { motivo: 'Diferencia de kilos', importe: '121.50' }))
  })

  it('no deja confirmar un importe de más ni uno con tres decimales', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    await abrirNota()
    fireEvent.click(screen.getByLabelText('Por un importe'))
    const importe = screen.getByLabelText('Importe a acreditar (con IVA)')
    const confirmar = screen.getByText('Confirmar nota de crédito')

    fireEvent.change(importe, { target: { value: '1210.01' } })
    expect(confirmar).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Supera lo que queda por acreditar')
    fireEvent.change(importe, { target: { value: '1.234' } })
    expect(confirmar).toBeDisabled()
    fireEvent.change(importe, { target: { value: '1210' } })
    expect(confirmar).toBeEnabled()
  })

  it('con notas previas no ofrece la total, propone el saldo y las lista', async () => {
    abrirDetalle('75123456789012', 'factura_a', {
      notas: [{ id: 11, tipo: 'nota_credito_a', punto_venta: 5, numero: 43, fecha: '2026-10-05',
                total: '121.00', motivo: 'Kilos', anulado: false }],
      acreditado: '121.00', saldo_acreditable: '1089.00',
    })
    expect(await screen.findByText(/Nota de crédito A 0005-00000043/)).toBeInTheDocument()
    expect(screen.getByText(/queda por/)).toHaveTextContent('1.089,00')
    await abrirNota()

    expect(screen.getByLabelText('Por el total')).toBeDisabled()
    expect(screen.getByLabelText('Importe a acreditar (con IVA)')).toHaveValue('1089.00')
  })

  it('una FCE con CAE ofrece sólo la nota por un importe menor que el saldo', async () => {
    abrirDetalle('75123456789012', 'fce_a', SIN_NOTAS)
    expect(await screen.findByRole('note')).toHaveTextContent('menos que su saldo')
    await abrirNota()

    expect(screen.getByLabelText('Por el total')).toBeDisabled()
    const importe = screen.getByLabelText('Importe a acreditar (con IVA)')
    fireEvent.change(importe, { target: { value: '1210.00' } })
    expect(screen.getByText('Confirmar nota de crédito')).toBeDisabled()
    fireEvent.change(importe, { target: { value: '1209.99' } })
    expect(screen.getByText('Confirmar nota de crédito')).toBeEnabled()
  })

  it('el comprobante sin CAE (registrado a mano o migrado) se sigue pudiendo anular', async () => {
    abrirDetalle(null)

    expect(await screen.findByText('Anular comprobante')).toBeInTheDocument()
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('el boton de facturar lleva a la pantalla, no abre un modal', async () => {
    responder({})
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    const boton = await screen.findByText('Facturar pendientes')
    expect(boton.closest('a')).toHaveAttribute('href', '/comprobantes/facturar')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
