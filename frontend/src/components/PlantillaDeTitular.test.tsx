/** El editor de la plantilla de un titular (ADR-044): los datos habituales con que arranca «Emitir carta de porte».
 *
 *  Lo que se prueba es que use **las mismas claves y las mismas reglas que el asistente**, que lo guardado sea exactamente lo
 *  que `propuesta()` del servidor lee, que nada sea obligatorio, que un dato que ARCA no lista no se pierda en silencio y que
 *  un operador mire sin tocar.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable, opcionesDe } from '@/test/buscable'

const get = vi.fn()
const put = vi.fn()
const del = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put, del, postForm: vi.fn() } }
})

const { PlantillaDeTitular } = await import('./PlantillaDeTitular')
const { ApiError } = await import('libra-ui/api-client')

const RUTA = '/api/cartas-porte'
const TITULAR = '30111111112'
const OTRO_DELEGADO = '30222222223'

const titular = (extra: Record<string, unknown> = {}) => ({
  id: 5, cuit: TITULAR, razon_social: 'Agro Delegado SA', emite: 'nosotros' as const, activo: true, notas: null,
  delegacion: 'delegado' as const, tercero: null, tiene_plantilla: true, ...extra,
})

/** Lo que `emitir` deja en `plantillas_cpe`: con nulos y vacíos, tal como sale del asistente. */
const GUARDADA = {
  sucursal: 1,
  origen: { tipo: 'campo', cod_provincia: 12, cod_localidad: 3456, planta: null, renspa: '01.001.0.00001/00' },
  cod_grano: 15, cosecha: 2526,
  destino: { cuit: '30555555558', cod_provincia: 20, cod_localidad: 777, planta: 9, es_campo: false },
  cuit_destinatario: '30555555558',
  intervinientes: { cuitCorredorVentaPrimaria: '20123456786' },
  cuit_remitente_comercial_productor: null,
  mercaderia_fumigada: false, km: 320, observaciones: null,
}

let plantilla: { datos: Record<string, unknown>; existe: boolean; actualizada: string | null }
let catalogosFallan = false

function responder() {
  get.mockImplementation((ruta: string) => {
    if (ruta === `${RUTA}/titulares/5/plantilla`) return Promise.resolve(plantilla)
    if (ruta.includes('/catalogos/') && catalogosFallan) return Promise.reject(new ApiError(502, 'ARCA no contestó'))
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
      return Promise.resolve([{ codigo: 777, nombre: 'Rosario' }, { codigo: 778, nombre: 'Funes' }])
    }
    if (ruta.startsWith(`${RUTA}/catalogos/plantas`)) {
      return Promise.resolve([{ numero: 9, cod_provincia: 20, cod_localidad: 777 }])
    }
    return Promise.reject(new Error(`ruta inesperada: ${ruta}`))
  })
}

function abrir(props: Partial<Parameters<typeof PlantillaDeTitular>[0]> = {}) {
  const alCambiar = vi.fn()
  render(<PlantillaDeTitular titular={titular()} cuitParaCatalogos={OTRO_DELEGADO} puedeEditar alCambiar={alCambiar}
                             {...props} />)
  return { alCambiar }
}

beforeEach(() => {
  get.mockReset(); put.mockReset(); del.mockReset()
  plantilla = { datos: GUARDADA, existe: true, actualizada: '2026-10-08T15:00:00-03:00' }
  catalogosFallan = false
  responder()
})

