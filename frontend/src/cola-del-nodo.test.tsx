/** La cola de comprobantes del nodo en LibraCargo (ADR-056 del backend, libra-ui ADR-094): el cartel «sin conexión», la entrada
 *  «Cola de comprobantes» del menú y la ruta `/cola`.
 *
 *  🔑 Todo lo que depende de ser un nodo lo dice `GET /api/nodo/cola` (que LibraCargo sí monta): `/api/nodo/conexion` es del motor de ventas y
 *  acá no existe. Fuera de un nodo no cambia nada visible: ni cartel, ni entrada de menú.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    detailData?: unknown
    constructor(status: number, detail: unknown, detailData?: unknown) {
      super(String(detail)); this.status = status; this.detail = detail; this.detailData = detailData
    }
  }
  return { ApiError, api: { get, post, put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

let rol = 'admin'
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: rol, name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: App } = await import('./App')
const { NAV_SECCIONES, RUTA_DE_LA_CONEXION } = await import('@/components/Layout')
const { _reiniciarConexionDelNodo, TEXTO_CARTEL_SIN_CONEXION_CON_COLA } = await import('libra-ui/nodo-offline')

const pedidoDeCpe = (extra: Record<string, unknown> = {}) => ({
  id: 5, origen_producto: 'libracargo', origen_instancia: 'oficina', origen_tipo: 'cpe', origen_id: 'orden41:3f1c9a',
  estado: 'esperando', datos: { orden_id: 41, solicitud: {}, confirmo: true }, fecha_ref: '', concepto: 1, intentos: 0,
  ultimo_error: '', resultado: null, revision: 1, created_at: '2026-10-24T10:00:00', updated_at: '2026-10-24T10:00:00',
  resuelto_at: '', ...extra,
})
const pedidoDeFactura = (extra: Record<string, unknown> = {}) => ({
  ...pedidoDeCpe(), id: 6, origen_tipo: 'documento', origen_id: 'ordenes:77aa',
  datos: { clase: 'ordenes', cliente_id: 1, orden_ids: [41, 42, 43], tipo: 'factura_a' }, ...extra,
})

const NODO_SIN_CONEXION = (pedidos: unknown[] = []) => ({
  es_nodo: true, en_linea: false, node_id: 'oficina', cuentas: { esperando: pedidos.length }, a_revisar: 0, pedidos,
})
const NODO_CON_CONEXION = (pedidos: unknown[] = []) => ({ ...NODO_SIN_CONEXION(pedidos), en_linea: true })
const FUERA_DE_UN_NODO = { es_nodo: false, en_linea: true, node_id: null, cuentas: {}, a_revisar: 0, pedidos: [] }

function responder(cola: unknown) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/nodo/cola')) return Promise.resolve(cola)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve([{ id: 1, razon_social: 'Agro Norte', es_cliente: true }])
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({ razon_social: 'Suitrans' })
    return Promise.resolve([])
  })
}

const montar = (ruta: string) => render(<MemoryRouter initialEntries={[ruta]}><App /></MemoryRouter>)
const entradasDelMenu = () => Array.from(document.querySelectorAll('[data-sidebar="menu-button"]')).map((e) => e.textContent)

beforeEach(() => {
  get.mockReset(); post.mockReset()
  rol = 'admin'
  _reiniciarConexionDelNodo()
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
})

describe('el cartel «sin conexión» del layout', () => {
  it('🔴 en un nodo sin internet dice que las facturas y las cartas de porte quedan en cola y que no hay CPE válida para viajar', async () => {
    responder(NODO_SIN_CONEXION())
    montar('/')
    const cartel = await waitFor(() => {
      const c = document.querySelector('[data-slot="cartel-sin-conexion"]')
      expect(c).not.toBeNull()
      return c as HTMLElement
    })
    expect(cartel).toHaveTextContent(TEXTO_CARTEL_SIN_CONEXION_CON_COLA)
    expect(cartel).toHaveTextContent('Hasta entonces no hay CPE válida para viajar.')
    // No es el cartel de las ventas de mostrador: acá no se cobra con ticket.
    expect(cartel).not.toHaveTextContent('ticket')
  })

  it('pregunta a la cola del motor (`/api/nodo/cola?limite=1`) y no a `/api/nodo/conexion`, que LibraCargo no monta', async () => {
    responder(NODO_SIN_CONEXION())
    montar('/')
    await waitFor(() => expect(get).toHaveBeenCalledWith(RUTA_DE_LA_CONEXION))
    expect(RUTA_DE_LA_CONEXION).toBe('/api/nodo/cola?limite=1')
    expect(get.mock.calls.map((c) => String(c[0]))).not.toContain('/api/nodo/conexion')
  })

  it('con conexión, o fuera de un nodo, no hay cartel', async () => {
    responder(NODO_CON_CONEXION())
    const { unmount } = montar('/')
    await waitFor(() => expect(get).toHaveBeenCalledWith(RUTA_DE_LA_CONEXION))
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(document.querySelector('[data-slot="cartel-sin-conexion"]')).toBeNull()
    unmount()

    _reiniciarConexionDelNodo()
    responder(FUERA_DE_UN_NODO)
    montar('/')
    await waitFor(() => expect(get).toHaveBeenCalledWith(RUTA_DE_LA_CONEXION))
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(document.querySelector('[data-slot="cartel-sin-conexion"]')).toBeNull()
  })
})

describe('la entrada «Cola de comprobantes» del menú', () => {
  it('está declarada, con la ruta /cola, y se oculta cuando el equipo no es un nodo', () => {
    const entrada = NAV_SECCIONES.flatMap((s) => s.items).find((i) => i.to === '/cola')
    expect(entrada).toBeDefined()
    expect(entrada!.label).toBe('Cola de comprobantes')
    expect(entrada!.hideFor?.({ role: 'admin', esNodo: false })).toBe(true)
    expect(entrada!.hideFor?.({ role: 'admin' })).toBe(true)
    expect(entrada!.hideFor?.({ role: 'admin', esNodo: true })).toBe(false)
  })

  it('🔴 en un nodo aparece (con conexión o sin ella), para cualquier rol', async () => {
    rol = 'operador'
    responder(NODO_CON_CONEXION())
    montar('/')
    await waitFor(() => expect(entradasDelMenu()).toContain('Cola de comprobantes'))
  })

  it('🔴 fuera de un nodo el menú queda como siempre: no hay entrada', async () => {
    responder(FUERA_DE_UN_NODO)
    montar('/')
    await waitFor(() => expect(entradasDelMenu()).toContain('Comprobantes'))
    await waitFor(() => expect(get).toHaveBeenCalledWith(RUTA_DE_LA_CONEXION))
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(entradasDelMenu()).not.toContain('Cola de comprobantes')
  })
})

describe('la ruta /cola', () => {
  it('🔴 muestra la bandeja de la cola con cada pedido descripto con lo de LibraCargo: la orden de la carta de porte y el cliente de la factura', async () => {
    responder(NODO_SIN_CONEXION([pedidoDeCpe(), pedidoDeFactura()]))
    montar('/cola')
    expect(await screen.findByRole('heading', { name: 'Cola de comprobantes' })).toBeInTheDocument()
    // El `origen_id` es `orden41:<uuid>`; el título sale de `datos.orden_id` y no se lee «orden41».
    expect(await screen.findByText('Carta de porte · Orden 41')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Factura · Agro Norte · 3 órdenes')).toBeInTheDocument())
    expect(screen.getAllByText('En cola')).not.toHaveLength(0)
  })

  it('un administrador puede descartar; un operador mira la cola pero no resuelve', async () => {
    responder(NODO_SIN_CONEXION([pedidoDeCpe()]))
    const admin = montar('/cola')
    expect(await screen.findByRole('button', { name: /Descartar/ })).toBeInTheDocument()
    admin.unmount()

    rol = 'operador'
    montar('/cola')
    expect(await screen.findByText('Carta de porte · Orden 41')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Descartar/ })).toBeNull()
  })

  it('🔴 un `incierto` no se reintenta sin confirmar que NO salió en ARCA', async () => {
    responder(NODO_CON_CONEXION([pedidoDeCpe({ estado: 'incierto', ultimo_error: 'ARCA no contestó' })]))
    post.mockResolvedValue({})
    montar('/cola')
    fireEvent.click(await screen.findByRole('button', { name: /Reintentar/ }))
    expect(await screen.findByText('¿Confirmás que este comprobante NO salió en ARCA?')).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('fuera de un nodo dice que la instalación no es un nodo', async () => {
    responder(FUERA_DE_UN_NODO)
    montar('/cola')
    const pantalla = await screen.findByRole('heading', { name: 'Cola de comprobantes' })
    expect(await within(pantalla.closest('div')!.parentElement!).findByText(/no es un nodo/)).toBeInTheDocument()
  })
})
