import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

function orden(id: number, extra: Record<string, unknown> = {}) {
  return {
    id, fecha: '2026-08-10', cliente_id: 1, origen_id: 1, destino_id: 2,
    fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
    razon_social_id: null, remito: null, cantidad: null, unidad: null,
    tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
    comision: '0.00', estado: 'pendiente', comprobante_id: null,
    observaciones: null, ...extra,
  }
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
  it('el boton de facturar lleva a la pantalla, no abre un modal', async () => {
    responder({})
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    const boton = await screen.findByText('Facturar pendientes')
    expect(boton.closest('a')).toHaveAttribute('href', '/comprobantes/facturar')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
