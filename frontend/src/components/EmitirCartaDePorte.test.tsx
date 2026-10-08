/** «Emitir carta de porte» (ADR-043): lo que el asistente decide y el backend no puede.
 *
 *  El titular que se elige a mano, la emisión apagada que no deja avanzar, el check de confirmación en producción,
 *  el único envío, y sobre todo: tras un 502/500 NO se ofrece reintentar, porque emitir de nuevo es duplicar una carta
 *  de porte real. Las reglas de fondo son del servidor y su texto se muestra tal cual.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable, opcionesDe } from '@/test/buscable'

// El asistente tiene muchos campos y el CI es lento: el segundo por defecto de `waitFor` no siempre alcanza.
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
  return { ApiError, api: { get, post, put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { EmitirCartaDePorte } = await import('./EmitirCartaDePorte')

const TITULAR = '30222222223'
const RUTA = '/api/cartas-porte'

const ORDEN = {
  id: 12, estado: 'pendiente',
} as unknown as import('@/api/ordenes').Orden

/** El listado de titulares (ADR-044): el delegado y cargado es el único que el asistente ofrece sin marca. */
const titular = (extra: Record<string, unknown> = {}) => ({
  id: 1, cuit: TITULAR, razon_social: 'Agropecuaria Los Talas', emite: 'nosotros', activo: true, notas: null,
  delegacion: 'delegado', tercero: null, tiene_plantilla: false, ...extra,
})
const TITULARES = {
  ambiente: 'produccion', verificado: true, motivo: null, cuit_para_catalogos: TITULAR,
  titulares: [titular()], sin_cargar: [],
}
const ESTADO_PRODUCCION = { ambiente: 'produccion', habilitada: true, puede_emitir: true }
const ESTADO_HOMOLOGACION = { ambiente: 'homologacion', habilitada: false, puede_emitir: true }

const PROPUESTA = {
  orden_id: 12, cuit_titular: TITULAR, sucursal: 1,
  origen: { tipo: 'campo', cod_provincia: 12, cod_localidad: 3456, renspa: null },
  cod_grano: 15, cosecha: 2526, peso_bruto: 44000, peso_tara: 14500,
  destino: { cuit: '30555555558', cod_provincia: 20, cod_localidad: 777, planta: 9, es_campo: false },
  cuit_destinatario: '30555555558',
  intervinientes: {}, cuit_remitente_comercial_productor: null,
  transporte: {
    cuit_transportista: '30999999995', dominios: ['ab123cd', 'EF456GH'], fecha_hora_partida: null, km: 320,
    cuit_chofer: '20333333336', cuit_pagador_flete: '30111111118', tarifa: '19724.73', mercaderia_fumigada: false,
  },
  observaciones: null, de_plantilla: false, faltantes: [] as string[],
}

const EMITIDA = {
  id: 77, nro_ctg: 10123456781, numero: '00001-00072413', estado: 'AC', estado_descripcion: 'Activa',
  ambiente: 'produccion', tiene_pdf: true, peso_neto: 29500, km: 320, emitida: true,
  origen: { cuit: null, nombre: null }, destino: { cuit: '30555555558', nombre: null },
}

type Rutas = {
  estado?: unknown
  titulares?: unknown
  propuesta?: unknown
  plantas?: unknown
}

function responder({
  estado = ESTADO_PRODUCCION, titulares = TITULARES, propuesta = PROPUESTA, plantas = [],
}: Rutas = {}) {
  get.mockImplementation((ruta: string) => {
    if (ruta === `${RUTA}/emision/estado`) return Promise.resolve(estado)
    if (ruta === `${RUTA}/titulares`) return Promise.resolve(titulares)
    if (ruta.startsWith(`${RUTA}/emision/propuesta`)) return Promise.resolve(propuesta)
    if (ruta.startsWith(`${RUTA}/catalogos/granos`)) {
      return Promise.resolve([{ codigo: 15, nombre: 'Soja' }, { codigo: 23, nombre: 'Maíz' }])
    }
    if (ruta.startsWith(`${RUTA}/catalogos/provincias`)) {
      return Promise.resolve([{ codigo: 12, nombre: 'Córdoba' }, { codigo: 20, nombre: 'Santa Fe' }])
    }
    if (ruta.includes('/catalogos/localidades') && ruta.endsWith('provincia=12')) {
      return Promise.resolve([{ codigo: 3456, nombre: 'Suipacha' }])
    }
    if (ruta.includes('/catalogos/localidades') && ruta.endsWith('provincia=20')) {
      return Promise.resolve([{ codigo: 777, nombre: 'Rosario' }])
    }
    if (ruta.startsWith(`${RUTA}/catalogos/plantas`)) return Promise.resolve(plantas)
    if (ruta.endsWith('/enlace')) {
      return Promise.resolve({ url: 'https://app.test/api/publico/cpe/77/1792000000/abc.pdf', vence: '2026-10-15T12:00:00+00:00' })
    }
    return Promise.reject(new Error(`ruta inesperada: ${ruta}`))
  })
}

