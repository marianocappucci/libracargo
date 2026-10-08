/** Configuración → «Tarifario de referencia» (ADR-038).
 *
 * Lo que se prueba es lo que la pantalla decide: cómo se lee cada edición, la búsqueda por km, que cargar sea sólo del
 * administrador, que una vigencia repetida se avise, que el 422 del servidor (que nombra la línea del CSV) se muestre
 * tal cual, y que la pestaña esté en Configuración.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const postForm = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm } }
})

let rol = 'admin'
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: rol, name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { TarifarioDeReferencia } = await import('./Tarifario')
const { Configuracion } = await import('./Configuracion')

const edicion = (id: number, extra: Record<string, unknown> = {}) => ({
  id, vigencia: '2026-04-10', nombre: 'Tarifario de referencia abril 2026', valor_estadia: '214146.67',
  filas: 1050, km_desde: 1, km_hasta: 1050, ...extra,
})

const FILAS = [
  { km: 1, tarifa: '9636.69' }, { km: 80, tarifa: '23205.57' }, { km: 81, tarifa: '23500.00' },
  { km: 800, tarifa: '95000.10' }, { km: 1050, tarifa: '120000.00' },
]

async function error(status: number, detail: string) {
  const { ApiError } = await import('libra-ui/api-client')
  return new (ApiError as unknown as new (s: number, d: string) => Error)(status, detail)
}

function responder(ediciones: unknown[] = [edicion(1)]) {
  get.mockImplementation((ruta?: string) => {
    if (ruta === '/api/tarifario') return Promise.resolve(ediciones)
    if (ruta?.match(/^\/api\/tarifario\/\d+\/filas$/)) return Promise.resolve(FILAS)
    return Promise.resolve([])
  })
}

const montar = () => render(<MemoryRouter><TarifarioDeReferencia /></MemoryRouter>)

beforeEach(() => {
  get.mockReset(); postForm.mockReset()
  rol = 'admin'
  responder()
})

describe('Tarifario · ediciones', () => {
  it('lista cada edición con vigencia dd-mm-aaaa, nombre, km desde–hasta, filas y valor de estadía', async () => {
    responder([
      edicion(2),
      edicion(1, { vigencia: '2025-11-03', nombre: 'Tarifario noviembre 2025', valor_estadia: null, filas: 900, km_hasta: 900 }),
    ])
    montar()
    const tabla = await screen.findByRole('table')
    expect(within(tabla).getByText('10-04-2026')).toBeInTheDocument()
    expect(within(tabla).getByText('Tarifario de referencia abril 2026')).toBeInTheDocument()
    expect(within(tabla).getByText('1–1.050')).toBeInTheDocument()
    expect(within(tabla).getByText('1.050')).toBeInTheDocument()
    expect(within(tabla).getByText('$ 214.146,67')).toBeInTheDocument()
    // La otra, sin valor de estadía.
    expect(within(tabla).getByText('03-11-2025')).toBeInTheDocument()
    expect(within(tabla).getByText('1–900')).toBeInTheDocument()
    expect(within(tabla).getByText('—')).toBeInTheDocument()
  })

  it('sin ediciones lo dice', async () => {
    responder([])
    montar()
    expect(await screen.findByText('Todavía no hay ningún tarifario cargado.')).toBeInTheDocument()
  })

  it('si el servidor falla al listar, muestra el motivo', async () => {
    get.mockRejectedValue(await error(500, 'no se pudo leer el tarifario'))
    montar()
    expect(await screen.findByRole('alert')).toHaveTextContent('no se pudo leer el tarifario')
  })

  it('«ver la tabla» muestra los km con su tarifa por tonelada en pesos', async () => {
    montar()
    fireEvent.click(await screen.findByRole('button', { name: 'Ver la tabla del 10-04-2026' }))
    const seccion = await screen.findByRole('region', { name: 'Tabla del 10-04-2026' })
    expect(await within(seccion).findByText('$ 23.205,57')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/tarifario/1/filas')
    expect(within(seccion).getAllByRole('row')).toHaveLength(1 + FILAS.length)
  })

  it('el buscador filtra por km: «80» trae el 80, el 81 no, y el 800 sí; sin coincidencias lo dice', async () => {
    montar()
    fireEvent.click(await screen.findByRole('button', { name: 'Ver la tabla del 10-04-2026' }))
    const seccion = await screen.findByRole('region', { name: 'Tabla del 10-04-2026' })
    await within(seccion).findByText('$ 23.205,57')

    fireEvent.change(within(seccion).getByLabelText('Buscar por km'), { target: { value: '80' } })
    expect(within(seccion).getByText('$ 23.205,57')).toBeInTheDocument()
    expect(within(seccion).getByText('$ 95.000,10')).toBeInTheDocument()
    expect(within(seccion).queryByText('$ 23.500,00')).toBeNull()
    expect(within(seccion).queryByText('$ 9.636,69')).toBeNull()

    fireEvent.change(within(seccion).getByLabelText('Buscar por km'), { target: { value: '7' } })
    expect(within(seccion).getByText('Ningún km empieza con 7.')).toBeInTheDocument()
  })
})

describe('Tarifario · cargar una edición', () => {
  const csv = () => new File(['80;23.205,57\n'], 'tarifario.csv', { type: 'text/csv' })

  function completar(vigencia = '2026-10-01') {
    const dialogo = screen.getByRole('form', { name: 'Cargar una edición' })
    fireEvent.change(within(dialogo).getByLabelText('Archivo CSV'), { target: { files: [csv()] } })
    fireEvent.change(within(dialogo).getByLabelText('Vigencia'), { target: { value: vigencia } })
    fireEvent.change(within(dialogo).getByLabelText('Nombre'), { target: { value: 'Tarifario octubre 2026' } })
    return dialogo
  }

  it('lleva el texto de ayuda del formato y de qué pasa con una vigencia repetida', async () => {
    montar()
    const formulario = await screen.findByRole('form', { name: 'Cargar una edición' })
    expect(formulario).toHaveTextContent(
      'CSV con dos columnas: km y tarifa por tonelada (por ejemplo 80;23.205,57). Si ya hay una edición con esa vigencia, se reemplaza.')
  })

  it('no se puede cargar sin archivo, vigencia y nombre', async () => {
    montar()
    const formulario = await screen.findByRole('form', { name: 'Cargar una edición' })
    expect(within(formulario).getByRole('button', { name: /Cargar/ })).toBeDisabled()
    completar()
    expect(within(formulario).getByRole('button', { name: /Cargar/ })).toBeEnabled()
  })

  it('manda el CSV por multipart, avisa cuántas filas quedaron y recarga las ediciones', async () => {
    montar()
    await screen.findByRole('table')
    postForm.mockResolvedValue(edicion(2, { vigencia: '2026-10-01', nombre: 'Tarifario octubre 2026', filas: 1100, km_hasta: 1100 }))
    const formulario = completar()
    fireEvent.change(within(formulario).getByLabelText('Valor de estadía (opcional)'), { target: { value: '250.000,50' } })
    fireEvent.click(within(formulario).getByRole('button', { name: /Cargar/ }))

    expect(await within(formulario).findByRole('status'))
      .toHaveTextContent('Se cargó «Tarifario octubre 2026», vigencia 01-10-2026: 1.100 filas (km 1–1.100).')
    const [ruta, cuerpo] = postForm.mock.calls[0] as [string, FormData]
    expect(ruta).toBe('/api/tarifario')
    expect(cuerpo.get('vigencia')).toBe('2026-10-01')
    expect(cuerpo.get('nombre')).toBe('Tarifario octubre 2026')
    expect(cuerpo.get('valor_estadia')).toBe('250.000,50')
    expect((cuerpo.get('archivo') as File).name).toBe('tarifario.csv')
    // El formulario queda limpio, listo para otra edición.
    expect(within(formulario).getByLabelText('Nombre')).toHaveValue('')
    // Y el listado se volvió a pedir.
    await waitFor(() => expect(get.mock.calls.filter((c) => c[0] === '/api/tarifario')).toHaveLength(2))
  })

  it('🔴 el 422 del servidor, que nombra la línea del CSV, se muestra tal cual', async () => {
    montar()
    await screen.findByRole('table')
    postForm.mockRejectedValue(await error(422, 'línea 4: «abc;12» no es un km y una tarifa'))
    const formulario = completar()
    fireEvent.click(within(formulario).getByRole('button', { name: /Cargar/ }))
    expect(await within(formulario).findByRole('alert')).toHaveTextContent('línea 4: «abc;12» no es un km y una tarifa')
    // No quedó un «se cargó» a medias, y lo tipeado sigue ahí para corregir el archivo y reintentar.
    expect(within(formulario).queryByRole('status')).toBeNull()
    expect(within(formulario).getByLabelText('Nombre')).toHaveValue('Tarifario octubre 2026')
  })

  it('una vigencia que ya existe avisa que se reemplaza entera, antes de mandar', async () => {
    montar()
    await screen.findByRole('table')
    const formulario = completar('2026-04-10')
    expect(within(formulario).getByRole('note'))
      .toHaveTextContent('Ya hay una edición con la vigencia 10-04-2026: se va a reemplazar entera.')
    fireEvent.change(within(formulario).getByLabelText('Vigencia'), { target: { value: '2026-10-01' } })
    expect(within(formulario).queryByRole('note')).toBeNull()
  })

  it('🔑 el personal que no es administrador ve el tarifario pero no el formulario de carga', async () => {
    rol = 'staff'
    montar()
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Cargar una edición' })).toBeNull()
    expect(screen.getByText('Las ediciones las carga un administrador.')).toBeInTheDocument()
    // Pero sí puede ver la tabla de una edición.
    fireEvent.click(screen.getByRole('button', { name: 'Ver la tabla del 10-04-2026' }))
    expect(await screen.findByRole('region', { name: 'Tabla del 10-04-2026' })).toBeInTheDocument()
  })
})

describe('Configuración · pestaña «Tarifario de referencia»', () => {
  beforeEach(() => {
    // jsdom no trae `matchMedia`, que algunas piezas del kit piden.
    window.matchMedia = ((q: string) => ({
      matches: false, media: q, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia
  })

  it('está entre las pestañas, con su ícono, y abre la pantalla del tarifario', async () => {
    render(<MemoryRouter initialEntries={['/configuracion?seccion=tarifario']}><Configuracion /></MemoryRouter>)
    const pestana = await screen.findByRole('tab', { name: 'Tarifario de referencia' })
    expect(pestana).toHaveAttribute('data-state', 'active')
    expect(pestana.querySelector('svg.lucide-route')).not.toBeNull()
    expect(await screen.findByRole('form', { name: 'Cargar una edición' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/tarifario')
  })
})
