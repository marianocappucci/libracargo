/** El selector de origen y destino (ADR-041): maestro primero, catálogo de Argentina debajo y «cargar como paraje» al final.
 *
 *  Lo que se prueba es lo que decide la pantalla y el servidor no puede: el orden y el rótulo de los grupos, que elegir del
 *  catálogo llame a `/desde-catalogo` y deje seleccionada **la localidad que devuelve el servidor** (no la del catálogo), y
 *  que el paraje pida provincia y muestre el 409/422 tal cual. El buscador espera 250 ms tras la última tecla: por eso todo
 *  lo asíncrono va con `findBy*`/`waitFor` y un tiempo holgado (en el CI la suite entera tarda más que en una notebook).
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20_000 })

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

const { ApiError } = await import('libra-ui/api-client')
const { ElegirLocalidad } = await import('./ElegirLocalidad')
const { aOpcionLocalidad } = await import('@/api/localidades')
const { _olvidarCache } = await import('@/api/geo')

const SUIPACHA_MAESTRO = { id: 1, nombre: 'Suipacha', provincia: 'Buenos Aires', es_paraje: false, activo: true, catalogo_id: '06784020' }
const SUIPACHA_PARAJE = { id: 2, nombre: 'Suipacha Chica', provincia: 'Santa Fe', es_paraje: true, activo: true, catalogo_id: null }
const SUIPACHA_BAJA = { id: 3, nombre: 'Suipacha Vieja', provincia: null, es_paraje: false, activo: false, catalogo_id: null }
const SUIPACHA_CATALOGO = { id: '82084020', nombre: 'Suipacha', provincia_id: '82', provincia: 'Santa Fe' }

const PROVINCIAS = [{ id: '06', nombre: 'Buenos Aires' }, { id: '82', nombre: 'Santa Fe' }]

/** El formulario de una orden, en chiquito: guarda el id elegido y la lista que conoce. */
function Campo({ inicial = '', alElegir = vi.fn(), conocidas = [SUIPACHA_MAESTRO] }: {
  inicial?: string; alElegir?: (id: string) => void; conocidas?: typeof SUIPACHA_MAESTRO[]
}) {
  const [valor, setValor] = useState(inicial)
  const [lista, setLista] = useState(conocidas.map(aOpcionLocalidad))
  return (
    <ElegirLocalidad
      id="origen_id" etiqueta="Origen" valor={valor} localidades={lista}
      alElegir={(v) => { setValor(v); alElegir(v) }}
      alIncorporar={(l) => setLista((xs) => [...xs.filter((x) => x.id !== l.id), aOpcionLocalidad(l)])}
    />
  )
}

let combinado: { maestro: unknown[]; catalogo: unknown[] }

beforeEach(() => {
  get.mockReset(); post.mockReset(); _olvidarCache()
  combinado = { maestro: [SUIPACHA_MAESTRO, SUIPACHA_PARAJE, SUIPACHA_BAJA], catalogo: [SUIPACHA_CATALOGO] }
  get.mockImplementation((ruta?: string) => {
    if (ruta?.startsWith('/api/localidades/buscar/combinado')) return Promise.resolve(combinado)
    if (ruta?.startsWith('/api/geo/provincias')) return Promise.resolve(PROVINCIAS)
    return Promise.resolve([])
  })
})

/** Escribe en el campo y espera la lista. */
async function buscar(texto: string) {
  const campo = screen.getByRole('combobox', { name: 'Origen' })
  fireEvent.focus(campo)
  fireEvent.change(campo, { target: { value: texto } })
  return { campo, lista: await screen.findByRole('listbox') }
}

