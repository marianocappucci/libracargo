/** Configuración → Localidades (ADR-041, ADR-042): de dónde viene cada localidad y cómo se resuelve lo que falta.
 *
 *  Lo que se prueba es lo que la pantalla decide: la pastilla «Origen» de cada fila, el filtro de lo que falta vincular, qué
 *  acciones ofrece cada fila (y que unificar es sólo del administrador), a qué endpoint va cada una y que el 409 del servidor
 *  se muestra tal cual. Que una localidad se vincule o se unifique bien es del backend.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable } from '@/test/buscable'

// Los buscadores esperan 250 ms tras la última tecla y en el CI la suite entera tarda más que en una notebook.
configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20_000 })

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post, put, del: vi.fn() } }
})

let rol = 'admin'
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: rol, name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { ApiError } = await import('libra-ui/api-client')
const { Localidades } = await import('./Localidades')
const { _olvidarCache } = await import('@/api/geo')

const fila = (id: number, extra: Record<string, unknown> = {}) => ({
  id, nombre: `Lugar ${id}`, provincia: 'Buenos Aires', pais: 'AR', es_paraje: false, activo: true, catalogo_id: null, ...extra,
})
const FILAS = [
  fila(1, { nombre: 'Suipacha', catalogo_id: '06784020' }),
  fila(2, { nombre: 'Tomás Jofré', es_paraje: true }),
  fila(3, { nombre: 'Pto San Martín', provincia: 'Santa Fe' }),
  fila(4, { nombre: 'Pto. San Martín', provincia: 'Santa Fe' }),
  fila(5, { nombre: 'Cnel. Bogado', provincia: null }),
  fila(6, { nombre: 'Lugar de baja', activo: false }),
  fila(7, { nombre: 'Nueva Palmira', provincia: 'Colonia', pais: 'UY', catalogo_id: 'UY-1' }),
  fila(8, { nombre: 'Puerto Pilcomayo', provincia: null, pais: 'PY' }),
]
const PROVINCIAS = [{ id: '06', nombre: 'Buenos Aires' }, { id: '82', nombre: 'Santa Fe' }]
const PROVINCIAS_UY = [{ id: 'UY-CO', nombre: 'Colonia', pais: 'UY' }, { id: 'UY-MO', nombre: 'Montevideo', pais: 'UY' }]
const PAISES = [
  { id: 'AR', nombre: 'Argentina' }, { id: 'BR', nombre: 'Brasil' }, { id: 'CL', nombre: 'Chile' },
  { id: 'PY', nombre: 'Paraguay' }, { id: 'BO', nombre: 'Bolivia' }, { id: 'UY', nombre: 'Uruguay' },
]
const PUERTO = { id: '82021010', nombre: 'Puerto General San Martín', provincia_id: '82', provincia: 'Santa Fe', pais: 'AR' }
const SUIPACHA_BA = { id: '06784020', nombre: 'Suipacha', provincia_id: '06', provincia: 'Buenos Aires', pais: 'AR' }
const PALMIRA = { id: 'UY-1', nombre: 'Nueva Palmira', provincia_id: 'UY-CO', provincia: 'Colonia', pais: 'UY' }

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset(); _olvidarCache()
  rol = 'admin'
  get.mockImplementation((ruta?: string) => {
    if (ruta?.startsWith('/api/geo/paises')) return Promise.resolve(PAISES)
    if (ruta?.startsWith('/api/geo/provincias?pais=UY')) return Promise.resolve(PROVINCIAS_UY)
    if (ruta?.startsWith('/api/geo/provincias')) return Promise.resolve(PROVINCIAS)
    if (ruta?.startsWith('/api/geo/localidades')) {
      if (ruta.includes('pais=UY')) return Promise.resolve([PALMIRA])
      return Promise.resolve(ruta.includes('q=suip') ? [SUIPACHA_BA] : [PUERTO])
    }
    return Promise.resolve(FILAS)
  })
})

function abrir() {
  render(<MemoryRouter><Localidades /></MemoryRouter>)
}

/** La fila de la tabla con ese nombre. */
async function laFila(nombre: string) {
  const celda = await screen.findByRole('cell', { name: nombre })
  return celda.closest('tr') as HTMLElement
}

