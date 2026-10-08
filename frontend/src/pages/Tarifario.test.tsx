/** Configuración → «Tarifario de referencia» (ADR-038).
 *
 * Lo que se prueba es lo que la pantalla decide: cómo se lee cada edición, la búsqueda por km, que cargar sea sólo del
 * administrador, la vista previa del PDF (ADR-039) con sus campos precargados, que una vigencia repetida se avise, que el
 * 422 del servidor se muestre tal cual y bloquee, y que la pestaña esté en Configuración.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  const pdf = () => new File(['%PDF-1.4'], 'tarifario.pdf', { type: 'application/pdf' })
  const csv = () => new File(['80;23.205,57\n'], 'tarifario.csv', { type: 'text/csv' })

  /** Lo que lee el servidor de un PDF como lo descarga la página del sector. */
  const LEIDO = {
    vigencia: '2026-10-01', nombre: 'Tarifa de referencia octubre 2026', valor_estadia: '214146.67',
    filas: 1100, km_desde: 1, km_hasta: 1100, reemplaza: false,
    muestra: [{ km: 1, tarifa: '9636.69' }, { km: 80, tarifa: '23205.57' }, { km: 1000, tarifa: '110000.00' }],
  }

  /** Responde a `/previsualizar` con lo leído y deja el POST de cargar para cada test. */
  function previsualizarCon(leido: unknown) {
    postForm.mockImplementation((ruta: string) =>
      ruta === '/api/tarifario/previsualizar' ? Promise.resolve(leido) : Promise.resolve(edicion(2)))
  }

  async function elegir(archivo: File) {
    const formulario = await screen.findByRole('form', { name: 'Cargar una edición' })
    // `act` asíncrono: deja que termine la lectura del archivo (la respuesta de /previsualizar) antes de seguir.
    await act(async () => {
      fireEvent.change(within(formulario).getByLabelText('PDF del tarifario (o CSV)'), { target: { files: [archivo] } })
    })
    return formulario
  }

  const cargas = () => postForm.mock.calls.filter((c) => c[0] === '/api/tarifario') as [string, FormData][]

  it('lleva el texto de ayuda: se sube el PDF tal como se descarga, y también se acepta un CSV', async () => {
    montar()
    const formulario = await screen.findByRole('form', { name: 'Cargar una edición' })
    expect(formulario).toHaveTextContent(
      'Subí el PDF tal como lo descargás de la página. El sistema lee la tabla de km y tarifas, la vigencia y el valor de estadía. También se acepta un CSV km;tarifa.')
    const entrada = within(formulario).getByLabelText('PDF del tarifario (o CSV)')
    expect(entrada).toHaveAttribute('accept', '.pdf,.csv,application/pdf,text/csv')
  })

  it('sin archivo no hay vista previa ni campos, y no se puede cargar', async () => {
    montar()
    const formulario = await screen.findByRole('form', { name: 'Cargar una edición' })
    expect(within(formulario).getByRole('button', { name: /Cargar tarifario/ })).toBeDisabled()
    expect(within(formulario).queryByLabelText('Vigencia')).toBeNull()
    expect(within(formulario).queryByRole('region', { name: 'Vista previa' })).toBeNull()
  })

  it('al elegir el PDF lo manda a previsualizar y muestra vigencia, nombre, estadía, filas y la muestra de km', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon(LEIDO)
    const formulario = await elegir(pdf())

    const vista = await within(formulario).findByRole('region', { name: 'Vista previa' })
    expect(vista).toHaveTextContent('01-10-2026')
    expect(vista).toHaveTextContent('Tarifa de referencia octubre 2026')
    expect(vista).toHaveTextContent('$ 214.146,67')
    expect(vista).toHaveTextContent('1.100 filas, km 1 a 1100')
    const muestra = within(vista).getByRole('table', { name: 'Muestra de la tabla leída' })
    expect(within(muestra).getByText('$ 23.205,57')).toBeInTheDocument()
    expect(within(muestra).getAllByRole('row')).toHaveLength(1 + LEIDO.muestra.length)
    const [ruta, cuerpo] = postForm.mock.calls[0] as [string, FormData]
    expect(ruta).toBe('/api/tarifario/previsualizar')
    expect((cuerpo.get('archivo') as File).name).toBe('tarifario.pdf')
    // Previsualizar no guarda: todavía no se mandó la carga.
    expect(cargas()).toHaveLength(0)
    expect(within(formulario).queryByRole('note')).toBeNull()
  })

  it('los campos quedan precargados con lo leído y se pueden editar', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon(LEIDO)
    const formulario = await elegir(pdf())

    const vigencia = await within(formulario).findByLabelText('Vigencia')
    expect(vigencia).toHaveValue('2026-10-01')
    expect(within(formulario).getByLabelText('Nombre')).toHaveValue('Tarifa de referencia octubre 2026')
    expect(within(formulario).getByLabelText('Valor de estadía (opcional)')).toHaveValue('214.146,67')
    // El archivo trae la vigencia: no es obligatoria de tipear, y se puede cargar ya.
    expect(within(formulario).getByRole('button', { name: /Cargar tarifario/ })).toBeEnabled()

    fireEvent.change(within(formulario).getByLabelText('Nombre'), { target: { value: 'Octubre, corregido' } })
    fireEvent.change(vigencia, { target: { value: '2026-10-05' } })
    fireEvent.change(within(formulario).getByLabelText('Valor de estadía (opcional)'), { target: { value: '250.000,50' } })
    expect(within(formulario).getByLabelText('Nombre')).toHaveValue('Octubre, corregido')
    expect(vigencia).toHaveValue('2026-10-05')
    expect(within(formulario).getByLabelText('Valor de estadía (opcional)')).toHaveValue('250.000,50')
  })

  it('cargar el PDF sin tocar nada manda sólo el archivo, avisa cuántas filas quedaron y recarga las ediciones', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon(LEIDO)
    const formulario = await elegir(pdf())
    await within(formulario).findByRole('region', { name: 'Vista previa' })
    postForm.mockImplementation((ruta: string) => Promise.resolve(
      ruta === '/api/tarifario'
        ? edicion(2, { vigencia: '2026-10-01', nombre: 'Tarifa de referencia octubre 2026', filas: 1100, km_hasta: 1100 })
        : LEIDO))
    fireEvent.click(within(formulario).getByRole('button', { name: 'Cargar tarifario' }))

    expect(await within(formulario).findByText(/Se cargó/))
      .toHaveTextContent('Se cargó «Tarifa de referencia octubre 2026», vigencia 01-10-2026: 1.100 filas (km 1–1.100).')
    const [cuerpo] = cargas().map((c) => c[1])
    expect((cuerpo.get('archivo') as File).name).toBe('tarifario.pdf')
    // Lo leído del PDF lo vuelve a leer el servidor: no hace falta repetirlo.
    expect(cuerpo.has('vigencia')).toBe(false)
    expect(cuerpo.has('nombre')).toBe(false)
    expect(cuerpo.has('valor_estadia')).toBe(false)
    // El formulario queda limpio, listo para otra edición.
    expect(within(formulario).queryByLabelText('Nombre')).toBeNull()
    await waitFor(() => expect(get.mock.calls.filter((c) => c[0] === '/api/tarifario')).toHaveLength(2))
  })

  it('lo que el usuario cambió viaja y manda sobre lo leído', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon(LEIDO)
    const formulario = await elegir(pdf())
    await within(formulario).findByRole('region', { name: 'Vista previa' })
    fireEvent.change(within(formulario).getByLabelText('Nombre'), { target: { value: 'Octubre, corregido' } })
    fireEvent.change(within(formulario).getByLabelText('Vigencia'), { target: { value: '2026-10-05' } })
    fireEvent.change(within(formulario).getByLabelText('Valor de estadía (opcional)'), { target: { value: '250.000,50' } })
    fireEvent.click(within(formulario).getByRole('button', { name: 'Cargar tarifario' }))

    await waitFor(() => expect(cargas()).toHaveLength(1))
    const cuerpo = cargas()[0][1]
    expect(cuerpo.get('vigencia')).toBe('2026-10-05')
    expect(cuerpo.get('nombre')).toBe('Octubre, corregido')
    expect(cuerpo.get('valor_estadia')).toBe('250.000,50')
  })

  it('🔴 si previsualizar da 422, se muestra el motivo, no hay vista previa y no se puede confirmar', async () => {
    montar()
    await screen.findByRole('table')
    postForm.mockRejectedValue(
      await error(422, 'las tarifas del PDF no crecen con los km: no se pudo leer con seguridad'))
    const formulario = await elegir(pdf())

    expect(await within(formulario).findByRole('alert'))
      .toHaveTextContent('las tarifas del PDF no crecen con los km: no se pudo leer con seguridad')
    expect(within(formulario).queryByRole('region', { name: 'Vista previa' })).toBeNull()
    expect(within(formulario).getByRole('button', { name: 'Cargar tarifario' })).toBeDisabled()
    fireEvent.submit(formulario)
    expect(cargas()).toHaveLength(0)
  })

  it('un CSV no trae vigencia: la vista previa dice «no dice: indicala» y hay que tipearla para poder cargar', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon({
      vigencia: null, nombre: null, valor_estadia: null, filas: 1, km_desde: 80, km_hasta: 80, reemplaza: false,
      muestra: [{ km: 80, tarifa: '23205.57' }],
    })
    const formulario = await elegir(csv())

    const vista = await within(formulario).findByRole('region', { name: 'Vista previa' })
    expect(vista).toHaveTextContent('no dice: indicala')
    expect(vista).toHaveTextContent('1 filas, km 80 a 80')
    const vigencia = within(formulario).getByLabelText('Vigencia')
    expect(vigencia).toHaveValue('')
    expect(vigencia).toBeRequired()
    expect(within(formulario).getByRole('button', { name: 'Cargar tarifario' })).toBeDisabled()

    fireEvent.change(vigencia, { target: { value: '2026-10-01' } })
    expect(within(formulario).getByRole('button', { name: 'Cargar tarifario' })).toBeEnabled()
    fireEvent.click(within(formulario).getByRole('button', { name: 'Cargar tarifario' }))
    await waitFor(() => expect(cargas()).toHaveLength(1))
    const cuerpo = cargas()[0][1]
    expect((cuerpo.get('archivo') as File).name).toBe('tarifario.csv')
    expect(cuerpo.get('vigencia')).toBe('2026-10-01')
    expect(cuerpo.has('nombre')).toBe(false)
    expect(cuerpo.has('valor_estadia')).toBe(false)
  })

  it('🔴 el 422 de cargar (la vigencia que falta, una línea del CSV) se muestra tal cual y lo tipeado queda', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon(LEIDO)
    const formulario = await elegir(pdf())
    await within(formulario).findByRole('region', { name: 'Vista previa' })
    postForm.mockRejectedValue(await error(422, 'indicá la vigencia: el archivo no la dice'))
    fireEvent.change(within(formulario).getByLabelText('Nombre'), { target: { value: 'Octubre, corregido' } })
    fireEvent.click(within(formulario).getByRole('button', { name: 'Cargar tarifario' }))

    expect(await within(formulario).findByRole('alert')).toHaveTextContent('indicá la vigencia: el archivo no la dice')
    expect(within(formulario).queryByText(/Se cargó/)).toBeNull()
    expect(within(formulario).getByLabelText('Nombre')).toHaveValue('Octubre, corregido')
  })

  it('si la vista previa dice que reemplaza, lo avisa; y si se cambia la vigencia, avisa según las ediciones cargadas', async () => {
    montar()
    await screen.findByRole('table')
    previsualizarCon({ ...LEIDO, vigencia: '2026-04-10', reemplaza: true })
    const formulario = await elegir(pdf())
    expect(await within(formulario).findByRole('note'))
      .toHaveTextContent('Ya hay una edición con esa vigencia: se va a reemplazar entera.')
    // Otra vigencia sin edición: ya no reemplaza.
    fireEvent.change(within(formulario).getByLabelText('Vigencia'), { target: { value: '2026-10-01' } })
    expect(within(formulario).queryByRole('note')).toBeNull()
    // Y una que sí está cargada (la del 10-04-2026 del listado) vuelve a avisar.
    fireEvent.change(within(formulario).getByLabelText('Vigencia'), { target: { value: '2026-04-10' } })
    expect(within(formulario).getByRole('note')).toBeInTheDocument()
  })

  it('si se elige otro archivo mientras se lee el anterior, vale el último', async () => {
    montar()
    await screen.findByRole('table')
    let soltarPrimero: (v: unknown) => void = () => {}
    postForm.mockImplementationOnce(() => new Promise((r) => { soltarPrimero = r }))
    const formulario = await elegir(pdf())
    expect(await within(formulario).findByText('Leyendo el archivo…')).toBeInTheDocument()
    postForm.mockResolvedValueOnce({ ...LEIDO, nombre: 'El segundo' })
    await act(async () => {
      fireEvent.change(within(formulario).getByLabelText('PDF del tarifario (o CSV)'), { target: { files: [csv()] } })
    })
    expect(await within(formulario).findByLabelText('Nombre')).toHaveValue('El segundo')
    await act(async () => { soltarPrimero({ ...LEIDO, nombre: 'El primero' }) })
    expect(within(formulario).getByLabelText('Nombre')).toHaveValue('El segundo')
  })

  it('🔑 el personal que no es administrador ve el tarifario pero no el formulario de carga', async () => {
    rol = 'staff'
    montar()
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Cargar una edición' })).toBeNull()
    expect(screen.getByText('Las ediciones las carga un administrador.')).toBeInTheDocument()
    // Pero sí puede ver la tabla de una edición.
    fireEvent.click(await screen.findByRole('button', { name: 'Ver la tabla del 10-04-2026' }))
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
