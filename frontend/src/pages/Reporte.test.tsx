import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', () => ({
  ApiError: class extends Error {},
  api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { default: Reporte } = await import('./Reporte')
const { default: ReportesIndice } = await import('./ReportesIndice')

const CATALOGO = [
  {
    slug: 'por-cliente', titulo: 'Clientes',
    descripcion: 'Ranking de clientes por lo facturado.',
    parametros: ['rango', 'cliente', 'limite'],
    detalle: false, solo_admin: false,
  },
  {
    slug: 'caja', titulo: 'Caja',
    descripcion: 'Ingresos y egresos del período.',
    parametros: ['rango', 'tercero', 'medio_pago', 'tipo_caja'],
    detalle: false, solo_admin: false,
  },
  // Un listado: filas de detalle, y el rango obligatorio.
  {
    slug: 'listado-ordenes', titulo: 'Listado de órdenes',
    descripcion: 'Las órdenes del período, una por línea.',
    parametros: ['rango', 'cliente', 'fletero'],
    detalle: true, solo_admin: false,
  },
]

const TERCEROS = [{ id: 3, razon_social: 'Agro Norte', es_cliente: true }]

function responder(datos: unknown[] = []) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta === '/api/reportes') return Promise.resolve(CATALOGO)
    if (ruta.startsWith('/api/reportes/')) return Promise.resolve(datos)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    return Promise.resolve([])
  })
}

function abrir(slug: string) {
  return render(
    <MemoryRouter initialEntries={[`/reportes/${slug}`]}>
      <Routes><Route path="/reportes/:slug" element={<Reporte />} /></Routes>
    </MemoryRouter>,
  )
}

describe('catálogo de reportes', () => {
  beforeEach(() => get.mockReset())

  it('cada reporte se lee antes de entrar: título, para qué sirve y por qué se filtra', async () => {
    responder()
    render(<MemoryRouter><ReportesIndice /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('Clientes')).toBeInTheDocument())
    expect(screen.getByText('Ranking de clientes por lo facturado.')).toBeInTheDocument()
    // Los parámetros se muestran con nombre de persona, no con el del backend.
    // La lista completa y no un pedazo: hay más de un reporte que empieza con
    // "fechas, cliente" y un regex parcial matchearía los dos.
    expect(screen.getByText(/fechas, cliente, cuántas filas/)).toBeInTheDocument()
  })
})

describe('Reporte', () => {
  beforeEach(() => get.mockReset())

  it('🔑 dibuja SÓLO los filtros que ese reporte acepta', async () => {
    // La barra sale de `parametros` del catálogo: si la pantalla tuviera su
    // propia lista, ofreceria filtros que el reporte ya no acepta.
    responder([])
    abrir('por-cliente')
    await waitFor(() => expect(screen.getByLabelText('Cliente')).toBeInTheDocument())
    expect(screen.getByLabelText('Desde')).toBeInTheDocument()
    expect(screen.getByLabelText('Cuántas filas')).toBeInTheDocument()
    // Y los que NO acepta no están: el de caja no aparece acá.
    expect(screen.queryByLabelText('Medio de pago')).toBeNull()
    expect(screen.queryByLabelText('Tipo')).toBeNull()
  })

  it('el mismo componente dibuja otros filtros para otro reporte', async () => {
    // El control del test de arriba: si la barra fuera fija, los dos reportes
    // mostrarian lo mismo.
    responder([])
    abrir('caja')
    await waitFor(() => expect(screen.getByLabelText('Medio de pago')).toBeInTheDocument())
    expect(screen.getByLabelText('Tipo')).toBeInTheDocument()
    expect(screen.queryByLabelText('Cliente')).toBeNull()
    expect(screen.queryByLabelText('Cuántas filas')).toBeNull()
  })

  it('elegir un filtro vuelve a pedir el reporte con ese parámetro', async () => {
    responder([{ tercero_id: 3, tercero: 'Agro Norte', ordenes: 2,
                 facturado: '3630.00', comision: '300.00', saldo: '2130.00' }])
    abrir('por-cliente')
    const select = await screen.findByLabelText('Cliente')
    await waitFor(() => expect(select.querySelectorAll('option').length).toBe(2))

    get.mockClear()
    fireEvent.change(select, { target: { value: '3' } })
    await waitFor(() =>
      expect(get.mock.calls.some((llamada) => {
        const ruta = String(llamada[0] ?? '')
        return ruta.includes('/api/reportes/por-cliente') && ruta.includes('cliente_id=3')
      })).toBe(true))
  })

  it('muestra la descripción del reporte adentro, no sólo en el índice', async () => {
    responder([])
    abrir('caja')
    await waitFor(() =>
      expect(screen.getByText('Ingresos y egresos del período.')).toBeInTheDocument())
  })
})

describe('los listados: el rango es obligatorio', () => {
  beforeEach(() => get.mockReset())

  it('🔑 sin desde y hasta no corre, y no hay botón de imprimir', async () => {
    // Es el cambio entero: antes esto era un botón arriba a la derecha de la
    // pantalla de órdenes, y apretarlo con la pantalla recién abierta mandaba
    // las 4.337 órdenes al papel.
    responder([{ fecha: '2026-07-05', tarifa: '1000.00' }])
    abrir('listado-ordenes')
    await waitFor(() => expect(screen.getByLabelText('Desde')).toBeInTheDocument())
    expect(screen.getByText(/Elegí un/)).toBeInTheDocument()
    expect(screen.queryByText('Imprimir')).toBeNull()
    // Y no se pidió el reporte: la guarda no es cosmética.
    expect(get.mock.calls.some(
      (l) => String(l[0] ?? '').includes('/api/reportes/listado-ordenes'))).toBe(false)
  })

  it('con las dos fechas corre y aparece el botón', async () => {
    // El control positivo del test de arriba: si el botón nunca apareciera, el
    // "queryByText(Imprimir) === null" pasaría igual con la guarda rota.
    responder([{ fecha: '2026-07-05', tarifa: '1000.00' }])
    abrir('listado-ordenes')
    fireEvent.change(await screen.findByLabelText('Desde'),
                     { target: { value: '2026-07-01' } })
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-07-31' } })

    await waitFor(() => expect(screen.getByText('Imprimir')).toBeInTheDocument())
    expect(get.mock.calls.some((l) => {
      const ruta = String(l[0] ?? '')
      return ruta.includes('/api/reportes/listado-ordenes')
        && ruta.includes('desde=2026-07-01') && ruta.includes('hasta=2026-07-31')
    })).toBe(true)
  })

  it('un reporte agregado NO exige rango: corre con la pantalla vacía', async () => {
    // El control cruzado: si la guarda se aplicara a todos, los siete reportes
    // de siempre dejarían de correr al abrirlos.
    responder([])
    abrir('por-cliente')
    await waitFor(() => expect(get.mock.calls.some(
      (l) => String(l[0] ?? '').includes('/api/reportes/por-cliente'))).toBe(true))
    expect(screen.queryByText(/Elegí un/)).toBeNull()
  })
})

describe('el índice separa los listados de los reportes', () => {
  beforeEach(() => get.mockReset())

  it('los listados van en su propia sección, y dice que piden fechas', async () => {
    responder()
    render(<MemoryRouter><ReportesIndice /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('Clientes')).toBeInTheDocument())
    expect(screen.getByText('Listados para imprimir')).toBeInTheDocument()
    expect(screen.getByText('Listado de órdenes')).toBeInTheDocument()
    expect(screen.getByText(/sin fechas es la tabla entera/)).toBeInTheDocument()
  })
})