describe('Localidades · listado', () => {
  it('muestra Nombre, Provincia, País, Origen y Estado, con la pastilla de cada fila', async () => {
    abrir()
    const tabla = await screen.findByRole('table')
    await screen.findByText('Suipacha')
    for (const col of ['Nombre', 'Provincia', 'País', 'Origen', 'Estado']) {
      expect(within(tabla).getByRole('columnheader', { name: new RegExp(col) })).toBeInTheDocument()
    }
    const origen = async (nombre: string) =>
      within(await laFila(nombre)).getAllByText(/^(Catálogo|Paraje|Sin vincular)$/)[0]
    expect(await origen('Suipacha')).toHaveTextContent('Catálogo')
    expect(await origen('Tomás Jofré')).toHaveTextContent('Paraje')
    expect(await origen('Pto San Martín')).toHaveTextContent('Sin vincular')
    // Cada una lleva su tono: lo esperado queda quieto, la excepción es azul y lo que falta decidir, ámbar.
    expect((await origen('Suipacha')).getAttribute('data-tono')).toBe('neutro')
    expect((await origen('Tomás Jofré')).getAttribute('data-tono')).toBe('curso')
    expect((await origen('Pto San Martín')).getAttribute('data-tono')).toBe('atencion')
  })

  it('🔑 la columna País muestra el nombre del país de cada fila, y se puede buscar por él', async () => {
    abrir()
    const tabla = await screen.findByRole('table')
    await screen.findByText('Suipacha')
    const pais = async (nombre: string) => {
      const celdas = within(await laFila(nombre)).getAllByRole('cell').map((c) => c.textContent)
      return celdas
    }
    expect(await pais('Suipacha')).toContain('Argentina')
    expect(await pais('Nueva Palmira')).toContain('Uruguay')
    expect(await pais('Puerto Pilcomayo')).toContain('Paraguay')

    fireEvent.change(screen.getByPlaceholderText(/Buscar en localidades/), { target: { value: 'uruguay' } })
    await waitFor(() => expect(within(tabla).queryByText('Suipacha')).toBeNull())
    expect(within(tabla).getByText('Nueva Palmira')).toBeInTheDocument()
  })

  it('el filtro «Sin vincular» deja sólo las activas que faltan emparejar, y se saca con el mismo botón', async () => {
    abrir()
    await screen.findByText('Suipacha')
    // Cuenta las activas sin vincular: 3, 4, 5 y 8. La baja (6) no pide nada a nadie.
    const filtro = await screen.findByRole('button', { name: 'Sin vincular (4)' })
    expect(filtro).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(filtro)
    expect(filtro).toHaveAttribute('aria-pressed', 'true')
    const tabla = screen.getByRole('table')
    expect(within(tabla).queryByText('Suipacha')).toBeNull()
    expect(within(tabla).queryByText('Tomás Jofré')).toBeNull()
    expect(within(tabla).queryByText('Lugar de baja')).toBeNull()
    for (const n of ['Pto San Martín', 'Pto. San Martín', 'Cnel. Bogado']) {
      expect(within(tabla).getByText(n)).toBeInTheDocument()
    }

    fireEvent.click(filtro)
    expect(within(screen.getByRole('table')).getByText('Suipacha')).toBeInTheDocument()
  })

  it('«Vincular» está en las que no son del catálogo; «Marcar como paraje», sólo en las sin vincular', async () => {
    abrir()
    const botones = async (nombre: string) =>
      within(await laFila(nombre)).queryAllByRole('button').map((b) => b.getAttribute('aria-label'))
    expect(await botones('Suipacha')).not.toContain('Vincular al catálogo')
    expect(await botones('Suipacha')).not.toContain('Marcar como paraje')
    expect(await botones('Tomás Jofré')).toContain('Vincular al catálogo')
    expect(await botones('Tomás Jofré')).not.toContain('Marcar como paraje')
    expect(await botones('Pto San Martín')).toEqual(
      expect.arrayContaining(['Vincular al catálogo', 'Marcar como paraje', 'Unificar con…']))
  })

  it('«Unificar con…» es sólo del administrador', async () => {
    rol = 'operador'
    abrir()
    await screen.findByText('Suipacha')
    expect(screen.queryByLabelText('Unificar con…')).toBeNull()
    // Lo demás sí está para todos.
    expect(screen.getAllByLabelText('Vincular al catálogo').length).toBeGreaterThan(0)
  })
})

