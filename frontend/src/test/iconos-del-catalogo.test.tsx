/** El menú y los títulos de LibraCargo usan el catálogo de íconos de identidad de la familia (`libra-ui/iconos-identidad`, ADR-035).
 *
 *  🔑 **LibraCargo es el único producto con una excepción** (`ICONOS_POR_PRODUCTO.libracargo`, decisión del humano del 2026-10-07): el camión
 *  (`Truck`) es de los fleteros y Proveedores lleva `Store`. Todo lo de este producto toma el ícono de `iconosDe('libracargo')` (`@/iconos`) y
 *  nunca de `ICONOS.proveedores`, que es `Truck` en el resto de la familia.
 *
 *  Las dos mitades: los FUENTES (el `Layout` no se rinde en cada pantalla y lo que hay que impedir es que vuelva a divergir) y el DOM (que
 *  las pestañas de Comprobantes y de Cuenta corriente dibujen de verdad `Store` y `Truck`).
 */
import { render, screen, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { MemoryRouter } from 'react-router-dom'
import * as lucide from 'lucide-react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { auditarMenuContraCatalogo, iconoDelTitulo, iconosDelNav } from 'libra-ui/auditoria-de-titulos'
import { ICONOS, iconoDelConcepto, iconosDe, type Concepto } from 'libra-ui/iconos-identidad'

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
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: { role: 'operador', name: 'Ana' }, loading: false, logout: vi.fn(),
  }),
}))

const { default: App } = await import('@/App')
const { default: CuentaCorriente } = await import('@/pages/CuentaCorriente')
const { NAV_SECCIONES } = await import('@/components/Layout')

const SRC = join(process.cwd(), 'src')
const leer = (ruta: string) => readFileSync(join(SRC, ruta), 'utf8')

/** Qué concepto del catálogo es cada entrada del menú que lo tiene. «Órdenes de carga» es de este producto y no entra al catálogo. */
const MENU: Record<string, Concepto> = {
  '/': 'dashboard',
  '/cuentas': 'cuentaCorriente',
  '/caja': 'caja',
  '/comprobantes': 'comprobantes',
  '/reportes': 'reportes',
  '/configuracion': 'configuracion',
  '/usuarios': 'usuarios',
  '/logs': 'logDeActividad',
}

/** Los títulos de las pantallas que un concepto del catálogo, y no el sidebar, decide: las pre facturas (un botón de Comprobantes, no una
 *  entrada del menú) y las que cuelgan de una entrada pero tienen su propio concepto. */
const TITULOS: Record<string, Concepto> = {
  PreFacturas: 'preFacturas',
  PreFactura: 'preFacturas',
  EditarPreFactura: 'preFacturas',
  FacturarPendientes: 'comprobantes',
  ComprobantesSeccion: 'comprobantes',
  CuentaCorriente: 'cuentaCorriente',
  Caja: 'caja',
  Logs: 'logDeActividad',
  Reporte: 'reportes',
  ReportesIndice: 'reportes',
  PreLiquidacionTransportistas: 'reportes',
}

const nombre = (i: unknown) => (i as { displayName?: string }).displayName

describe('LibraCargo es el único producto con excepción en el catálogo', () => {
  it('🔴 Proveedores es Store y Fleteros es Truck; el resto de la familia deja Truck para Proveedores', () => {
    const LC = iconosDe('libracargo')
    expect(LC.proveedores).toBe(lucide.Store)
    expect(LC.fleteros).toBe(lucide.Truck)
    expect(ICONOS.proveedores).toBe(lucide.Truck)
    // Dentro de LibraCargo no se repite ningún dibujo, que es lo que la excepción compra.
    const dibujos = Object.values(LC).map(nombre)
    expect(new Set(dibujos).size).toBe(dibujos.length)
  })
})

