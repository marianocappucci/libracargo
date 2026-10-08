/** Titulares de Carta de Porte (ADR-044): la pestaña de «Cartas de porte» donde se cargan los clientes que nos delegaron.
 *
 *  Lo que se prueba es lo que la pantalla decide: la pestaña y su URL, los estados de delegación tal como los informa el
 *  servidor (leídos de ARCA, no tildados), «Delegado sin cargar» con su «Agregar», que una pantalla sin ARCA no se rompe,
 *  las instrucciones armadas con los datos del certificado (nunca escritas a mano) y que sólo un administrador escribe.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
const del = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: string
    detailData?: unknown
    constructor(status: number, detail: string, detailData?: unknown) {
      super(detail); this.status = status; this.detail = detail; this.detailData = detailData
    }
  }
  return { ApiError, api: { get, post, put, del, postForm: vi.fn() } }
})

const sesion = vi.hoisted(() => ({ rol: 'admin' }))
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: sesion.rol, name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: CartasDePorte } = await import('./CartasDePorte')
const { ApiError } = await import('libra-ui/api-client')

const RUTA = '/api/cartas-porte'
// CUIT ficticios (nunca los de un cliente real).
const A = '30111111112'
const B = '30222222223'
const C = '30333333334'
const X = '30444444445'

const titular = (id: number, cuit: string, razon_social: string, extra: Record<string, unknown> = {}) => ({
  id, cuit, razon_social, emite: 'nosotros', activo: true, notas: null, delegacion: 'delegado', tercero: null,
  tiene_plantilla: false, ...extra,
})

const LISTADO = {
  ambiente: 'produccion', verificado: true, motivo: null, cuit_para_catalogos: A,
  titulares: [
    titular(1, A, 'Agro Delegado SA', { tercero: { id: 7, razon_social: 'Agro Delegado SA' }, tiene_plantilla: true }),
    titular(2, B, 'Agro Pendiente SA', { delegacion: 'pendiente' }),
    titular(3, C, 'Agro Solo SA', { emite: 'titular', delegacion: 'no_aplica' }),
  ],
  sin_cargar: [{ cuit: X, tercero: { id: 9, razon_social: 'Campo Nuevo SA' } }],
}

const INSTRUCCIONES = {
  disponible: true, ambiente: 'produccion', alias: 'libracargowscpeprod', cuit_representante: '20111111112', motivo: null,
}

let listado: unknown
let instrucciones: unknown

function responder() {
  get.mockImplementation((ruta: string) => {
    if (ruta === `${RUTA}/titulares`) return Promise.resolve(listado)
    if (ruta === `${RUTA}/titulares/instrucciones`) return Promise.resolve(instrucciones)
    if (/\/titulares\/\d+\/plantilla$/.test(ruta)) return Promise.resolve({ datos: {}, existe: false, actualizada: null })
    if (ruta.includes('/catalogos/')) return Promise.resolve([])
    if (ruta.startsWith('/api/terceros/rol/')) return Promise.resolve([{ id: 7, razon_social: 'Agro Delegado SA' }])
    return Promise.resolve([])
  })
}

function Ubicacion() {
  const { pathname, search } = useLocation()
  return <p data-testid="ubicacion">{pathname + search}</p>
}
const ubicacion = () => screen.getByTestId('ubicacion').textContent

function abrir(url = '/cartas-porte?pestana=titulares') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/cartas-porte" element={<><CartasDePorte /><Ubicacion /></>} />
      </Routes>
    </MemoryRouter>)
}

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset(); del.mockReset()
  sesion.rol = 'admin'
  listado = LISTADO
  instrucciones = INSTRUCCIONES
  responder()
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
})

describe('Titulares · la pestaña', () => {
  it('Cartas de porte tiene dos pestañas, Cartas y Titulares; sin parámetro abre el listado', async () => {
    abrir('/cartas-porte')
    const pestanas = await screen.findAllByRole('tab')
    expect(pestanas.map((t) => t.textContent)).toEqual(['Cartas', 'Titulares'])
    expect(screen.getByRole('tab', { name: 'Cartas' })).toHaveAttribute('data-state', 'active')
    expect(get).not.toHaveBeenCalledWith(`${RUTA}/titulares`)
  })

  it('🔑 la pestaña va en la URL: elegir Titulares escribe ?pestana=titulares, y volver al listado la borra', async () => {
    abrir('/cartas-porte')
    await screen.findAllByRole('tab')
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Titulares' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Titulares' }))
    await waitFor(() => expect(ubicacion()).toBe('/cartas-porte?pestana=titulares'))
    expect(await screen.findByText('Agro Delegado SA')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Cartas' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Cartas' }))
    await waitFor(() => expect(ubicacion()).toBe('/cartas-porte'))
  })

  it('«Nuevo titular» va en la línea del título, a la altura de «Cartas de porte»', async () => {
    abrir()
    const boton = await screen.findByRole('button', { name: /Nuevo titular/ })
    const linea = boton.closest('.no-imprimir')!.parentElement!
    expect(within(linea).getByText('Cartas de porte')).toBeInTheDocument()
  })
})

describe('Titulares · la delegación se lee de ARCA', () => {
  it('🔑 muestra cada estado que informa el servidor: Delegado ✓, Pendiente y Emite él', async () => {
    abrir()
    const tabla = await screen.findByRole('table')
    const fila = (nombre: string) => within(tabla).getByText(nombre).closest('tr') as HTMLElement
    expect(within(fila('Agro Delegado SA')).getByText('Delegado ✓')).toBeInTheDocument()
    expect(within(fila('Agro Pendiente SA')).getByText('Pendiente')).toBeInTheDocument()
    expect(within(fila('Agro Solo SA')).getByText('Emite él')).toBeInTheDocument()
    expect(within(fila('Agro Delegado SA')).getByText('30-11111111-2')).toBeInTheDocument()
    // Quién emite, y el vínculo con el cliente de Entidades.
    expect(within(fila('Agro Delegado SA')).getByText('Nosotros')).toBeInTheDocument()
    expect(within(fila('Agro Solo SA')).getByText('El titular')).toBeInTheDocument()
    expect(within(fila('Agro Delegado SA')).getByRole('link', { name: /Cliente: Agro Delegado SA/ }))
      .toHaveAttribute('href', '/entidades?pestana=clientes&ver=7')
  })

  it('explica que «Pendiente» se resuelve solo con el próximo ticket de ARCA (hasta 12 horas)', async () => {
    abrir()
    await screen.findByText('Agro Pendiente SA')
    expect(screen.getByText(/ARCA todavía no informa su delegación/)).toBeInTheDocument()
    expect(screen.getByText(/hasta 12 horas/)).toBeInTheDocument()
  })

  it('un CUIT que ARCA trae y no está cargado aparece como «Delegado sin cargar», con su entidad si la hay', async () => {
    abrir()
    const seccion = await screen.findByRole('region', { name: 'Delegados sin cargar' })
    expect(within(seccion).getByText('Campo Nuevo SA')).toBeInTheDocument()
    expect(within(seccion).getByText(/30-44444444-5/)).toBeInTheDocument()
    expect(within(seccion).getByText('Delegado sin cargar')).toBeInTheDocument()
  })

  it('«Agregar» abre el alta con el CUIT y el nombre de la entidad ya puestos, y lo da de alta', async () => {
    post.mockResolvedValue(titular(4, X, 'Campo Nuevo SA'))
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: /Agregar 30-44444444-5/ }))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('CUIT')).toHaveValue('30-44444444-5')
    expect(within(dialogo).getByLabelText('CUIT')).toBeDisabled()
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Campo Nuevo SA')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar titular' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post).toHaveBeenCalledWith(`${RUTA}/titulares`, {
      emite: 'nosotros', activo: true, notas: null, tercero_id: 9, cuit: X, razon_social: 'Campo Nuevo SA',
    })
    // Y recarga el listado para que el que se agregó salga de «sin cargar».
    await waitFor(() => expect(get.mock.calls.filter(([r]) => r === `${RUTA}/titulares`)).toHaveLength(2))
  })

  it('🔴 sin certificado o con ARCA caída la pantalla NO se rompe: dice el motivo y los estados quedan sin verificar', async () => {
    listado = {
      ...LISTADO, ambiente: null, verificado: false, cuit_para_catalogos: null, sin_cargar: [],
      motivo: 'No hay certificado de «CTG y Carta de Porte» cargado: cargalo en Configuración / ARCA.',
      titulares: [titular(1, A, 'Agro Delegado SA', { delegacion: 'sin_verificar' })],
    }
    abrir()
    expect(await screen.findByText('Agro Delegado SA')).toBeInTheDocument()
    expect(screen.getByText(/Sin verificar en ARCA/)).toBeInTheDocument()
    expect(screen.getByText(/cargalo en Configuración \/ ARCA/)).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Sin verificar')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Delegados sin cargar' })).toBeNull()
  })

  it('si el pedido mismo falla, lo dice y no deja la pantalla en blanco', async () => {
    get.mockImplementation((ruta: string) => ruta === `${RUTA}/titulares`
      ? Promise.reject(new ApiError(500, 'Error interno')) : Promise.resolve([]))
    abrir()
    expect(await screen.findByRole('alert')).toHaveTextContent('Error interno')
    expect(screen.getByText(/Todavía no hay titulares cargados/)).toBeInTheDocument()
  })
})

describe('Titulares · la ficha', () => {
  it('abre al tocar una fila: explica el estado y trae la plantilla', async () => {
    abrir()
    fireEvent.click(await screen.findByText('Agro Pendiente SA'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Pendiente SA')
    expect(within(dialogo).getByLabelText('CUIT')).toBeDisabled()
    expect(within(dialogo).getByText(/puede tardar hasta 12 horas/)).toBeInTheDocument()
    expect(await within(dialogo).findByRole('region', { name: 'Datos habituales para emitir' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith(`${RUTA}/titulares/2/plantilla`)
  })

  it('un titular «Pendiente» lleva las instrucciones de delegación con su nombre', async () => {
    abrir()
    fireEvent.click(await screen.findByText('Agro Pendiente SA'))
    const dialogo = await screen.findByRole('dialog')
    const texto = await within(dialogo).findByLabelText('Texto de las instrucciones')
    expect(texto).toHaveTextContent('en representación de Agro Pendiente SA')
  })

  it('un titular que emite él no lleva plantilla: no emitimos a su nombre', async () => {
    abrir()
    fireEvent.click(await screen.findByText('Agro Solo SA'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText(/no lleva datos habituales para emitir/)).toBeInTheDocument()
    expect(within(dialogo).queryByRole('region', { name: 'Datos habituales para emitir' })).toBeNull()
    expect(get).not.toHaveBeenCalledWith(`${RUTA}/titulares/3/plantilla`)
  })

  it('edita quién emite y las notas, y manda el CUIT afuera: no se cambia', async () => {
    put.mockResolvedValue(titular(2, B, 'Agro Pendiente SA', { emite: 'titular' }))
    abrir()
    fireEvent.click(await screen.findByText('Agro Pendiente SA'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByRole('radio', { name: /^El titular/ }))
    fireEvent.change(within(dialogo).getByLabelText('Notas'), { target: { value: 'Emite con su software' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    expect(put).toHaveBeenCalledWith(`${RUTA}/titulares/2`, {
      emite: 'titular', activo: true, notas: 'Emite con su software', tercero_id: null, razon_social: 'Agro Pendiente SA',
    })
  })

  it('un 409 del servidor (CUIT ya cargado) se lee en la ficha', async () => {
    post.mockRejectedValue(new ApiError(409, 'Ese CUIT ya está cargado como titular.'))
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: /Nuevo titular/ }))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('CUIT'), { target: { value: '30111111112' } })
    expect(within(dialogo).getByLabelText('CUIT')).toHaveValue('30-11111111-2')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar titular' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('Ese CUIT ya está cargado como titular.')
  })

  it('«Sacar de la lista» pide confirmar y borra', async () => {
    del.mockResolvedValue(undefined)
    abrir()
    fireEvent.click(await screen.findByText('Agro Pendiente SA'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Sacar de la lista' }))
    expect(del).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: 'Sacar' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith(`${RUTA}/titulares/2`))
  })

  it('?ver=<id> abre la ficha de ese titular (así llega el enlace de la ficha del cliente)', async () => {
    abrir('/cartas-porte?pestana=titulares&ver=3')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Solo SA')
    // Al cerrarla, el parámetro desaparece y la pestaña se queda.
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(ubicacion()).toBe('/cartas-porte?pestana=titulares'))
  })
})

describe('Titulares · sólo un administrador escribe', () => {
  beforeEach(() => { sesion.rol = 'operador' })

  it('un operador ve la lista pero no tiene «Nuevo titular» ni «Agregar»', async () => {
    abrir()
    expect(await screen.findByText('Agro Delegado SA')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Nuevo titular/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Agregar/ })).toBeNull()
    // «Delegado sin cargar» se ve igual: es información.
    expect(screen.getByRole('region', { name: 'Delegados sin cargar' })).toBeInTheDocument()
  })

  it('en la ficha mira, no toca: campos apagados y sin Guardar ni Sacar', async () => {
    abrir()
    fireEvent.click(await screen.findByText('Agro Delegado SA'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toBeDisabled()
    expect(within(dialogo).queryByRole('button', { name: 'Guardar' })).toBeNull()
    expect(within(dialogo).queryByRole('button', { name: 'Sacar de la lista' })).toBeNull()
    expect(within(dialogo).getByRole('button', { name: 'Cerrar' })).toBeInTheDocument()
  })
})

describe('Titulares · cómo delegarnos', () => {
  it('🔑 el texto se arma con el CUIT y el alias del certificado cargado', async () => {
    abrir()
    const seccion = await screen.findByRole('region', { name: 'Instrucciones de delegación' })
    const texto = await within(seccion).findByLabelText('Texto de las instrucciones')
    expect(texto).toHaveTextContent('CUIT 20-11111111-2')
    expect(texto).toHaveTextContent('elegir libracargowscpeprod (no el que termina en «homo»)')
    expect(texto).toHaveTextContent('Administrador de Relaciones de Clave Fiscal, actuando en representación del titular')
    expect(texto).toHaveTextContent('wscpe (Carta de Porte Electrónica)')
    expect(texto).toHaveTextContent('Confirmar dos veces')
  })

  it('🔴 no está escrito a mano: con otro certificado el texto cambia', async () => {
    instrucciones = { ...INSTRUCCIONES, alias: 'otrodominiowscpeprod', cuit_representante: '27222222224' }
    abrir()
    const texto = await screen.findByLabelText('Texto de las instrucciones')
    expect(texto).toHaveTextContent('CUIT 27-22222222-4')
    expect(texto).toHaveTextContent('otrodominiowscpeprod')
    expect(texto).not.toHaveTextContent('libracargowscpeprod')
    expect(texto).not.toHaveTextContent('20-11111111-2')
  })

  it('«Copiar» deja el texto en el portapapeles', async () => {
    const escribir = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: escribir }, configurable: true })
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: 'Copiar' }))
    await waitFor(() => expect(escribir).toHaveBeenCalledTimes(1))
    expect(escribir.mock.calls[0][0]).toContain('libracargowscpeprod')
    expect(await screen.findByText('Instrucciones copiadas.')).toBeInTheDocument()
  })

  it('«Compartir por WhatsApp» abre wa.me con el texto ya escrito', async () => {
    const abrirVentana = vi.spyOn(window, 'open').mockReturnValue(null)
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: 'Compartir por WhatsApp' }))
    expect(abrirVentana).toHaveBeenCalledTimes(1)
    const url = String(abrirVentana.mock.calls[0][0])
    expect(url.startsWith('https://wa.me/?text=')).toBe(true)
    expect(decodeURIComponent(url)).toContain('CUIT 20-11111111-2')
    abrirVentana.mockRestore()
  })

  it('sin certificado no inventa instrucciones: dice dónde cargarlo y no ofrece copiar', async () => {
    instrucciones = {
      disponible: false, ambiente: null, alias: null, cuit_representante: null,
      motivo: 'No hay certificado de «CTG y Carta de Porte» cargado: cargalo en Configuración / ARCA.',
    }
    abrir()
    const seccion = await screen.findByRole('region', { name: 'Instrucciones de delegación' })
    expect(await within(seccion).findByText(/cargalo en Configuración \/ ARCA/)).toBeInTheDocument()
    expect(within(seccion).queryByRole('button', { name: 'Copiar' })).toBeNull()
    expect(within(seccion).queryByLabelText('Texto de las instrucciones')).toBeNull()
  })

  it('con el certificado de homologación avisa que es de prueba', async () => {
    instrucciones = { ...INSTRUCCIONES, ambiente: 'homologacion', alias: 'libracargowscpehomo' }
    abrir()
    expect(await screen.findByText(/certificado de homologación/)).toBeInTheDocument()
    const texto = screen.getByLabelText('Texto de las instrucciones')
    expect(texto).toHaveTextContent('elegir libracargowscpehomo')
    expect(texto).not.toHaveTextContent('no el que termina en «homo»')
  })
})