describe('Plantilla del titular · lo que muestra', () => {
  it('trae lo guardado, con los catálogos de ARCA por nombre y no por código', async () => {
    abrir()
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    expect(screen.getByLabelText('Cosecha')).toHaveValue('2526')
    expect(screen.getByLabelText('Provincia de origen')).toHaveValue('Córdoba')
    await waitFor(() => expect(screen.getByLabelText('Localidad de origen')).toHaveValue('Suipacha'))
    expect(screen.getByLabelText('RENSPA')).toHaveValue('01.001.0.00001/00')
    expect(screen.getByLabelText('CUIT del destino')).toHaveValue('30-55555555-8')
    await waitFor(() => expect(screen.getByLabelText('Localidad de destino')).toHaveValue('Rosario'))
    expect(screen.getByLabelText('CUIT del destinatario')).toHaveValue('30-55555555-8')
    expect(screen.getByLabelText('Kilómetros habituales')).toHaveValue('320')
    expect(screen.getByLabelText('Corredor (venta primaria)')).toHaveValue('20-12345678-6')
    // Con un interviniente cargado, la sección se ve abierta.
    expect(screen.getByText('Intervinientes (opcionales)').closest('details')).toHaveAttribute('open')
  })

  it('un titular delegado pide los catálogos con su propio CUIT; uno que no, con el que el ticket deja operar', async () => {
    abrir()
    await waitFor(() => expect(get).toHaveBeenCalledWith(`${RUTA}/catalogos/granos?cuit_titular=${TITULAR}`))
    get.mockClear()
    abrir({ titular: titular({ id: 5, delegacion: 'pendiente' }) })
    await waitFor(() => expect(get).toHaveBeenCalledWith(`${RUTA}/catalogos/granos?cuit_titular=${OTRO_DELEGADO}`))
  })

  it('ofrece las plantas del CUIT del destino', async () => {
    abrir()
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      `${RUTA}/catalogos/plantas?cuit_titular=${TITULAR}&cuit=30555555558`))
    const planta = await screen.findByLabelText('N.º de planta de destino')
    await waitFor(() => expect(opcionesDe(planta)).toContain('Planta 9'))
  })

  it('una plantilla que todavía no existe arranca vacía, sin inventar valores', async () => {
    plantilla = { datos: {}, existe: false, actualizada: null }
    abrir()
    await screen.findByRole('region', { name: 'Datos habituales para emitir' })
    expect(screen.getByLabelText('Cosecha')).toHaveValue('')
    expect(screen.getByLabelText('Grano')).toHaveValue('Elegir…')
    expect(screen.queryByRole('button', { name: 'Borrar plantilla' })).toBeNull()
  })
})

