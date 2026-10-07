/** «Comprobantes» es una sola entrada del menú con dos pestañas (Clientes y Proveedores).
 *
 *  Se monta la `App` entera con el `Layout` de verdad —no las pantallas sueltas— porque lo que hay que
 *  afirmar es el cruce: el menú, el router, la redirección de `/gastos` y la pestaña que queda en la URL.
 *  Cada pantalla tiene sus propios tests; acá sólo se mira cómo se juntan.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
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
  return {
    ApiError,
    api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() },
  }
})

// Un usuario operador (no admin): las dos pestañas se ven con cualquier rol, y el menú de administración no.
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: { role: 'operador', name: 'Ana' }, loading: false, logout: vi.fn(),
  }),
}))

const { default: App } = await import('./App')
const { NAV_SECCIONES } = await import('@/components/Layout')

const TERCEROS = [
  { id: 1, razon_social: 'Gomería Del Centro', es_cliente: false, es_fletero: false, es_proveedor: true },
  { id: 2, razon_social: 'Fletes SRL', es_cliente: false, es_fletero: true, es_proveedor: false },
]
const GASTO = {
  id: 5, fecha: '2026-08-21', proveedor_id: 1, fletero_id: 2, comprobante: '0001-00000123',
  descripcion: '2 cubiertas', importe: '150000.00', anulado: false,
}
const PRE_FACTURA = {
  id: 7, numero_interno: 'PF-0007', estado: 'pendiente', cliente_id: 1, cliente_razon: 'Agro Norte',
  cliente_cuit: '30-12345678-1', tipo_comprobante: 1,
  fecha_sugerida: '2026-08-20', fecha_vencimiento_pago: null, observaciones: '', orden_ids: [3],
  total: '1210.00', created_at: '2026-08-20 10:15:00', enviado_at: null, enviado_a: null,
  aceptado_at: null, aceptado_por: null, factura_id: null, motivo_descarte: null, resuelto_por: null,
  resuelto_at: null,
  items: [{ description: 'Flete', detalle: 'Orden 3', qty: 1, unit_price: 1000, iva_rate: 0.21, orden_id: 3 }],
}
const COMPROBANTE = {
  comprobante: {
    id: 9, tipo: 'factura_a', punto_venta: 5, numero: 42, fecha: '2026-08-15',
    cliente_id: 1, neto: '1000.00', iva: '210.00', total: '1210.00', anulado: false,
    origen_legado: null, cae: null,
  },
  ordenes: [], suma_de_ordenes: { cantidad: 0, neto: '0.00', iva: '0.00', total: '0.00' }, coinciden: true,
}

const TOTALES_VACIOS = {
  cantidad_comprobantes: 0, neto_comprobantes: '0.00', iva_comprobantes: '0.00', total_comprobantes: '0.00',
  cantidad_ordenes: 0, neto_ordenes: '0.00', iva_ordenes: '0.00', total_ordenes: '0.00', coinciden: true,
}

function responder() {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (/^\/api\/gastos\/\d+/.test(ruta)) return Promise.resolve(GASTO)
    if (ruta.startsWith('/api/gastos')) return Promise.resolve([GASTO])
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/comprobantes/totales')) return Promise.resolve(TOTALES_VACIOS)
    if (ruta === '/api/comprobantes/9') return Promise.resolve(COMPROBANTE)
    if (ruta === '/api/pre-facturas/7') return Promise.resolve(PRE_FACTURA)
    if (ruta.startsWith('/api/pre-facturas')) {
      return Promise.resolve({ items: [PRE_FACTURA], counts: { pendiente: 1 } })
    }
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({ razon_social: 'Suitrans' })
    return Promise.resolve([])
  })
}

function Donde() {
  const { pathname, search } = useLocation()
  return <span data-testid="donde">{pathname + search}</span>
}

function montar(ruta: string) {
  return render(<MemoryRouter initialEntries={[ruta]}><Donde /><App /></MemoryRouter>)
}

/** Todas las entradas del menú lateral, marcadas o no. */
function entradasDelMenu() {
  return Array.from(document.querySelectorAll('[data-sidebar="menu-button"]')).map((e) => e.textContent)
}

/** Las entradas del menú marcadas como activas. */
function activas() {
  return Array.from(document.querySelectorAll('[data-sidebar="menu-button"][data-active="true"]'))
    .map((e) => e.textContent)
}

const donde = () => screen.getByTestId('donde').textContent

beforeEach(() => {
  get.mockReset()
  responder()
  // jsdom no trae `matchMedia`, que el menú lateral pide para saber si es un teléfono.
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
})

describe('el menú', () => {
  it('🔑 tiene una sola entrada «Comprobantes», sin «Pre facturas» ni «Comprobantes de proveedores»', () => {
    const etiquetas = NAV_SECCIONES.flatMap((s) => s.items).map((i) => i.label)
    expect(etiquetas.filter((e) => e === 'Comprobantes')).toHaveLength(1)
    expect(etiquetas).not.toContain('Pre facturas')
    expect(etiquetas).not.toContain('Comprobantes de proveedores')
  })

  it('lo mismo, en el menú dibujado', async () => {
    montar('/comprobantes')
    await screen.findByRole('tab', { name: 'Clientes' })
    const menu = entradasDelMenu()
    expect(menu.filter((e) => e === 'Comprobantes')).toHaveLength(1)
    expect(menu).not.toContain('Pre facturas')
    expect(menu).not.toContain('Comprobantes de proveedores')
    // El acceso a Pre facturas existe, pero es un botón de la pantalla y no una entrada del menú.
    expect(screen.getByText('Pre facturas').closest('[data-sidebar="menu-button"]')).toBeNull()
  })
})

