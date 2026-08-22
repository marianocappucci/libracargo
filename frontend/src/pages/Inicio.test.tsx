/** El dashboard: cómo se llama, y que el estado sea una píldora. */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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

const { default: Inicio } = await import('./Inicio')
const { NAV_SECCIONES } = await import('@/components/Layout')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]
const LOCALIDADES = [{ id: 1, nombre: 'Suipacha' }, { id: 2, nombre: 'Mercedes' }]

function orden(id: number, estado: string) {
  return {
    id, fecha: '2026-08-10', cliente_id: 1, origen_id: 1, destino_id: 2,
    fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
    razon_social_id: null, remito: null, cantidad: null, unidad: null,
    tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
    comision: '0.00', estado, comprobante_id: null, observaciones: null,
  }
}

function responder(ordenes: unknown[]) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/reportes/saldos')) return Promise.resolve([])
    if (ruta.startsWith('/api/reportes/resumen')) return Promise.resolve({})
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/localidades')) return Promise.resolve(LOCALIDADES)
    return Promise.resolve([])
  })
}

describe('el dashboard', () => {
  beforeEach(() => { get.mockReset() })

  it('en el menú se llama Dashboard, como en el resto de la familia', () => {
    // Gestiolibra, Contalibra, Restolibra, MedLibra y LibraDesk le dicen
    // 'Dashboard'; este producto era el único que le decía 'Inicio'.
    const items = NAV_SECCIONES.flatMap((s) => s.items)
    const raiz = items.find((i) => i.to === '/')
    expect(raiz?.label).toBe('Dashboard')
    // Y que no haya quedado ningún otro item con la palabra vieja.
    expect(items.map((i) => i.label)).not.toContain('Inicio')
  })

  it('🔑 el estado de las últimas órdenes sale en píldora, no como texto pelado', async () => {
    // Era la única de las siete tablas de la aplicación que lo mostraba en
    // texto. Se afirma `data-slot="badge"` y no el color: el color depende de
    // la variante y lo que el humano pidió es la píldora.
    responder([orden(1, 'pendiente'), orden(2, 'facturada')])
    render(<MemoryRouter><Inicio /></MemoryRouter>)

    const pendiente = await screen.findByText('pendiente')
    expect(pendiente).toHaveAttribute('data-slot', 'badge')
    expect(screen.getByText('facturada')).toHaveAttribute('data-slot', 'badge')
  })

  it('una orden anulada se distingue de una viva', async () => {
    // Se afirma el TONO y no el nombre de la clase de color. La pastilla pasó
    // a `BadgeEstado` de libra-ui, que marca `data-tono` en el DOM justamente
    // para poder auditar esto sin acoplarse a la clase que emite Tailwind:
    // esta línea decía `bg-destructive` y se rompió al cambiar el criterio
    // visual, sin que la orden anulada dejara ni un momento de distinguirse.
    responder([orden(1, 'anulada'), orden(2, 'pendiente')])
    render(<MemoryRouter><Inicio /></MemoryRouter>)

    await waitFor(() => expect(screen.getByText('anulada')).toBeInTheDocument())
    expect(screen.getByText('anulada')).toHaveAttribute('data-tono', 'negativo')
    expect(screen.getByText('pendiente')).not.toHaveAttribute('data-tono', 'negativo')
    // El control de que el `not` de arriba mide algo: la pastilla viva existe
    // y trae tono, o sea que no pasa por ausencia del atributo.
    expect(screen.getByText('pendiente')).toHaveAttribute('data-tono')
  })
})