describe('Plantilla del titular · guardar', () => {
  it('🔑 guarda con las claves que lee la propuesta: sin nulos, sin vacíos, con el CUIT en dígitos', async () => {
    put.mockImplementation((_r: string, cuerpo: { datos: unknown }) =>
      Promise.resolve({ datos: cuerpo.datos, existe: true, actualizada: '2026-10-08T16:00:00-03:00' }))
    const { alCambiar } = abrir()
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    await elegirEnBuscable(screen.getByLabelText('Grano'), 'Maíz')
    fireEvent.change(screen.getByLabelText('Cosecha'), { target: { value: '2627' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar plantilla' }))

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    expect(put.mock.calls[0][0]).toBe(`${RUTA}/titulares/5/plantilla`)
    expect(put.mock.calls[0][1]).toEqual({
      datos: {
        origen: { tipo: 'campo', cod_provincia: 12, cod_localidad: 3456, renspa: '01.001.0.00001/00' },
        cod_grano: 23, cosecha: 2627,
        destino: { cuit: '30555555558', cod_provincia: 20, cod_localidad: 777, planta: 9, es_campo: false },
        cuit_destinatario: '30555555558',
        intervinientes: { cuitCorredorVentaPrimaria: '20123456786' },
        km: 320,
      },
    })
    expect(await screen.findByText(/Plantilla guardada/)).toBeInTheDocument()
    expect(alCambiar).toHaveBeenCalled()
  })

  it('todo es opcional: una plantilla con sólo el grano se guarda', async () => {
    plantilla = { datos: {}, existe: false, actualizada: null }
    put.mockResolvedValue({ datos: { cod_grano: 15 }, existe: true, actualizada: null })
    abrir()
    await screen.findByRole('region', { name: 'Datos habituales para emitir' })
    await elegirEnBuscable(screen.getByLabelText('Grano'), 'Soja')
    fireEvent.click(screen.getByRole('button', { name: 'Guardar plantilla' }))
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    expect(put.mock.calls[0][1]).toEqual({ datos: { cod_grano: 15 } })
  })

  it('🔑 mismas reglas que el asistente: una cosecha de tres cifras o un CUIT corto bloquean el guardado', async () => {
    abrir()
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    fireEvent.change(screen.getByLabelText('Cosecha'), { target: { value: '252' } })
    fireEvent.change(screen.getByLabelText('CUIT del destinatario'), { target: { value: '3055555' } })
    expect(await screen.findByText('Cuatro cifras (2526 = 2025/2026)')).toBeInTheDocument()
    expect(screen.getByText('Un CUIT tiene 11 dígitos')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guardar plantilla' })).toBeDisabled()
    expect(screen.getByText('Hay 2 datos con error.')).toBeInTheDocument()
    // Lo vacío no es un error: borrar el CUIT corto lo arregla.
    fireEvent.change(screen.getByLabelText('CUIT del destinatario'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Cosecha'), { target: { value: '2526' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar plantilla' })).toBeEnabled())
  })

  it('cambiar la provincia limpia la localidad y pide las de la nueva', async () => {
    abrir()
    await waitFor(() => expect(screen.getByLabelText('Localidad de origen')).toHaveValue('Suipacha'))
    await elegirEnBuscable(screen.getByLabelText('Provincia de origen'), 'Santa Fe')
    expect(screen.getByLabelText('Localidad de origen')).toHaveValue('Elegir…')
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      `${RUTA}/catalogos/localidades?cuit_titular=${TITULAR}&provincia=20`))
  })

  it('un rechazo del servidor se lee tal cual, al lado del botón', async () => {
    put.mockRejectedValue(new ApiError(422, 'interviniente desconocido: cuitInventado'))
    abrir()
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    fireEvent.click(screen.getByRole('button', { name: 'Guardar plantilla' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('interviniente desconocido: cuitInventado')
  })
})

describe('Plantilla del titular · cuando ARCA no responde', () => {
  it('🔴 el catálogo caído se dice, y lo ya guardado no se pierde: se ve y se vuelve a guardar igual', async () => {
    catalogosFallan = true
    put.mockResolvedValue({ datos: {}, existe: true, actualizada: null })
    abrir()
    expect(await screen.findByText('ARCA no contestó')).toBeInTheDocument()
    // Sin el nombre de ARCA, el código queda a la vista en vez de un campo vacío.
    expect(screen.getByLabelText('Grano')).toHaveValue('Grano 15')
    expect(screen.getByLabelText('Provincia de origen')).toHaveValue('Provincia 12')
    fireEvent.click(screen.getByRole('button', { name: 'Guardar plantilla' }))
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    expect(put.mock.calls[0][1].datos).toMatchObject({ cod_grano: 15, origen: { cod_provincia: 12, cod_localidad: 3456 } })
  })

  it('sin ningún delegado con quien pedir los catálogos lo dice y no pide nada a ARCA', async () => {
    abrir({ titular: titular({ delegacion: 'sin_verificar' }), cuitParaCatalogos: null })
    expect(await screen.findByText(/todavía no hay ninguno/)).toBeInTheDocument()
    expect(get.mock.calls.some(([r]) => String(r).includes('/catalogos/'))).toBe(false)
    expect(screen.getByLabelText('Grano')).toHaveValue('Grano 15')
  })
})

describe('Plantilla del titular · quién la toca', () => {
  it('un operador la mira: campos apagados y sin Guardar ni Borrar', async () => {
    abrir({ puedeEditar: false })
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    expect(screen.getByLabelText('Cosecha')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Guardar plantilla' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Borrar plantilla' })).toBeNull()
  })

  it('«Borrar plantilla» pide confirmar, la borra y deja el editor vacío', async () => {
    del.mockResolvedValue(undefined)
    const { alCambiar } = abrir()
    await waitFor(() => expect(screen.getByLabelText('Grano')).toHaveValue('Soja'))
    fireEvent.click(screen.getByRole('button', { name: 'Borrar plantilla' }))
    expect(del).not.toHaveBeenCalled()
    const confirmacion = await screen.findByRole('alertdialog')
    fireEvent.click(within(confirmacion).getByRole('button', { name: 'Borrar' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith(`${RUTA}/titulares/5/plantilla`))
    await waitFor(() => expect(screen.getByLabelText('Cosecha')).toHaveValue(''))
    expect(alCambiar).toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Borrar plantilla' })).toBeNull()
  })

  it('si no se puede leer la plantilla lo dice', async () => {
    get.mockImplementation(() => Promise.reject(new ApiError(404, 'no existe el titular 5')))
    abrir()
    expect(await screen.findByRole('alert')).toHaveTextContent('no existe el titular 5')
  })
})