describe('Localidades · vincular al catálogo', () => {
  async function abrirVincular(nombre = 'Pto San Martín') {
    abrir()
    fireEvent.click(within(await laFila(nombre)).getByLabelText('Vincular al catálogo'))
    return await screen.findByRole('dialog')
  }

  it('busca en el catálogo con el nombre de la fila ya escrito y vincula la elegida: POST /vincular', async () => {
    post.mockResolvedValue({ ...FILAS[2], catalogo_id: PUERTO.id })
    const dialogo = await abrirVincular()
    const opcion = await within(dialogo).findByRole('option', { name: 'Puerto General San Martín — Santa Fe' })
    expect(get).toHaveBeenCalledWith('/api/geo/localidades?q=Pto%20San%20Mart%C3%ADn&limite=20&pais=AR')

    const antes = get.mock.calls.filter((c) => c[0] === '/api/localidades').length
    fireEvent.click(opcion)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades/3/vincular', { catalogo_id: '82021010' }))
    // Se cierra y se vuelve a pedir el listado para ver la pastilla nueva.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await waitFor(() => expect(get.mock.calls.filter((c) => c[0] === '/api/localidades').length).toBe(antes + 1))
  })

  it('🔑 busca en el país de la fila y se puede cambiar; al cambiarlo vuelve a buscar con ?pais=', async () => {
    abrir()
    fireEvent.click(within(await laFila('Puerto Pilcomayo')).getByLabelText('Vincular al catálogo'))
    const dialogo = await screen.findByRole('dialog')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/geo/localidades?q=Puerto%20Pilcomayo&limite=20&pais=PY'))
    const pais = within(dialogo).getByLabelText('País')
    await within(dialogo).findByRole('option', { name: 'Uruguay' })
    expect(pais).toHaveValue('PY')

    fireEvent.change(pais, { target: { value: 'UY' } })
    expect(await within(dialogo).findByRole('option', { name: /Nueva Palmira — Colonia \(Uruguay\)/ })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/geo/localidades?q=Puerto%20Pilcomayo&limite=20&pais=UY')

    fireEvent.change(pais, { target: { value: 'todos' } })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/geo/localidades?q=Puerto%20Pilcomayo&limite=20&pais=todos'))
  })

  it('🔑 el 409 («ya está vinculada a …») se muestra tal cual y el diálogo no se cierra', async () => {
    const mensaje = '«Puerto General San Martín» del catálogo ya está vinculada a «Pto. San Martín» (id 4): si son la misma, unificalas'
    post.mockRejectedValue(new ApiError(409, mensaje))
    const dialogo = await abrirVincular()
    fireEvent.click(await within(dialogo).findByRole('option', { name: /Puerto General San Martín/ }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent(mensaje)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

describe('Localidades · marcar como paraje', () => {
  it('con provincia no pregunta nada: edita con es_paraje: true', async () => {
    put.mockResolvedValue({ ...FILAS[2], es_paraje: true })
    abrir()
    fireEvent.click(within(await laFila('Pto San Martín')).getByLabelText('Marcar como paraje'))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/localidades/3', {
      nombre: 'Pto San Martín', provincia: 'Santa Fe', pais: 'AR', es_paraje: true, activo: true,
    }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('sin provincia la pide en un diálogo, con el nombre fijo, y no manda nada hasta tenerla', async () => {
    put.mockResolvedValue({ ...FILAS[4], provincia: 'Buenos Aires', es_paraje: true })
    abrir()
    fireEvent.click(within(await laFila('Cnel. Bogado')).getByLabelText('Marcar como paraje'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Nombre del paraje')).toHaveAttribute('readonly')

    fireEvent.click(within(dialogo).getByRole('button', { name: 'Marcar como paraje' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('Elegí la provincia')
    expect(put).not.toHaveBeenCalled()

    await elegirEnBuscable(within(dialogo).getByRole('combobox', { name: 'Provincia' }), 'Buenos Aires')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Marcar como paraje' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/localidades/5', {
      nombre: 'Cnel. Bogado', provincia: 'Buenos Aires', pais: 'AR', es_paraje: true, activo: true,
    }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('una sin provincia de otro país conserva su país: el diálogo parte de él y el PUT lo manda', async () => {
    put.mockResolvedValue({ ...FILAS[7], provincia: 'Presidente Hayes', es_paraje: true })
    abrir()
    fireEvent.click(within(await laFila('Puerto Pilcomayo')).getByLabelText('Marcar como paraje'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('País')).toHaveValue('PY')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/geo/provincias?pais=PY'))
    await elegirEnBuscable(within(dialogo).getByRole('combobox', { name: 'Provincia' }), 'Buenos Aires')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Marcar como paraje' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/localidades/8', {
      nombre: 'Puerto Pilcomayo', provincia: 'Buenos Aires', pais: 'PY', es_paraje: true, activo: true,
    }))
  })

  it('si el servidor lo rechaza, el mensaje se ve arriba de la tabla', async () => {
    put.mockRejectedValue(new ApiError(409, 'ya existe una localidad con ese nombre en esa provincia'))
    abrir()
    fireEvent.click(within(await laFila('Pto San Martín')).getByLabelText('Marcar como paraje'))
    expect(await screen.findByRole('alert')).toHaveTextContent('ya existe una localidad con ese nombre en esa provincia')
  })
})

describe('Localidades · unificar', () => {
  async function abrirUnificar() {
    abrir()
    fireEvent.click(within(await laFila('Pto. San Martín')).getByLabelText('Unificar con…'))
    return await screen.findByRole('dialog')
  }

  async function elegirDestino(dialogo: HTMLElement, texto: string, opcion: string) {
    const campo = within(dialogo).getByRole('combobox', { name: 'La localidad que queda' })
    fireEvent.focus(campo)
    fireEvent.change(campo, { target: { value: texto } })
    fireEvent.click(await within(dialogo).findByRole('option', { name: opcion }))
  }

  it('hasta elegir la que queda no se puede unificar; al elegir, dice con todas las letras qué va a pasar', async () => {
    const dialogo = await abrirUnificar()
    expect(within(dialogo).getByRole('button', { name: 'Unificar' })).toBeDisabled()
    await elegirDestino(dialogo, 'pto san', 'Pto San Martín — Santa Fe')
    expect(within(dialogo).getByRole('note')).toHaveTextContent(
      'Las órdenes de «Pto. San Martín» pasan a «Pto San Martín» y «Pto. San Martín» se da de baja.')
    expect(within(dialogo).getByRole('button', { name: 'Unificar' })).toBeEnabled()
  })

  it('no ofrece la misma fila ni las bajas como destino', async () => {
    const dialogo = await abrirUnificar()
    const campo = within(dialogo).getByRole('combobox', { name: 'La localidad que queda' })
    fireEvent.focus(campo)
    fireEvent.change(campo, { target: { value: 'a' } })
    const nombres = (await within(dialogo).findAllByRole('option')).map((o) => o.textContent)
    expect(nombres).not.toContain('Pto. San Martín — Santa Fe')
    expect(nombres).not.toContain('Lugar de baja — Buenos Aires')
    expect(nombres).toContain('Pto San Martín — Santa Fe')
  })

  it('confirma con POST /unificar {en_id}, cierra y recarga', async () => {
    post.mockResolvedValue(FILAS[2])
    const dialogo = await abrirUnificar()
    await elegirDestino(dialogo, 'pto san', 'Pto San Martín — Santa Fe')
    const antes = get.mock.calls.filter((c) => c[0] === '/api/localidades').length
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Unificar' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades/4/unificar', { en_id: 3 }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await waitFor(() => expect(get.mock.calls.filter((c) => c[0] === '/api/localidades').length).toBe(antes + 1))
  })

  it('un error del servidor se muestra en el diálogo y no se cierra', async () => {
    post.mockRejectedValue(new ApiError(403, 'sólo un administrador puede unificar'))
    const dialogo = await abrirUnificar()
    await elegirDestino(dialogo, 'pto san', 'Pto San Martín — Santa Fe')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Unificar' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('sólo un administrador puede unificar')
  })
})

describe('Localidades · altas', () => {
  it('«Agregar del catálogo» busca, trae la elegida con /desde-catalogo y recarga', async () => {
    post.mockResolvedValue({ ...fila(9, { nombre: 'Suipacha', catalogo_id: '06784020' }) })
    abrir()
    await screen.findByText('Tomás Jofré')
    fireEvent.click(screen.getByRole('button', { name: /Agregar del catálogo/ }))
    const dialogo = await screen.findByRole('dialog')
    const campo = within(dialogo).getByRole('combobox', { name: 'Buscar localidad' })
    fireEvent.focus(campo)
    fireEvent.change(campo, { target: { value: 'suip' } })
    const opcion = await within(dialogo).findByRole('option', { name: /Suipacha — Buenos Aires/ })
    // Esa ya está en el maestro (fila 1 con el mismo código): se avisa, pero no se impide.
    expect(opcion).toHaveTextContent('Ya cargada')

    const antes = get.mock.calls.filter((c) => c[0] === '/api/localidades').length
    fireEvent.click(opcion)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades/desde-catalogo', { catalogo_id: '06784020' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await waitFor(() => expect(get.mock.calls.filter((c) => c[0] === '/api/localidades').length).toBe(antes + 1))
  })

  it('🔑 «Agregar del catálogo» busca en todos los países y se acota con el desplegable: ?pais=', async () => {
    post.mockResolvedValue(fila(11, { nombre: 'Nueva Palmira', provincia: 'Colonia', pais: 'UY', catalogo_id: 'UY-1' }))
    abrir()
    await screen.findByText('Tomás Jofré')
    fireEvent.click(screen.getByRole('button', { name: /Agregar del catálogo/ }))
    const dialogo = await screen.findByRole('dialog')
    const pais = within(dialogo).getByLabelText('País')
    expect(pais).toHaveValue('todos')
    const campo = within(dialogo).getByRole('combobox', { name: 'Buscar localidad' })
    fireEvent.focus(campo)
    fireEvent.change(campo, { target: { value: 'palm' } })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/geo/localidades?q=palm&limite=20&pais=todos'))

    fireEvent.change(pais, { target: { value: 'UY' } })
    const opcion = await within(dialogo).findByRole('option', { name: /Nueva Palmira — Colonia \(Uruguay\)/ })
    expect(get).toHaveBeenCalledWith('/api/geo/localidades?q=palm&limite=20&pais=UY')
    fireEvent.click(opcion)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades/desde-catalogo', { catalogo_id: 'UY-1' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('si la que trae ya estaba pero de baja, lo avisa en vez de dejar creer que quedó lista', async () => {
    post.mockResolvedValue(fila(1, { nombre: 'Suipacha', catalogo_id: '06784020', activo: false }))
    abrir()
    await screen.findByText('Tomás Jofré')
    fireEvent.click(screen.getByRole('button', { name: /Agregar del catálogo/ }))
    const dialogo = await screen.findByRole('dialog')
    const campo = within(dialogo).getByRole('combobox', { name: 'Buscar localidad' })
    fireEvent.focus(campo)
    fireEvent.change(campo, { target: { value: 'suip' } })
    fireEvent.click(await within(dialogo).findByRole('option', { name: /Suipacha — Buenos Aires/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ya estaba cargada pero está dada de baja')
  })

  it('«Cargar paraje» pide nombre y provincia y crea con es_paraje: true', async () => {
    post.mockResolvedValue(fila(10, { nombre: 'Paraje Los Ceibos', provincia: 'Santa Fe', es_paraje: true }))
    abrir()
    await screen.findByText('Tomás Jofré')
    fireEvent.click(screen.getByRole('button', { name: /Cargar paraje/ }))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Nombre del paraje'), { target: { value: 'Paraje Los Ceibos' } })
    await elegirEnBuscable(within(dialogo).getByRole('combobox', { name: 'Provincia' }), 'Santa Fe')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cargar paraje' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades', {
      nombre: 'Paraje Los Ceibos', provincia: 'Santa Fe', pais: 'AR', es_paraje: true, activo: true,
    }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('«Cargar paraje» en otro país: provincias de ese país y pais en el POST', async () => {
    post.mockResolvedValue(fila(12, { nombre: 'Estancia Don Pedro', provincia: 'Colonia', pais: 'UY', es_paraje: true }))
    abrir()
    await screen.findByText('Tomás Jofré')
    fireEvent.click(screen.getByRole('button', { name: /Cargar paraje/ }))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Nombre del paraje'), { target: { value: 'Estancia Don Pedro' } })
    await within(dialogo).findByRole('option', { name: 'Uruguay' })
    fireEvent.change(within(dialogo).getByLabelText('País'), { target: { value: 'UY' } })
    await elegirEnBuscable(within(dialogo).getByRole('combobox', { name: 'Provincia' }), 'Colonia')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cargar paraje' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades', {
      nombre: 'Estancia Don Pedro', provincia: 'Colonia', pais: 'UY', es_paraje: true, activo: true,
    }))
    expect(get).toHaveBeenCalledWith('/api/geo/provincias?pais=UY')
  })

  it('ya no hay un «Nuevo» que deje tipear el nombre sin pasar por el catálogo', async () => {
    abrir()
    await screen.findByText('Tomás Jofré')
    expect(screen.queryByRole('button', { name: /^Nuevo/ })).toBeNull()
  })
})