describe('ElegirLocalidad · búsqueda combinada', () => {
  it('pide /buscar/combinado con lo escrito y muestra primero el maestro y después el catálogo, con su provincia', async () => {
    render(<Campo />)
    const { lista } = await buscar('suip')
    await within(lista).findByText('Suipacha — Santa Fe')

    expect(get).toHaveBeenCalledWith('/api/localidades/buscar/combinado?q=suip&limite=20')
    const textos = within(lista).getAllByRole('option').map((o) => o.textContent)
    expect(textos).toEqual([
      'Suipacha — Buenos Aires',      // maestro, del catálogo
      'Suipacha Chica — Santa FeParaje',  // maestro, paraje con su marca
      'Suipacha ViejaDe baja',
      'Suipacha — Santa Fe',          // del catálogo (todavía no está en el maestro)
      'Cargar «suip» como paraje…',
    ])
    // El separador está entre las del maestro y las del catálogo, y no es una opción.
    const separador = within(lista).getByText('Del catálogo de Argentina')
    expect(separador).toHaveAttribute('role', 'presentation')
    const opciones = within(lista).getAllByRole('option')
    expect(separador.compareDocumentPosition(opciones[3]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(separador.compareDocumentPosition(opciones[2]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
  })

  it('espera a que se termine de tipear: «suipacha» no pide primero «sui»', async () => {
    render(<Campo />)
    const campo = screen.getByRole('combobox', { name: 'Origen' })
    fireEvent.focus(campo)
    for (const t of ['su', 'sui', 'suip', 'suipacha']) fireEvent.change(campo, { target: { value: t } })
    await screen.findByRole('option', { name: /Suipacha — Santa Fe/ })
    const pedidos = get.mock.calls.map((c) => String(c[0])).filter((r) => r.includes('buscar/combinado'))
    expect(pedidos).toEqual(['/api/localidades/buscar/combinado?q=suipacha&limite=20'])
  })

  it('con menos de dos letras no pide nada y lo dice', async () => {
    render(<Campo />)
    const campo = screen.getByRole('combobox', { name: 'Origen' })
    fireEvent.focus(campo)
    fireEvent.change(campo, { target: { value: 's' } })
    expect(await screen.findByText(/Escribí al menos 2 letras/)).toBeInTheDocument()
    expect(get.mock.calls.some((c) => String(c[0]).includes('buscar/combinado'))).toBe(false)
    // Y todavía no ofrece cargar un paraje con una sola letra.
    expect(screen.queryByText(/como paraje/)).toBeNull()
  })

  it('una localidad de baja se ve pero no se puede elegir', async () => {
    const alElegir = vi.fn()
    render(<Campo alElegir={alElegir} />)
    const { lista } = await buscar('suip')
    fireEvent.click(await within(lista).findByText('Suipacha Vieja'))
    expect(alElegir).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })

  it('muestra la elegida con su provincia y se puede quitar', async () => {
    render(<Campo inicial="1" />)
    expect(screen.getByRole('combobox', { name: 'Origen' })).toHaveValue('Suipacha — Buenos Aires')
    fireEvent.click(screen.getByLabelText('Quitar la selección'))
    expect(screen.getByRole('combobox', { name: 'Origen' })).toHaveValue('')
  })

  it('si la búsqueda falla, lo dice con el mensaje del servidor', async () => {
    get.mockImplementation((ruta?: string) =>
      ruta?.includes('buscar/combinado') ? Promise.reject(new ApiError(500, 'se cayó el catálogo')) : Promise.resolve([]))
    render(<Campo />)
    await buscar('suip')
    expect(await screen.findByText('se cayó el catálogo')).toBeInTheDocument()
  })
})

describe('ElegirLocalidad · elegir', () => {
  it('una del maestro queda elegida sin llamar al servidor', async () => {
    const alElegir = vi.fn()
    render(<Campo alElegir={alElegir} />)
    const { lista } = await buscar('suip')
    fireEvent.click(await within(lista).findByRole('option', { name: 'Suipacha — Buenos Aires' }))
    expect(alElegir).toHaveBeenCalledWith('1')
    expect(post).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull())
  })

  it('🔑 una del catálogo llama /desde-catalogo y queda seleccionada la que DEVUELVE el servidor', async () => {
    // El id del maestro (77) no es el código censal ('82084020'): lo que va a la orden es el primero.
    post.mockResolvedValue({ id: 77, nombre: 'Suipacha', provincia: 'Santa Fe', es_paraje: false, activo: true, catalogo_id: '82084020' })
    const alElegir = vi.fn()
    render(<Campo alElegir={alElegir} />)
    const { lista } = await buscar('suip')
    fireEvent.click(await within(lista).findByRole('option', { name: 'Suipacha — Santa Fe' }))

    await waitFor(() => expect(alElegir).toHaveBeenCalledWith('77'))
    expect(post).toHaveBeenCalledWith('/api/localidades/desde-catalogo', { catalogo_id: '82084020' })
    // El campo muestra el nombre con la provincia, que salió de la lista que el formulario incorporó.
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Origen' })).toHaveValue('Suipacha — Santa Fe'))
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('si el servidor rechaza traerla, muestra su mensaje y no elige nada', async () => {
    post.mockRejectedValue(new ApiError(404, 'no hay una localidad con código \'82084020\' en el catálogo'))
    const alElegir = vi.fn()
    render(<Campo alElegir={alElegir} />)
    const { lista } = await buscar('suip')
    fireEvent.click(await within(lista).findByRole('option', { name: 'Suipacha — Santa Fe' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('no hay una localidad con código')
    expect(alElegir).not.toHaveBeenCalled()
  })

  it('con el teclado: flechas para recorrer, Enter para elegir, Escape para cerrar', async () => {
    post.mockResolvedValue({ id: 77, nombre: 'Suipacha', provincia: 'Santa Fe', es_paraje: false, activo: true, catalogo_id: '82084020' })
    const alElegir = vi.fn()
    render(<Campo alElegir={alElegir} />)
    const { campo } = await buscar('suip')
    await screen.findByRole('option', { name: 'Suipacha — Santa Fe' })

    // La primera resaltada es la primera del maestro; tres flechas abajo llegan a la del catálogo.
    expect(campo).toHaveAttribute('aria-activedescendant')
    for (let i = 0; i < 3; i++) fireEvent.keyDown(campo, { key: 'ArrowDown' })
    const activa = document.getElementById(campo.getAttribute('aria-activedescendant')!)
    expect(activa).toHaveTextContent('Suipacha — Santa Fe')
    fireEvent.keyDown(campo, { key: 'Enter' })
    await waitFor(() => expect(alElegir).toHaveBeenCalledWith('77'))

    // Escape cierra la lista y descarta lo escrito.
    fireEvent.change(campo, { target: { value: 'ro' } })
    await screen.findByRole('listbox')
    fireEvent.keyDown(campo, { key: 'Escape' })
    expect(screen.queryByRole('listbox')).toBeNull()
  })
})

describe('ElegirLocalidad · cargar como paraje', () => {
  async function abrirDialogo(texto = 'Tomás Jofré') {
    combinado = { maestro: [], catalogo: [] }
    render(<Campo />)
    const { lista } = await buscar(texto)
    fireEvent.click(await within(lista).findByRole('option', { name: `Cargar «${texto}» como paraje…` }))
    return await screen.findByRole('dialog')
  }

  it('la opción final lleva lo escrito; abre el diálogo con el nombre precargado y la provincia por elegir', async () => {
    const dialogo = await abrirDialogo()
    expect(within(dialogo).getByLabelText('Nombre del paraje')).toHaveValue('Tomás Jofré')
    const provincia = within(dialogo).getByLabelText('Provincia')
    await within(dialogo).findByRole('option', { name: 'Santa Fe' })
    expect(provincia).toHaveValue('')
  })

  it('la provincia es obligatoria: sin ella no manda nada y lo dice', async () => {
    const dialogo = await abrirDialogo()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cargar paraje' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('Elegí la provincia')
    expect(post).not.toHaveBeenCalled()
  })

  it('🔑 crea con es_paraje: true y la provincia, y la nueva queda seleccionada', async () => {
    post.mockResolvedValue({ id: 90, nombre: 'Tomás Jofré', provincia: 'Buenos Aires', es_paraje: true, activo: true, catalogo_id: null })
    const alElegir = vi.fn()
    combinado = { maestro: [], catalogo: [] }
    render(<Campo alElegir={alElegir} />)
    const { lista } = await buscar('Tomás Jofré')
    fireEvent.click(await within(lista).findByRole('option', { name: 'Cargar «Tomás Jofré» como paraje…' }))
    const dialogo = await screen.findByRole('dialog')
    await within(dialogo).findByRole('option', { name: 'Buenos Aires' })
    fireEvent.change(within(dialogo).getByLabelText('Provincia'), { target: { value: 'Buenos Aires' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cargar paraje' }))

    await waitFor(() => expect(alElegir).toHaveBeenCalledWith('90'))
    expect(post).toHaveBeenCalledWith('/api/localidades', {
      nombre: 'Tomás Jofré', provincia: 'Buenos Aires', es_paraje: true, activo: true,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByRole('combobox', { name: 'Origen' })).toHaveValue('Tomás Jofré — Buenos Aires')
  })

  it('un 409 (ya existe en esa provincia) se muestra tal cual y el diálogo sigue abierto', async () => {
    post.mockRejectedValue(new ApiError(409, 'ya existe una localidad «Tomás Jofré» en Buenos Aires'))
    const dialogo = await abrirDialogo()
    await within(dialogo).findByRole('option', { name: 'Buenos Aires' })
    fireEvent.change(within(dialogo).getByLabelText('Provincia'), { target: { value: 'Buenos Aires' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cargar paraje' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('ya existe una localidad «Tomás Jofré» en Buenos Aires')
  })
})
