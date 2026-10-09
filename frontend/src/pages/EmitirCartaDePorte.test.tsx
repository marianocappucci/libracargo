/** «Emitir carta de porte» en su propia página (2026-10-09): trae la orden por la URL, vuelve a ella, y no emite una
 *  anulada. Lo del asistente (titular, datos, confirmar, envío único) está en `components/EmitirCartaDePorte.test.tsx`. */
import { configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { opcionesDe } from '@/test/buscable'

configure({ asyncUtilTimeout: 5000 })

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { default: EmitirCartaDePortePagina } = await import('./EmitirCartaDePorte')
const { ApiError } = await import('libra-ui/api-client')

const TITULARES = {
  ambiente: 'produccion', verificado: true, motivo: null, cuit_para_catalogos: '30222222223',
  titulares: [{
    id: 1, cuit: '30222222223', razon_social: 'Agropecuaria Los Talas', emite: 'nosotros', activo: true,
    notas: null, delegacion: 'delegado', tercero: null, tiene_plantilla: false,
  }],
  sin_cargar: [],
}

function responder(orden: Record<string, unknown> | Error) {
  get.mockImplementation((ruta: string) => {
    if (ruta.startsWith('/api/ordenes/')) return orden instanceof Error ? Promise.reject(orden) : Promise.resolve(orden)
    if (ruta === '/api/cartas-porte/emision/estado') {
      return Promise.resolve({ ambiente: 'produccion', habilitada: true, puede_emitir: true })
    }
    if (ruta === '/api/cartas-porte/titulares') return Promise.resolve(TITULARES)
    return Promise.reject(new Error(`ruta inesperada: ${ruta}`))
  })
}

function Donde() {
  const { pathname, search } = useLocation()
  return <p data-testid="donde">{pathname + search}</p>
}

function abrir(ruta: string) {
  render(
    <MemoryRouter initialEntries={[ruta]}>
      <Routes>
        <Route path="/cartas-porte/emitir/:ordenId" element={<EmitirCartaDePortePagina />} />
        <Route path="*" element={null} />
      </Routes>
      <Donde />
    </MemoryRouter>)
}

beforeEach(() => { get.mockReset() })

describe('Emitir carta de porte · la página', () => {
  it('trae la orden de la URL y arranca el asistente con el titular sin elegir', async () => {
    responder({ id: 7, estado: 'pendiente' })
    abrir('/cartas-porte/emitir/7')
    expect(await screen.findByRole('heading', { name: 'Emitir carta de porte · Orden Nº 00000007' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/ordenes/7')
    const titular = await screen.findByLabelText('A nombre de')
    await waitFor(() => expect(opcionesDe(titular)).toContain('Agropecuaria Los Talas'))
    expect(titular).toHaveValue('Elegir…')
    // No es un diálogo: no hay nada que se cierre con Escape ni tocando afuera.
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('«Cancelar» vuelve a la orden, con su detalle abierto', async () => {
    responder({ id: 7, estado: 'pendiente' })
    abrir('/cartas-porte/emitir/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Cancelar' }))
    expect(screen.getByTestId('donde')).toHaveTextContent('/ordenes?ver=7')
  })

  it('una orden anulada no se emite, aunque se llegue por un enlace', async () => {
    responder({ id: 8, estado: 'anulada' })
    abrir('/cartas-porte/emitir/8')
    expect(await screen.findByRole('alert')).toHaveTextContent('La orden está anulada')
    expect(screen.queryByLabelText('A nombre de')).toBeNull()
    expect(get).not.toHaveBeenCalledWith('/api/cartas-porte/titulares')
    expect(screen.getByRole('link', { name: 'Volver a la orden' })).toHaveAttribute('href', '/ordenes?ver=8')
  })

  it('una orden que no existe lo dice con el texto del servidor', async () => {
    responder(new (ApiError as unknown as new (s: number, d: string) => Error)(404, 'Orden no encontrada'))
    abrir('/cartas-porte/emitir/99')
    expect(await screen.findByRole('alert')).toHaveTextContent('Orden no encontrada')
  })

  it('un número que no es de orden no sale a buscarla', async () => {
    responder({ id: 7, estado: 'pendiente' })
    abrir('/cartas-porte/emitir/abc')
    expect(await screen.findByRole('alert')).toHaveTextContent('no tiene un número de orden válido')
    expect(get).not.toHaveBeenCalled()
  })
})