describe('las pestañas', () => {
  it('/comprobantes abre Clientes, con los accesos a Facturar pendientes y a Pre facturas', async () => {
    montar('/comprobantes')
    expect(await screen.findByRole('tab', { name: 'Clientes' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Proveedores' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByText('Facturar pendientes').closest('a'))
      .toHaveAttribute('href', '/comprobantes/facturar')
    expect(screen.getByText('Pre facturas').closest('a')).toHaveAttribute('href', '/pre-facturas')
    expect(activas()).toEqual(['Comprobantes'])
  })

  it('🔑 la pestaña queda en la URL: elegir Proveedores la escribe, y atrás vuelve a Clientes', async () => {
    const { container } = montar('/comprobantes')
    fireEvent.mouseDown(await screen.findByRole('tab', { name: 'Proveedores' }))
    await screen.findByText('2 cubiertas')
    expect(donde()).toBe('/comprobantes?seccion=proveedores')
    expect(screen.getByRole('tab', { name: 'Proveedores' })).toHaveAttribute('aria-selected', 'true')
    // Sólo la pestaña a la vista está montada.
    expect(within(container).queryByText('Facturar pendientes')).toBeNull()

    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Clientes' }))
    await screen.findByText('Facturar pendientes')
    expect(donde()).toBe('/comprobantes')
  })

  it('un enlace guardado a ?seccion=proveedores cae en Proveedores, y uno con basura en Clientes', async () => {
    const primero = montar('/comprobantes?seccion=proveedores')
    expect(await screen.findByRole('tab', { name: 'Proveedores' })).toHaveAttribute('aria-selected', 'true')
    await screen.findByText('2 cubiertas')
    primero.unmount()

    montar('/comprobantes?seccion=cualquiera')
    expect(await screen.findByRole('tab', { name: 'Clientes' })).toHaveAttribute('aria-selected', 'true')
  })

  it('cambiar de pestaña descarta el ?ver= de la otra', async () => {
    montar('/comprobantes?seccion=proveedores&ver=5')
    await screen.findByText('Editar comprobante 5')
    // Radix pone `inert`/aria-hidden al resto mientras hay un diálogo: se cierra para llegar a la pestaña.
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(donde()).toBe('/comprobantes?seccion=proveedores')
  })
})

describe('los enlaces de siempre siguen andando', () => {
  it('🔑 /gastos?ver=5 abre la pestaña Proveedores con el detalle del 5', async () => {
    montar('/gastos?ver=5')
    expect(await screen.findByText('Editar comprobante 5')).toBeInTheDocument()
    // Con el diálogo abierto Radix esconde el resto a los lectores de pantalla: de ahí `hidden`.
    expect(screen.getByRole('tab', { name: 'Proveedores', hidden: true })).toHaveAttribute('aria-selected', 'true')
    expect(donde()).toBe('/comprobantes?seccion=proveedores&ver=5')
    expect(activas()).toEqual(['Comprobantes'])
  })

  it('/gastos a secas abre Proveedores', async () => {
    montar('/gastos')
    await screen.findByText('2 cubiertas')
    expect(donde()).toBe('/comprobantes?seccion=proveedores')
  })

  it('/comprobantes?ver= sigue siendo de Clientes', async () => {
    montar('/comprobantes?ver=9')
    expect(await screen.findByRole('tab', { name: 'Clientes' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('Anular comprobante')).toBeInTheDocument()
  })

  it('🔑 /pre-facturas sigue andando y marca «Comprobantes» en el menú', async () => {
    montar('/pre-facturas')
    expect(await screen.findByText('PF-0007')).toBeInTheDocument()
    expect(donde()).toBe('/pre-facturas')
    expect(activas()).toEqual(['Comprobantes'])
    // Y se vuelve a Comprobantes sin pasar por el menú.
    expect(screen.getByRole('link', { name: 'Volver a Comprobantes' })).toHaveAttribute('href', '/comprobantes')
  })

  it('el detalle y la edición de una pre factura también marcan «Comprobantes»', async () => {
    const detalle = montar('/pre-facturas/7')
    await screen.findByText(/Pre factura PF-0007/)
    expect(donde()).toBe('/pre-facturas/7')
    expect(activas()).toEqual(['Comprobantes'])
    detalle.unmount()

    montar('/pre-facturas/7/editar')
    await screen.findByText(/Editar pre factura/)
    expect(donde()).toBe('/pre-facturas/7/editar')
    expect(activas()).toEqual(['Comprobantes'])
  })

  it('facturar pendientes también cuelga de «Comprobantes»', async () => {
    montar('/comprobantes/facturar')
    await screen.findAllByText('Facturar pendientes')
    expect(activas()).toEqual(['Comprobantes'])
  })

  it('el resto del menú no se corre: en Órdenes sólo está marcada Órdenes de carga', async () => {
    montar('/ordenes')
    await screen.findAllByText('Órdenes de carga')
    expect(activas()).toEqual(['Órdenes de carga'])
  })

  it('el botón Pre facturas de Clientes lleva a la lista', async () => {
    montar('/comprobantes')
    fireEvent.click(await screen.findByText('Pre facturas'))
    expect(await screen.findByText('PF-0007')).toBeInTheDocument()
    expect(donde()).toBe('/pre-facturas')
  })
})