describe('el menú usa el catálogo', () => {
  it('🔴 cada entrada de un concepto del catálogo lleva el ícono del catálogo (con la excepción de LibraCargo)', () => {
    const r = auditarMenuContraCatalogo(leer('components/Layout.tsx'), MENU, 'libracargo')
    expect(r.mal).toEqual([])
    expect(r.faltan).toEqual([])
    // El control: un parser que no encuentra nada también deja `mal` vacío.
    expect(r.medidas).toBe(Object.keys(MENU).length)
  })

  it('🔴 los componentes de las entradas SON los del catálogo (comparación con ===, no por nombre)', () => {
    const items = NAV_SECCIONES.flatMap((s) => s.items)
    for (const [ruta, concepto] of Object.entries(MENU)) {
      const item = items.find((i) => i.to === ruta)
      expect(item, ruta).toBeDefined()
      expect(item!.icon, ruta).toBe(iconoDelConcepto(concepto, 'libracargo'))
    }
  })

  it('🔴 la entrada propia del producto (Órdenes de carga) no usa el dibujo de un concepto del catálogo', () => {
    const delCatalogo = new Set(Object.values(iconosDe('libracargo')).map(nombre))
    const propias = [...iconosDelNav(leer('components/Layout.tsx'))].filter(([ruta]) => !(ruta in MENU))
    expect(propias.map(([ruta]) => ruta)).toEqual(['/ordenes'])
    for (const [, icono] of propias) {
      expect(delCatalogo.has(nombre((lucide as unknown as Record<string, unknown>)[icono]) ?? icono)).toBe(false)
    }
  })
})

describe('los títulos usan el catálogo', () => {
  it.each(Object.entries(TITULOS))('🔴 %s lleva ICONOS_LC.%s', (pantalla, concepto) => {
    expect(iconoDelTitulo(leer(`pages/${pantalla}.tsx`)).icono).toBe(`ICONOS_LC.${concepto}`)
  })
})

describe('Proveedores es Store y Fleteros es Truck, en lo que se dibuja', () => {
  beforeEach(() => {
    get.mockReset()
    get.mockImplementation((ruta?: string) => {
      if (!ruta) return Promise.resolve([])
      if (ruta.startsWith('/api/comprobantes/totales')) {
        return Promise.resolve({
          cantidad_comprobantes: 0, neto_comprobantes: '0.00', iva_comprobantes: '0.00', total_comprobantes: '0.00',
          cantidad_ordenes: 0, neto_ordenes: '0.00', iva_ordenes: '0.00', total_ordenes: '0.00', coinciden: true,
        })
      }
      if (ruta.startsWith('/api/configuracion')) return Promise.resolve({ razon_social: 'Suitrans' })
      return Promise.resolve([])
    })
    // jsdom no trae `matchMedia`, que el menú lateral pide para saber si es un teléfono.
    window.matchMedia = ((q: string) => ({
      matches: false, media: q, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia
  })

  /** El ícono de lucide que lleva un elemento: lucide pone `lucide-<nombre>` en la clase del svg. */
  const iconoDe = (el: HTMLElement) => {
    const svg = el.querySelector('svg')
    return Array.from(svg?.classList ?? []).find((c) => c.startsWith('lucide-') && c !== 'lucide') ?? null
  }

  it('🔴 Comprobantes: la pestaña Proveedores dibuja Store y la de Clientes Users', async () => {
    render(<MemoryRouter initialEntries={['/comprobantes']}><App /></MemoryRouter>)
    const proveedores = await screen.findByRole('tab', { name: 'Proveedores' })
    expect(iconoDe(proveedores)).toBe('lucide-store')
    expect(iconoDe(screen.getByRole('tab', { name: 'Clientes' }))).toBe('lucide-users')
  })

  it('🔴 Comprobantes: el botón Pre facturas dibuja FileClock', async () => {
    render(<MemoryRouter initialEntries={['/comprobantes']}><App /></MemoryRouter>)
    const boton = (await screen.findByText('Pre facturas')).closest('a') as HTMLElement
    expect(iconoDe(boton)).toBe('lucide-file-clock')
  })

  it('🔴 Cuenta corriente: Clientes Users, Fleteros Truck y Proveedores Store', async () => {
    render(<MemoryRouter initialEntries={['/cuentas']}><CuentaCorriente /></MemoryRouter>)
    const pestanas = await screen.findByRole('tablist')
    expect(iconoDe(within(pestanas).getByRole('tab', { name: 'Clientes' }))).toBe('lucide-users')
    expect(iconoDe(within(pestanas).getByRole('tab', { name: 'Fleteros' }))).toBe('lucide-truck')
    expect(iconoDe(within(pestanas).getByRole('tab', { name: 'Proveedores' }))).toBe('lucide-store')
  })
})