async function error(status: number, detail: string) {
  const { ApiError } = await import('libra-ui/api-client')
  return new (ApiError as unknown as new (s: number, d: string) => Error)(status, detail)
}

function abrir() {
  render(
    <MemoryRouter>
      <EmitirCartaDePorte orden={ORDEN} abierto alCambiar={() => {}} />
    </MemoryRouter>)
}

/** Elige el titular y pasa a los datos; espera a que la propuesta esté en pantalla. */
async function irALosDatos() {
  await elegirEnBuscable(await screen.findByLabelText('A nombre de'), 'Agropecuaria Los Talas')
  const siguiente = screen.getByRole('button', { name: 'Siguiente' })
  await waitFor(() => expect(siguiente).toBeEnabled())
  fireEvent.click(siguiente)
  await screen.findByLabelText('Peso bruto (kg)')
}

async function irARevisar() {
  await irALosDatos()
  const revisar = screen.getByRole('button', { name: 'Revisar' })
  await waitFor(() => expect(revisar).toBeEnabled())
  fireEvent.click(revisar)
  await screen.findByText('Kilos')
}

beforeEach(() => {
  get.mockReset(); post.mockReset()
  responder()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('Emitir carta de porte · paso 1, el titular', () => {
  it('«A nombre de» no tiene valor por defecto, ni siquiera con un único titular', async () => {
    abrir()
    const titular = await screen.findByLabelText('A nombre de')
    await waitFor(() => expect(opcionesDe(titular)).toContain('Agropecuaria Los Talas'))
    // Sin elegir: el campo muestra la opción vacía («Elegir…»), no un titular.
    expect(titular).toHaveValue('Elegir…')
    // Sin elegir no se puede avanzar, aunque la emisión esté habilitada.
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled()
    await elegirEnBuscable(titular, 'Agropecuaria Los Talas')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Siguiente' })).toBeEnabled())
  })

  it('con la emisión real apagada dice por qué y no deja avanzar, aunque se elija un titular', async () => {
    responder({ estado: { ambiente: 'produccion', habilitada: false, puede_emitir: false } })
    abrir()
    expect(await screen.findByText(
      'La emisión real está apagada. La habilita un administrador en Configuración / ARCA.')).toBeInTheDocument()
    await elegirEnBuscable(await screen.findByLabelText('A nombre de'), 'Agropecuaria Los Talas')
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled()
    // Nunca se pidió la propuesta.
    expect(get.mock.calls.some(([r]) => String(r).includes('/emision/propuesta'))).toBe(false)
  })

  it('sin certificado de CTG y Carta de Porte lo dice y tampoco deja avanzar', async () => {
    responder({ estado: { ambiente: null, habilitada: false, puede_emitir: false } })
    abrir()
    expect(await screen.findByText(/No hay un certificado de «CTG y Carta de Porte» cargado/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled()
  })
})

describe('Emitir carta de porte · paso 1, a nombre de quién se ofrece (ADR-044)', () => {
  const SIN_CARGAR = '30444444445'
  const LISTA = {
    ...TITULARES,
    titulares: [
      titular(),
      titular({ id: 2, cuit: '30111111112', razon_social: 'Emite Solo SA', emite: 'titular', delegacion: 'no_aplica' }),
      titular({ id: 3, cuit: '30333333334', razon_social: 'Pendiente SA', delegacion: 'pendiente' }),
      titular({ id: 4, cuit: '30666666667', razon_social: 'De Baja SA', activo: false }),
    ],
    sin_cargar: [{ cuit: SIN_CARGAR, tercero: { id: 9, razon_social: 'Campo Nuevo SA' } }],
  }

  it('🔑 ofrece sólo a los que emitimos nosotros, activos y delegados en ARCA; no a los que emiten solos, pendientes o de baja', async () => {
    responder({ titulares: LISTA })
    abrir()
    const combo = await screen.findByLabelText('A nombre de')
    await waitFor(() => expect(opcionesDe(combo)).toContain('Agropecuaria Los Talas'))
    const opciones = opcionesDe(combo)
    expect(opciones).not.toContain('Emite Solo SA')
    expect(opciones).not.toContain('Pendiente SA')
    expect(opciones).not.toContain('De Baja SA')
  })

  it('🔑 un CUIT que ARCA trae y no está cargado también se ofrece, marcado, para no romper lo que ya andaba', async () => {
    responder({ titulares: LISTA })
    abrir()
    const combo = await screen.findByLabelText('A nombre de')
    await waitFor(() => expect(opcionesDe(combo)).toContain('Campo Nuevo SA · sin cargar en Titulares'))
    expect(screen.queryByText(/no está cargado en Cartas de porte/)).toBeNull()
    await elegirEnBuscable(combo, 'Campo Nuevo SA · sin cargar en Titulares')
    expect(screen.getByText(/no está cargado en Cartas de porte → Titulares/)).toBeInTheDocument()
    // Y se puede seguir: la propuesta se pide con ese CUIT, igual que antes.
    const siguiente = screen.getByRole('button', { name: 'Siguiente' })
    await waitFor(() => expect(siguiente).toBeEnabled())
    fireEvent.click(siguiente)
    await screen.findByLabelText('Peso bruto (kg)')
    expect(get).toHaveBeenCalledWith(`${RUTA}/emision/propuesta?orden_id=12&cuit_titular=${SIN_CARGAR}`)
  })

  it('si ARCA no se pudo consultar dice por qué y no ofrece a nadie (no se adivina una delegación)', async () => {
    responder({ titulares: {
      ...LISTA, verificado: false, motivo: 'ARCA no dio acceso al servicio de Carta de Porte: timeout',
      titulares: [titular({ delegacion: 'sin_verificar' })], sin_cargar: [],
    } })
    abrir()
    expect(await screen.findByText(/ARCA no dio acceso al servicio de Carta de Porte: timeout/)).toBeInTheDocument()
    expect(screen.queryByLabelText('A nombre de')).toBeNull()
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled()
  })

  it('si no queda ninguno para ofrecer lo dice y manda a la pestaña Titulares', async () => {
    responder({ titulares: { ...LISTA, titulares: [titular({ emite: 'titular', delegacion: 'no_aplica' })], sin_cargar: [] } })
    abrir()
    expect(await screen.findByText(/Ningún titular activo le delegó la emisión/)).toBeInTheDocument()
    expect(screen.getByText(/pestaña\s+Titulares/)).toBeInTheDocument()
  })
})

describe('Emitir carta de porte · paso 2, los datos', () => {
  it('llega precargado con la propuesta y calcula el neto', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-08T15:00:00-03:00'))
    abrir()
    await irALosDatos()

    // Pidió la propuesta de ESA orden para ESE titular.
    expect(get).toHaveBeenCalledWith(`${RUTA}/emision/propuesta?orden_id=12&cuit_titular=${TITULAR}`)
    // Los catálogos de ARCA se buscan escribiendo: el campo muestra el nombre, no el código.
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    expect(screen.getByLabelText('Cosecha')).toHaveValue('2526')
    expect(screen.getByText('2526 = 2025/2026')).toBeInTheDocument()
    expect(screen.getByLabelText('Peso bruto (kg)')).toHaveValue('44000')
    expect(screen.getByLabelText('Peso tara (kg)')).toHaveValue('14500')
    expect(screen.getByText('29.500 kg')).toBeInTheDocument()
    // El CUIT se ve con guiones; el transportista viene precargado y es editable.
    expect(screen.getByLabelText('CUIT del transportista')).toHaveValue('30-99999999-5')
    expect(screen.getByLabelText('CUIT del destino')).toHaveValue('30-55555555-8')
    // El destinatario es el destino por defecto.
    expect(screen.getByLabelText('CUIT del destinatario')).toHaveValue('30-55555555-8')
    expect(screen.getByLabelText('Dominio 1 (chasis)')).toHaveValue('AB123CD')
    expect(screen.getByLabelText('Dominio 2 (acoplado)')).toHaveValue('EF456GH')
    expect(screen.getByLabelText('Dominio 3 (acoplado)')).toHaveValue('')
    expect(screen.getByLabelText('Kilómetros a recorrer')).toHaveValue('320')
    // La partida se propone dentro de una hora, en hora argentina.
    expect(screen.getByLabelText('Fecha y hora de partida')).toHaveValue('2026-10-08T16:00')
    await waitFor(() => expect(screen.getByLabelText('Provincia de origen')).toHaveValue('Córdoba'))
    await waitFor(() => expect(screen.getByLabelText('Localidad de origen')).toHaveValue('Suipacha'))
    await waitFor(() => expect(screen.getByLabelText('Localidad de destino')).toHaveValue('Rosario'))
  })

  it('muestra los faltantes y marca los obligatorios vacíos: sin completarlos no se avanza', async () => {
    responder({
      propuesta: {
        ...PROPUESTA, de_plantilla: true,
        peso_tara: null,
        transporte: { ...PROPUESTA.transporte, cuit_chofer: null },
        faltantes: ['El chofer de la orden no tiene CUIT: cargalo en Entidades → Choferes.',
                    'Faltan los kilos de carga (bruto y tara) en la orden.'],
      },
    })
    abrir()
    await irALosDatos()

    const avisos = screen.getByRole('alert', { name: 'Avisos' })
    expect(within(avisos).getByText(/El chofer de la orden no tiene CUIT/)).toBeInTheDocument()
    expect(within(avisos).getByText(/Faltan los kilos de carga/)).toBeInTheDocument()
    expect(screen.getByText('Se completó con lo último emitido para este titular.')).toBeInTheDocument()

    // Los campos vacíos obligatorios quedan marcados.
    expect(screen.getByLabelText('CUIT del chofer')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Peso tara (kg)')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('Hay 2 datos obligatorios o con error.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revisar' })).toBeDisabled()

    // Completar lo que falta habilita el paso siguiente.
    fireEvent.change(screen.getByLabelText('CUIT del chofer'), { target: { value: '20333333336' } })
    fireEvent.change(screen.getByLabelText('Peso tara (kg)'), { target: { value: '14500' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Revisar' })).toBeEnabled())
  })

  it('la tara no puede ser mayor que el bruto', async () => {
    abrir()
    await irALosDatos()
    fireEvent.change(screen.getByLabelText('Peso tara (kg)'), { target: { value: '50000' } })
    expect(await screen.findByText('La tara tiene que ser menor que el peso bruto')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revisar' })).toBeDisabled()
  })

  it('ofrece las plantas de ARCA del CUIT del destino', async () => {
    responder({ plantas: [
      { numero: 9, cod_provincia: 20, cod_localidad: 777 }, { numero: 11, cod_provincia: 20, cod_localidad: 777 },
    ] })
    abrir()
    await irALosDatos()
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      `${RUTA}/catalogos/plantas?cuit_titular=${TITULAR}&cuit=30555555558`))
    const planta = await screen.findByLabelText('N.º de planta de destino')
    await waitFor(() => expect(opcionesDe(planta)).toContain('Planta 11'))
    expect(planta).toHaveValue('Planta 9')
  })
})

describe('Emitir carta de porte · paso 3, revisar y confirmar', () => {
  it('en producción: el recuadro de aviso y, sin el «Confirmo», no se puede emitir', async () => {
    abrir()
    await irARevisar()

    expect(screen.getByText(
      'Vas a emitir una Carta de Porte REAL ante ARCA a nombre de Agropecuaria Los Talas. Queda registrada y sólo se puede anular.',
    )).toBeInTheDocument()
    // El resumen se lee: origen → destino, grano, kilos, chofer, dominios, km.
    expect(screen.getByText('Suipacha, Córdoba')).toBeInTheDocument()
    expect(screen.getByText(/Rosario, Santa Fe · Planta 9/)).toBeInTheDocument()
    expect(screen.getByText(/Soja · cosecha 2526/)).toBeInTheDocument()
    expect(screen.getByText('44.000 bruto − 14.500 tara = 29.500 neto')).toBeInTheDocument()
    expect(screen.getByText('20-33333333-6')).toBeInTheDocument()
    expect(screen.getByText('AB123CD, EF456GH')).toBeInTheDocument()

    const emitir = screen.getByRole('button', { name: 'Emitir ahora' })
    expect(emitir).toBeDisabled()
    fireEvent.click(emitir)
    expect(post).not.toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('Confirmo'))
    expect(emitir).toBeEnabled()
    // Destildar vuelve a bloquear.
    fireEvent.click(screen.getByLabelText('Confirmo'))
    expect(emitir).toBeDisabled()
  })

  it('en homologación avisa que es de prueba y no pide el «Confirmo»', async () => {
    responder({ estado: ESTADO_HOMOLOGACION, titulares: { ...TITULARES, ambiente: 'homologacion' } })
    abrir()
    await irARevisar()
    expect(screen.getByText('Homologación: es de prueba, no tiene efecto fiscal.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Confirmo')).toBeNull()
    expect(screen.queryByText(/Carta de Porte REAL/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Emitir ahora' })).toBeEnabled()
  })

  it('«Atrás» conserva lo editado', async () => {
    abrir()
    await irALosDatos()
    fireEvent.change(screen.getByLabelText('Kilómetros a recorrer'), { target: { value: '410' } })
    fireEvent.click(screen.getByRole('button', { name: 'Revisar' }))
    await screen.findByText('Kilos')
    fireEvent.click(screen.getByRole('button', { name: 'Atrás' }))
    expect(await screen.findByLabelText('Kilómetros a recorrer')).toHaveValue('410')
    // Y volver hasta el titular y seguir con el mismo no vuelve a pedir la propuesta (se perderían las ediciones).
    fireEvent.click(screen.getByRole('button', { name: 'Atrás' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Siguiente' }))
    expect(await screen.findByLabelText('Kilómetros a recorrer')).toHaveValue('410')
    expect(get.mock.calls.filter(([r]) => String(r).includes('/emision/propuesta'))).toHaveLength(1)
  })
})

describe('Emitir carta de porte · emitir', () => {
  it('manda lo editado con el «Confirmo» y muestra el CTG y el número', async () => {
    post.mockResolvedValue(EMITIDA)
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))

    expect(await screen.findByText('10123456781')).toBeInTheDocument()
    expect(screen.getByText('00001-00072413')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver PDF' })).toHaveAttribute('href', '/api/cartas-porte/77/pdf')

    expect(post).toHaveBeenCalledTimes(1)
    const [ruta, cuerpo] = post.mock.calls[0]
    expect(ruta).toBe(`${RUTA}/emision/emitir`)
    expect(cuerpo.orden_id).toBe(12)
    expect(cuerpo.confirmo).toBe(true)
    const d = cuerpo.datos
    expect(d.cuit_titular).toBe(TITULAR)
    expect(d.cod_grano).toBe(15)
    expect(d.cosecha).toBe(2526)
    expect(d.peso_bruto).toBe(44000)
    expect(d.peso_tara).toBe(14500)
    expect(d.origen).toEqual({ tipo: 'campo', cod_provincia: 12, cod_localidad: 3456, renspa: null })
    expect(d.destino).toEqual({
      cuit: '30555555558', cod_provincia: 20, cod_localidad: 777, planta: 9, es_campo: false,
    })
    expect(d.cuit_destinatario).toBe('30555555558')
    // Los CUIT viajan sin guiones, los dominios en mayúsculas y la partida con la zona de Argentina.
    expect(d.transporte.cuit_transportista).toBe('30999999995')
    expect(d.transporte.dominios).toEqual(['AB123CD', 'EF456GH'])
    expect(d.transporte.fecha_hora_partida).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00-03:00$/)
    expect(d.transporte.km).toBe(320)
    expect(d.transporte.tarifa).toBe('19724.73')
  })

  it('un solo envío: mientras se envía el botón está deshabilitado y un segundo clic no manda otro', async () => {
    let terminar: (v: unknown) => void = () => {}
    post.mockImplementation(() => new Promise((r) => { terminar = r }))
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    const emitir = screen.getByRole('button', { name: 'Emitir ahora' })
    fireEvent.click(emitir)
    fireEvent.click(emitir)

    const enviando = await screen.findByRole('button', { name: 'Emitiendo…' })
    expect(enviando).toBeDisabled()
    fireEvent.click(enviando)
    expect(post).toHaveBeenCalledTimes(1)

    terminar(EMITIDA)
    expect(await screen.findByText('10123456781')).toBeInTheDocument()
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('un 422 se muestra tal cual y se puede corregir y volver a enviar', async () => {
    post.mockRejectedValueOnce(await error(422, 'ARCA rechazó la carta de porte: 1015 el solicitante no es productor'))
    post.mockResolvedValueOnce(EMITIDA)
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))
    expect(await screen.findByText('ARCA rechazó la carta de porte: 1015 el solicitante no es productor'))
      .toBeInTheDocument()
    // Fue un «no» antes de emitir: el botón sigue y se puede reintentar.
    const emitir = screen.getByRole('button', { name: 'Emitir ahora' })
    await waitFor(() => expect(emitir).toBeEnabled())
    fireEvent.click(emitir)
    expect(await screen.findByText('10123456781')).toBeInTheDocument()
    expect(post).toHaveBeenCalledTimes(2)
  })

  it('un 502 de emisión incierta se muestra en rojo y NO ofrece reintentar', async () => {
    const detalle = 'ARCA no contestó y no se sabe si emitió la carta de porte. No reintentes. (sucursal 1, número 73)'
    post.mockRejectedValue(await error(502, detalle))
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))

    const alerta = await screen.findByText(detalle)
    expect(alerta.closest('[role="alert"]')).toHaveTextContent('No la vuelvas a emitir')
    expect(screen.queryByRole('button', { name: /Emitir ahora|Emitiendo/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Reintentar|Atrás|Revisar/ })).toBeNull()
    // Lo único que se ofrece es ir a verificar.
    expect(screen.getByRole('link', { name: 'Ir a Cartas de porte' })).toHaveAttribute('href', '/cartas-porte')
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('un 500 «SE EMITIÓ» tampoco ofrece reintentar', async () => {
    const detalle = 'La Carta de Porte SE EMITIÓ en ARCA (CTG 10123456781, N.º 00001-00072413) pero no se pudo guardar acá: ' +
      'traela con «Traer de ARCA» con ese CTG. No la vuelvas a emitir.'
    post.mockRejectedValue(await error(500, detalle))
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))
    expect(await screen.findByText(detalle)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Emitir ahora/ })).toBeNull()
  })

  it('si la conexión se corta sin respuesta tampoco se reintenta: no se sabe si ARCA recibió el pedido', async () => {
    post.mockRejectedValue(new TypeError('Failed to fetch'))
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))
    expect(await screen.findByText(/No se supo si ARCA recibió el pedido \(Failed to fetch\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Emitir ahora/ })).toBeNull()
  })
})

describe('Emitir carta de porte · compartir', () => {
  it('«Compartir por WhatsApp» pide el enlace y abre wa.me con el texto ya escrito', async () => {
    post.mockResolvedValue(EMITIDA)
    const ventana = { opener: {}, location: { href: '' }, close: vi.fn() }
    const abrirVentana = vi.spyOn(window, 'open').mockReturnValue(ventana as unknown as Window)
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Compartir por WhatsApp' }))

    const url = 'https://app.test/api/publico/cpe/77/1792000000/abc.pdf'
    const texto = `Carta de porte 00001-00072413 · CTG 10123456781 · Suipacha → Rosario · 29.500 kg · 320 km. PDF: ${url}`
    await waitFor(() => expect(ventana.location.href).toBe(`https://wa.me/?text=${encodeURIComponent(texto)}`))
    expect(get).toHaveBeenCalledWith(`${RUTA}/77/enlace`)
    expect(abrirVentana).toHaveBeenCalledTimes(1)
    // La ventana se abrió en el mismo gesto del clic y quedó sin acceso a esta.
    expect(ventana.opener).toBeNull()
    // El enlace queda a la vista, y se puede copiar.
    expect(screen.getByLabelText('Enlace al PDF')).toHaveValue(url)
  })

  it('«Copiar enlace» lo copia al portapapeles', async () => {
    post.mockResolvedValue(EMITIDA)
    const escribir = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: escribir }, configurable: true })
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Copiar enlace' }))
    await waitFor(() => expect(escribir).toHaveBeenCalledWith('https://app.test/api/publico/cpe/77/1792000000/abc.pdf'))
    expect(await screen.findByText('Enlace copiado.')).toBeInTheDocument()
  })

  it('si el navegador bloquea la ventana queda el enlace de WhatsApp a mano', async () => {
    post.mockResolvedValue(EMITIDA)
    vi.spyOn(window, 'open').mockReturnValue(null)
    abrir()
    await irARevisar()
    fireEvent.click(screen.getByLabelText('Confirmo'))
    fireEvent.click(screen.getByRole('button', { name: 'Emitir ahora' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Compartir por WhatsApp' }))
    const enlace = await screen.findByRole('link', { name: 'Abrir WhatsApp' })
    expect(enlace.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/\?text=Carta%20de%20porte/)
  })
})
