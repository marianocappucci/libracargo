/** Órdenes de carga con etapa, kilos y adjuntos (ADR-037, fase 2).
 *
 * Lo que se prueba es lo que la pantalla decide y el backend no puede: el neto que se calcula en el formulario, la
 * tara que no pasa al bruto, «Liquidada» como lectura de «facturada», y a qué endpoint va cada acción (la etapa a
 * `PUT /etapa` también en una facturada; los archivos a `/adjuntos`). Las reglas de fondo son del servidor y su
 * 422 se muestra tal cual.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// La sección «Flete» consulta la referencia con una espera de 250 ms antes de pedirla: en el CI, con este archivo
// tardando ~50 s, el segundo por defecto de `waitFor` no alcanza y el test falla por tiempo, no por lógica.
configure({ asyncUtilTimeout: 5000 })
// Y por lo mismo, el tiempo total de cada test: en el CI varios tests del flete pasan los 5 s por defecto de vitest.
vi.setConfig({ testTimeout: 20_000 })
// Y por lo mismo, el tiempo total de cada test: en el CI varios tests del flete pasan los 5 s por defecto de vitest.
vi.setConfig({ testTimeout: 20_000 })

const get = vi.fn()
const put = vi.fn()
const del = vi.fn()
const postForm = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put, del, postForm } }
})

const { default: Ordenes } = await import('./Ordenes')

/** La pastilla y no la opción del select, que dice lo mismo. */
const PASTILLA = { selector: '[data-tono]' }

const orden = (id: number, extra: Record<string, unknown> = {}) => ({
  id, fecha: '2026-10-05', cliente_id: 1, origen_id: 1, destino_id: 2,
  fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
  remito: `R-${id}`, cantidad: null, unidad: null,
  tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
  comision: '0.00', estado: 'pendiente', comprobante_id: null,
  observaciones: null, cantidad_legado: null, origen_legado: null,
  etapa: 'asignada',
  kg_bruto_carga: null, kg_tara_carga: null, kg_neto_carga: null,
  kg_bruto_descarga: null, kg_tara_descarga: null, kg_neto_descarga: null,
  km: null, tarifa_tonelada: null,
  ...extra,
})

const adjunto = (id: number, extra: Record<string, unknown> = {}) => ({
  id, orden_id: 1, nombre: `ticket-${id}.jpg`, tipo_contenido: 'image/jpeg', tamanio: 2_411_724,
  created_at: '2026-10-07T17:30:00-03:00', ...extra,
})

async function error(status: number, detail: string) {
  const { ApiError } = await import('libra-ui/api-client')
  return new (ApiError as unknown as new (s: number, d: string) => Error)(status, detail)
}

/** Un 404 como el del servidor: «no hay tarifario para esa fecha» o «ese cliente no tiene viaje con tarifa». */
const noHay = () => Promise.reject(Object.assign(new Error('no hay'), { status: 404 }))
/** Qué contesta `/api/tarifario/…` en cada test. Por omisión, nada: es el estado de un producto sin tarifario. */
let tarifarioDe: (ruta: string) => Promise<unknown> = noHay

function responder(ordenes: unknown[] = [], adjuntos: unknown[] = []) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/tarifario')) return tarifarioDe(ruta)
    if (ruta.includes('/adjuntos')) return Promise.resolve(adjuntos)
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) {
      return Promise.resolve([{ id: 1, razon_social: 'Agro Norte', es_cliente: true }])
    }
    if (ruta.startsWith('/api/localidades')) {
      return Promise.resolve([{ id: 1, nombre: 'Suipacha' }, { id: 2, nombre: 'Rosario' }])
    }
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({})
    return Promise.resolve([])
  })
}

function abrir() {
  render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
}

/** Abre el detalle de la orden con ese remito y devuelve el diálogo. */
async function verDetalle(remito: string) {
  fireEvent.click(await screen.findByText(remito))
  return await screen.findByRole('dialog')
}

beforeEach(() => {
  get.mockReset(); put.mockReset(); del.mockReset(); postForm.mockReset()
  tarifarioDe = noHay
  responder()
})

describe('Órdenes · listado con etapa y kilos', () => {
  it('muestra la etapa de cada orden; facturada se lee «Liquidada» y anulada «Anulada»', async () => {
    responder([
      orden(1, { etapa: 'en_viaje' }),
      orden(2, { etapa: 'cerrada', estado: 'facturada', comprobante_id: 9 }),
      orden(3, { etapa: 'descargada', estado: 'anulada' }),
    ])
    abrir()
    await screen.findByText('R-1')
    const tabla = screen.getByRole('table')
    expect(within(tabla).getByText('En viaje')).toBeInTheDocument()
    // La facturada no muestra «Cerrada» aunque su etapa lo sea: liquidada = facturada.
    expect(within(tabla).getByText('Liquidada')).toBeInTheDocument()
    expect(within(tabla).queryByText('Cerrada')).toBeNull()
    // La anulada tampoco muestra «Descargada».
    expect(within(tabla).getByText('Anulada')).toBeInTheDocument()
    expect(within(tabla).queryByText('Descargada')).toBeNull()
  })

  it('la pastilla de cada etapa lleva el tono que le toca', async () => {
    responder([
      orden(1, { etapa: 'asignada' }), orden(2, { etapa: 'cargada' }), orden(3, { etapa: 'descargada' }),
      orden(4, { etapa: 'cerrada' }), orden(5, { estado: 'facturada', comprobante_id: 9 }),
      orden(6, { estado: 'anulada' }),
    ])
    abrir()
    await screen.findByText('R-1')
    const tono = (texto: string) => within(screen.getByRole('table')).getByText(texto).getAttribute('data-tono')
    expect(tono('Asignada')).toBe('neutro')
    expect(tono('Cargada')).toBe('curso')
    expect(tono('Descargada')).toBe('atencion')
    expect(tono('Cerrada')).toBe('ok')
    expect(tono('Liquidada')).toBe('ok')
    expect(tono('Anulada')).toBe('negativo')
  })

  it('las columnas de kilos muestran el neto de carga y de descarga, o «—»', async () => {
    responder([
      orden(1, { kg_neto_carga: 29500, kg_neto_descarga: 29480 }),
      orden(2),
    ])
    abrir()
    await screen.findByText('R-1')
    const tabla = screen.getByRole('table')
    expect(within(tabla).getByText('29.500')).toBeInTheDocument()
    expect(within(tabla).getByText('29.480')).toBeInTheDocument()
    expect(within(tabla).getByText('Kg carga')).toBeInTheDocument()
    expect(within(tabla).getByText('Kg descarga')).toBeInTheDocument()
  })

  it('el filtro «Etapa» pide ?etapa=… al servidor, y «Todas» lo saca', async () => {
    responder([orden(1)])
    abrir()
    await screen.findByText('R-1')
    const filtro = screen.getByLabelText('Etapa')
    expect(Array.from(filtro.querySelectorAll('option')).map((o) => o.textContent))
      .toEqual(['Todas', 'Asignada', 'Cargada', 'En viaje', 'Descargada', 'Cerrada'])

    fireEvent.change(filtro, { target: { value: 'en_viaje' } })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/ordenes?etapa=en_viaje'))

    fireEvent.change(filtro, { target: { value: '' } })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/ordenes'))
  })
})

describe('Órdenes · formulario: kilos', () => {
  async function editar(extra: Record<string, unknown> = {}) {
    responder([orden(1, extra)])
    abrir()
    await screen.findByText('R-1')
    fireEvent.click(screen.getByLabelText('Editar'))
    return await screen.findByRole('dialog')
  }

  const escribir = (campo: string, valor: string) =>
    fireEvent.change(screen.getByLabelText(campo), { target: { value: valor } })

  it('tiene el select «Etapa» y dos filas de kilos, Carga y Descarga, con bruto, tara y neto', async () => {
    const dialogo = await editar({ etapa: 'cargada' })
    expect(within(dialogo).getByLabelText('Etapa')).toHaveValue('cargada')
    for (const tramo of ['carga', 'descarga']) {
      for (const parte of ['Bruto', 'Tara', 'Neto']) {
        expect(within(dialogo).getByLabelText(`${parte} de ${tramo}`)).toBeInTheDocument()
      }
    }
  })

  it('con bruto y tara completos el neto se calcula, no se puede tipear y es lo que se manda', async () => {
    const dialogo = await editar()
    escribir('Bruto de carga', '44000')
    expect(screen.getByLabelText('Neto de carga')).not.toHaveAttribute('readonly')
    escribir('Tara de carga', '14500')

    const neto = screen.getByLabelText('Neto de carga')
    expect(neto).toHaveValue('29500')
    expect(neto).toHaveAttribute('readonly')

    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][0]).toBe('/api/ordenes/1')
    expect(put.mock.calls[0][1]).toMatchObject({
      kg_bruto_carga: 44000, kg_tara_carga: 14500, kg_neto_carga: 29500,
      kg_bruto_descarga: null, kg_tara_descarga: null, kg_neto_descarga: null,
    })
  })

  it('un neto viejo que quedó tipeado no pisa al calculado', async () => {
    const dialogo = await editar()
    escribir('Neto de carga', '1')
    escribir('Bruto de carga', '10000')
    escribir('Tara de carga', '3000')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({ kg_neto_carga: 7000 })
  })

  it('sin bruto o sin tara el neto se carga a mano', async () => {
    const dialogo = await editar()
    escribir('Neto de descarga', '29480')
    expect(screen.getByLabelText('Neto de descarga')).not.toHaveAttribute('readonly')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({
      kg_bruto_descarga: null, kg_tara_descarga: null, kg_neto_descarga: 29480,
    })
  })

  it('🔴 tara mayor que el bruto: lo dice con el mensaje del backend y no manda nada', async () => {
    const dialogo = await editar()
    escribir('Bruto de carga', '10000')
    escribir('Tara de carga', '12000')
    fireEvent.click(within(dialogo).getByText('Guardar'))

    expect(await within(dialogo).findByText(
      'los kilos de carga: la tara (12000) no puede ser mayor que el bruto (10000)')).toBeInTheDocument()
    expect(put).not.toHaveBeenCalled()
    // Y con la tara pasada, el neto no se calcula: queda para tipearlo.
    expect(screen.getByLabelText('Neto de carga')).not.toHaveAttribute('readonly')
  })

  it('la tara pasada del bruto se controla por tramo: la descarga no depende de la carga', async () => {
    const dialogo = await editar()
    escribir('Bruto de descarga', '100')
    escribir('Tara de descarga', '200')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByText(/los kilos de descarga: la tara \(200\)/)).toBeInTheDocument()
  })

  it('edita una orden que ya trae kilos: los muestra y no los pierde', async () => {
    const dialogo = await editar({ kg_bruto_carga: 44000, kg_tara_carga: 14500, kg_neto_carga: 29500 })
    expect(screen.getByLabelText('Bruto de carga')).toHaveValue(44000)
    expect(screen.getByLabelText('Neto de carga')).toHaveValue('29500')
    expect(screen.getByLabelText('Bruto de descarga')).toHaveValue(null)
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({ kg_neto_carga: 29500, kg_bruto_descarga: null })
  })

  it('el 422 del servidor se muestra tal cual', async () => {
    const dialogo = await editar()
    put.mockRejectedValue(await error(422, 'los kilos de carga: el neto (5) no es bruto menos tara (10 - 3 = 7)'))
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('el neto (5) no es bruto menos tara')
  })
})

describe('Órdenes · detalle: etapa', () => {
  it('muestra los kilos y la etapa de la orden', async () => {
    responder([orden(1, {
      etapa: 'descargada',
      kg_bruto_carga: 44000, kg_tara_carga: 14500, kg_neto_carga: 29500, kg_neto_descarga: 29480,
    })])
    abrir()
    const detalle = await verDetalle('R-1')
    const kilos = within(detalle).getByRole('region', { name: 'Kilos' })
    expect(within(kilos).getByText('44.000')).toBeInTheDocument()
    expect(within(kilos).getByText('14.500')).toBeInTheDocument()
    expect(within(kilos).getByText('29.500')).toBeInTheDocument()
    expect(within(kilos).getByText('29.480')).toBeInTheDocument()
    expect(within(within(detalle).getByRole('region', { name: 'Etapa' })).getByText('Descargada', PASTILLA))
      .toBeInTheDocument()
  })

  it('«Siguiente etapa» llama PUT /etapa con la que sigue y actualiza la pastilla', async () => {
    responder([orden(1, { etapa: 'cargada' })])
    put.mockResolvedValue(orden(1, { etapa: 'en_viaje' }))
    abrir()
    const detalle = await verDetalle('R-1')

    fireEvent.click(within(detalle).getByRole('button', { name: /Siguiente etapa/ }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/ordenes/1/etapa', { etapa: 'en_viaje' }))
    const region = within(detalle).getByRole('region', { name: 'Etapa' })
    await waitFor(() => expect(within(region).getByText('En viaje', PASTILLA)).toBeInTheDocument())
    // Y la fila del listado también cambió, sin volver a pedir las órdenes.
    // (el modal esconde la tabla de los roles accesibles, por eso se busca por texto)
    expect(screen.getAllByText('En viaje', PASTILLA)).toHaveLength(2)
  })

  it('el select deja pasar a cualquier etapa, también para atrás', async () => {
    responder([orden(1, { etapa: 'cerrada' })])
    put.mockResolvedValue(orden(1, { etapa: 'descargada' }))
    abrir()
    const detalle = await verDetalle('R-1')

    fireEvent.change(within(detalle).getByLabelText('Etapa del viaje'), { target: { value: 'descargada' } })

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/ordenes/1/etapa', { etapa: 'descargada' }))
  })

  it('en la última etapa no hay «Siguiente»', async () => {
    responder([orden(1, { etapa: 'cerrada' })])
    abrir()
    const detalle = await verDetalle('R-1')
    expect(within(detalle).getByRole('button', { name: /Siguiente etapa/ })).toBeDisabled()
  })

  it('🔑 una orden facturada se lee «Liquidada» y igual cambia de etapa por PUT /etapa', async () => {
    responder([orden(1, { etapa: 'descargada', estado: 'facturada', comprobante_id: 9 })])
    put.mockResolvedValue(orden(1, { etapa: 'cerrada', estado: 'facturada', comprobante_id: 9 }))
    abrir()
    const detalle = await verDetalle('R-1')
    const region = within(detalle).getByRole('region', { name: 'Etapa' })
    expect(within(region).getByText('Liquidada', PASTILLA)).toBeInTheDocument()
    expect(within(detalle).getByLabelText('Etapa del viaje')).toHaveValue('descargada')

    fireEvent.click(within(detalle).getByRole('button', { name: /Siguiente etapa/ }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/ordenes/1/etapa', { etapa: 'cerrada' }))
    // Sigue liquidada: la etapa del viaje no cambia lo que es el estado de facturación.
    expect(within(region).getByText('Liquidada', PASTILLA)).toBeInTheDocument()
  })

  it('una anulada no cambia de etapa', async () => {
    responder([orden(1, { estado: 'anulada' })])
    abrir()
    const detalle = await verDetalle('R-1')
    expect(within(detalle).getByLabelText('Etapa del viaje')).toBeDisabled()
    expect(within(detalle).getByRole('button', { name: /Siguiente etapa/ })).toBeDisabled()
  })

  it('si el servidor rechaza el cambio, muestra el motivo y deja la etapa como estaba', async () => {
    responder([orden(1, { etapa: 'cargada' })])
    put.mockRejectedValue(await error(409, 'la orden esta anulada: no cambia de etapa'))
    abrir()
    const detalle = await verDetalle('R-1')
    fireEvent.click(within(detalle).getByRole('button', { name: /Siguiente etapa/ }))
    expect(await within(detalle).findByRole('alert')).toHaveTextContent('no cambia de etapa')
    expect(within(detalle).getByLabelText('Etapa del viaje')).toHaveValue('cargada')
  })
})

describe('Órdenes · detalle: adjuntos', () => {
  it('lista cada adjunto con nombre, tamaño legible y fecha, y lo abre en otra pestaña', async () => {
    responder([orden(1)], [adjunto(5), adjunto(6, { nombre: 'remito.pdf', tamanio: 850 })])
    abrir()
    const detalle = await verDetalle('R-1')

    const enlace = await within(detalle).findByRole('link', { name: /ticket-5\.jpg/ })
    expect(enlace).toHaveAttribute('href', '/api/ordenes/1/adjuntos/5')
    expect(enlace).toHaveAttribute('target', '_blank')
    expect(get).toHaveBeenCalledWith('/api/ordenes/1/adjuntos')
    // 2.411.724 bytes → 2,3 MB; 850 bytes → 850 B; la fecha, como se lee en Argentina.
    expect(within(detalle).getByText('2,3 MB · 07-10-2026 17:30')).toBeInTheDocument()
    expect(within(detalle).getByText('850 B · 07-10-2026 17:30')).toBeInTheDocument()
  })

  it('sin archivos lo dice', async () => {
    abrir()
    responder([orden(1)])
    abrir()
    const detalle = await verDetalle('R-1')
    expect(await within(detalle).findByText('Todavía no tiene archivos.')).toBeInTheDocument()
  })

  it('el input acepta imágenes y PDF, para que el celular ofrezca la cámara', async () => {
    responder([orden(1)])
    abrir()
    const detalle = await verDetalle('R-1')
    expect(within(detalle).getByLabelText('Adjuntar archivo')).toHaveAttribute('accept', 'image/*,application/pdf')
  })

  it('sube el archivo como multipart en el campo «archivo» y lo suma a la lista', async () => {
    responder([orden(1)], [])
    postForm.mockResolvedValue(adjunto(7, { nombre: 'ticket-puerto.jpg' }))
    abrir()
    const detalle = await verDetalle('R-1')
    await within(detalle).findByText('Todavía no tiene archivos.')

    const archivo = new File(['x'], 'ticket-puerto.jpg', { type: 'image/jpeg' })
    fireEvent.change(within(detalle).getByLabelText('Adjuntar archivo'), { target: { files: [archivo] } })

    await waitFor(() => expect(postForm).toHaveBeenCalledTimes(1))
    expect(postForm.mock.calls[0][0]).toBe('/api/ordenes/1/adjuntos')
    expect((postForm.mock.calls[0][1] as FormData).get('archivo')).toBe(archivo)
    expect(await within(detalle).findByRole('link', { name: /ticket-puerto\.jpg/ })).toBeInTheDocument()
  })

  it('🔑 también se adjunta a una orden facturada: el ticket llega después de facturar', async () => {
    responder([orden(1, { estado: 'facturada', comprobante_id: 9, etapa: 'cerrada' })], [])
    postForm.mockResolvedValue(adjunto(8))
    abrir()
    const detalle = await verDetalle('R-1')
    const campo = within(detalle).getByLabelText('Adjuntar archivo')
    expect(campo).toBeEnabled()
    fireEvent.change(campo, { target: { files: [new File(['x'], 'a.png', { type: 'image/png' })] } })
    await waitFor(() => expect(postForm).toHaveBeenCalled())
  })

  it('🔴 el 422 del servidor (tipo o tamaño) se muestra tal cual y no suma nada a la lista', async () => {
    responder([orden(1)], [])
    postForm.mockRejectedValue(await error(422, 'el archivo no es una imagen ni un PDF'))
    abrir()
    const detalle = await verDetalle('R-1')
    await within(detalle).findByText('Todavía no tiene archivos.')

    fireEvent.change(within(detalle).getByLabelText('Adjuntar archivo'), {
      target: { files: [new File(['x'], 'virus.exe', { type: 'application/octet-stream' })] },
    })

    expect(await within(detalle).findByRole('alert')).toHaveTextContent('el archivo no es una imagen ni un PDF')
    expect(within(detalle).getByText('Todavía no tiene archivos.')).toBeInTheDocument()
  })

  it('una orden anulada no admite archivos nuevos', async () => {
    responder([orden(1, { estado: 'anulada' })], [])
    abrir()
    const detalle = await verDetalle('R-1')
    expect(within(detalle).queryByLabelText('Adjuntar archivo')).toBeNull()
    expect(within(detalle).getByText('Una orden anulada no admite archivos nuevos.')).toBeInTheDocument()
  })

  it('borrar pide confirmación y recién entonces llama DELETE', async () => {
    responder([orden(1)], [adjunto(5), adjunto(6, { nombre: 'remito.pdf' })])
    del.mockResolvedValue(undefined)
    abrir()
    const detalle = await verDetalle('R-1')

    fireEvent.click(await within(detalle).findByRole('button', { name: 'Borrar ticket-5.jpg' }))
    const confirmacion = await screen.findByRole('alertdialog')
    expect(confirmacion).toHaveTextContent('ticket-5.jpg')
    expect(del).not.toHaveBeenCalled()

    fireEvent.click(within(confirmacion).getByRole('button', { name: 'Borrar' }))

    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/ordenes/1/adjuntos/5'))
    await waitFor(() => expect(within(detalle).queryByRole('link', { name: /ticket-5\.jpg/ })).toBeNull())
    expect(within(detalle).getByRole('link', { name: /remito\.pdf/ })).toBeInTheDocument()
  })

  it('cancelar la confirmación no borra nada', async () => {
    responder([orden(1)], [adjunto(5)])
    abrir()
    const detalle = await verDetalle('R-1')
    fireEvent.click(await within(detalle).findByRole('button', { name: 'Borrar ticket-5.jpg' }))
    const confirmacion = await screen.findByRole('alertdialog')
    fireEvent.click(within(confirmacion).getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(del).not.toHaveBeenCalled()
    expect(within(detalle).getByRole('link', { name: /ticket-5\.jpg/ })).toBeInTheDocument()
  })
})


// ── Flete: km y tarifa por tonelada (ADR-038) ─────────────────────────────

const referencia = (km: number, tarifa: string | null, extra: Record<string, unknown> = {}) => ({
  tarifario_id: 1, vigencia: '2026-04-10', nombre: 'Tarifario de referencia abril 2026', km, tarifa,
  valor_estadia: '214146.67', ...extra,
})

/** El tarifario con una tarifa por km; los km que no están en la tabla vuelven con `tarifa: null`. */
function conTarifario(tabla: Record<number, string>, sugerencia: Record<string, unknown> | null = null) {
  tarifarioDe = (ruta) => {
    if (ruta.startsWith('/api/tarifario/sugerencia')) return sugerencia ? Promise.resolve(sugerencia) : noHay()
    const km = Number(new URL(ruta, 'http://x').searchParams.get('km'))
    return Promise.resolve(referencia(km, tabla[km] ?? null))
  }
}

const llamadasA = (prefijo: string) => get.mock.calls.map((c) => c[0] as string).filter((r) => r.startsWith(prefijo))

describe('Órdenes · formulario: flete', () => {
  async function editar(extra: Record<string, unknown> = {}) {
    responder([orden(1, extra)])
    abrir()
    await screen.findByText('R-1')
    fireEvent.click(screen.getByLabelText('Editar'))
    return await screen.findByRole('dialog')
  }

  const escribir = (campo: string, valor: string) =>
    fireEvent.change(screen.getByLabelText(campo), { target: { value: valor } })

  /** El texto que acompaña a los km: `Referencia: …`, `Sin tarifa…` o `No hay tarifario…`. */
  const referenciaMostrada = (patron: RegExp) => screen.findByText(patron)

  it('tiene la sección «Flete» con Km, % sobre referencia y Tarifa por tonelada, todo vacío y nada obligatorio', async () => {
    const dialogo = await editar()
    const flete = within(dialogo).getByRole('region', { name: 'Flete' })
    for (const campo of ['Km', '% sobre referencia', 'Tarifa por tonelada']) {
      expect(within(flete).getByLabelText(campo)).toHaveValue(campo === 'Km' ? null : '')
    }
    // Sin tocar nada se guarda con null: ni los km ni la tarifa son obligatorios.
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({ km: null, tarifa_tonelada: null })
    // Y mientras no hay km no se consulta el tarifario.
    expect(llamadasA('/api/tarifario/referencia')).toEqual([])
  })

  it('con los km pide la referencia a la fecha de la orden y la muestra con la vigencia del tarifario', async () => {
    conTarifario({ 80: '23205.57' })
    await editar({ fecha: '2026-09-10' })
    escribir('Km', '80')
    expect(await referenciaMostrada(/Referencia: \$ 23\.205,57 \(tarifario 10-04-2026\)/)).toBeInTheDocument()
    expect(llamadasA('/api/tarifario/referencia')).toEqual(['/api/tarifario/referencia?km=80&fecha=2026-09-10'])
  })

  it('espera a que se termine de tipear: «80» no pide primero «8»', async () => {
    conTarifario({ 80: '23205.57' })
    await editar()
    escribir('Km', '8')
    escribir('Km', '80')
    await referenciaMostrada(/Referencia: \$ 23\.205,57/)
    expect(llamadasA('/api/tarifario/referencia')).toHaveLength(1)
  })

  it('unos km que no están en la tabla se dicen sin extrapolar: «Sin tarifa para esos km»', async () => {
    conTarifario({ 80: '23205.57' })
    await editar()
    escribir('Km', '81')
    expect(await referenciaMostrada(/Sin tarifa para esos km \(tarifario 10-04-2026\)/)).toBeInTheDocument()
    expect(screen.queryByText(/Referencia:/)).toBeNull()
  })

  it('🔴 sin tarifario para esa fecha (404) lo dice, y la tarifa se puede cargar igual a mano', async () => {
    const dialogo = await editar()
    escribir('Km', '80')
    expect(await referenciaMostrada(/No hay tarifario cargado para esa fecha/)).toBeInTheDocument()

    escribir('Tarifa por tonelada', '19000')
    // Sin referencia no hay porcentaje que calcular.
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({ km: 80, tarifa_tonelada: '19000.00' })
  })

  it('un fallo del servidor al consultar se muestra, no se traga', async () => {
    tarifarioDe = () => Promise.reject(new Error('el tarifario no responde'))
    await editar()
    escribir('Km', '80')
    expect(await referenciaMostrada(/el tarifario no responde/)).toBeInTheDocument()
  })

  it('el % sobre la referencia calcula la tarifa por tonelada: 85 % de 23.205,57 es 19.724,73', async () => {
    conTarifario({ 80: '23205.57' })
    const dialogo = await editar()
    escribir('Km', '80')
    await referenciaMostrada(/Referencia: \$ 23\.205,57/)

    escribir('% sobre referencia', '85')
    expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('19724.73')

    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    // Texto con dos decimales, no un número; el porcentaje no viaja.
    expect(put.mock.calls[0][1]).toMatchObject({ km: 80, tarifa_tonelada: '19724.73' })
    expect(put.mock.calls[0][1]).not.toHaveProperty('porcentaje')
  })

  it('al editar la tarifa a mano el % se recalcula con dos decimales', async () => {
    conTarifario({ 80: '23205.57' })
    await editar()
    escribir('Km', '80')
    await referenciaMostrada(/Referencia: \$ 23\.205,57/)

    escribir('Tarifa por tonelada', '19724.73')
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85.00')
    escribir('Tarifa por tonelada', '20000')
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('86.19')
  })

  it('acepta la coma al escribir el % y la tarifa', async () => {
    conTarifario({ 80: '23205.57' })
    const dialogo = await editar()
    escribir('Km', '80')
    await referenciaMostrada(/Referencia: \$ 23\.205,57/)

    escribir('% sobre referencia', '82,5')
    expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('19144.60')
    escribir('Tarifa por tonelada', '19.724,73')
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85.00')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({ tarifa_tonelada: '19724.73' })
  })

  it('🔑 manda lo último que se tocó: con el % puesto, otros km recalculan la tarifa; con la tarifa puesta, el %', async () => {
    conTarifario({ 80: '23205.57', 90: '25000.00' })
    await editar()
    escribir('Km', '80')
    await referenciaMostrada(/Referencia: \$ 23\.205,57/)
    escribir('% sobre referencia', '85')

    escribir('Km', '90')
    await referenciaMostrada(/Referencia: \$ 25\.000,00/)
    await waitFor(() => expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('21250.00'))
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85')

    escribir('Tarifa por tonelada', '20000')
    escribir('Km', '80')
    await referenciaMostrada(/Referencia: \$ 23\.205,57/)
    expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('20000')
    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('86.19'))
  })

  it('una orden que ya trae km y tarifa por tonelada los muestra y calcula su % contra la referencia', async () => {
    conTarifario({ 80: '23205.57' })
    await editar({ km: 80, tarifa_tonelada: '19724.73' })
    expect(screen.getByLabelText('Km')).toHaveValue(80)
    expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('19724.73')
    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85.00'))
  })

  it('una tarifa que no es un importe no se manda y lo dice', async () => {
    const dialogo = await editar()
    escribir('Tarifa por tonelada', 'mucho')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByText('importe inválido')).toBeInTheDocument()
    expect(put).not.toHaveBeenCalled()
  })
})

describe('Órdenes · formulario: sugerencia del cliente', () => {
  const SUGERENCIA = {
    porcentaje: '85.00', orden_id: 77, fecha: '2026-09-30', km: 80, tarifa_tonelada: '19724.73',
    tarifa_referencia: '23205.57',
  }

  async function nueva() {
    responder([])
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: /Nueva/ }))
    return await screen.findByRole('dialog')
  }

  /** Elige un cliente en el selector con buscador (espera a que lleguen las opciones). */
  async function elegirCliente(dialogo: HTMLElement, nombre: string) {
    const combo = within(dialogo).getByRole('combobox', { name: 'Cliente' })
    await waitFor(() => {
      fireEvent.click(combo)
      expect(screen.getByRole('option', { name: nombre })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('option', { name: nombre }))
  }

  it('al elegir el cliente propone el % de su último viaje, con el texto que lo explica', async () => {
    conTarifario({ 80: '23205.57' }, SUGERENCIA)
    const dialogo = await nueva()
    await elegirCliente(dialogo, 'Agro Norte')

    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85.00'))
    expect(screen.getByText('Último viaje de este cliente: 85 %')).toBeInTheDocument()
    expect(llamadasA('/api/tarifario/sugerencia')).toEqual(['/api/tarifario/sugerencia?cliente_id=1'])
    // Sin km todavía no hay referencia: la tarifa espera.
    expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('')
  })

  it('con el % sugerido, al cargar los km la tarifa sale sola', async () => {
    conTarifario({ 80: '23205.57' }, SUGERENCIA)
    const dialogo = await nueva()
    await elegirCliente(dialogo, 'Agro Norte')
    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85.00'))

    fireEvent.change(screen.getByLabelText('Km'), { target: { value: '80' } })
    await waitFor(() => expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('19724.73'))
  })

  it('con los km ya cargados, la tarifa sale en cuanto llega la sugerencia', async () => {
    conTarifario({ 80: '23205.57' }, SUGERENCIA)
    const dialogo = await nueva()
    fireEvent.change(screen.getByLabelText('Km'), { target: { value: '80' } })
    await screen.findByText(/Referencia: \$ 23\.205,57/)
    await elegirCliente(dialogo, 'Agro Norte')
    await waitFor(() => expect(screen.getByLabelText('Tarifa por tonelada')).toHaveValue('19724.73'))
  })

  it('un cliente sin viajes con tarifa (404) no propone nada', async () => {
    conTarifario({ 80: '23205.57' }, null)
    const dialogo = await nueva()
    await elegirCliente(dialogo, 'Agro Norte')
    await waitFor(() => expect(llamadasA('/api/tarifario/sugerencia')).toHaveLength(1))
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('')
    expect(screen.queryByText(/Último viaje de este cliente/)).toBeNull()
  })

  it('🔑 no pisa lo que ya está cargado: una orden con tarifa por tonelada no consulta la sugerencia', async () => {
    conTarifario({ 80: '23205.57' }, SUGERENCIA)
    responder([orden(1, { km: 80, tarifa_tonelada: '20000.00' })])
    abrir()
    await screen.findByText('R-1')
    fireEvent.click(screen.getByLabelText('Editar'))
    await screen.findByRole('dialog')
    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('86.19'))
    expect(llamadasA('/api/tarifario/sugerencia')).toEqual([])
    expect(screen.queryByText(/Último viaje de este cliente/)).toBeNull()
  })

  it('si lo sugerido todavía no se tocó, otro cliente lo reemplaza; si se tocó, no', async () => {
    responder([])
    const otra = { ...SUGERENCIA, porcentaje: '90.00' }
    tarifarioDe = (ruta) => {
      if (!ruta.startsWith('/api/tarifario/sugerencia')) return Promise.resolve(referencia(80, '23205.57'))
      return Promise.resolve(ruta.endsWith('cliente_id=1') ? SUGERENCIA : otra)
    }
    get.mockImplementation(((anterior) => (ruta?: string) => {
      if (ruta?.startsWith('/api/terceros')) {
        return Promise.resolve([
          { id: 1, razon_social: 'Agro Norte', es_cliente: true }, { id: 2, razon_social: 'Pereiro', es_cliente: true },
        ])
      }
      return anterior(ruta)
    })(get.getMockImplementation() as (r?: string) => unknown))
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: /Nueva/ }))
    const dialogo = await screen.findByRole('dialog')

    await elegirCliente(dialogo, 'Agro Norte')
    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('85.00'))
    await elegirCliente(dialogo, 'Pereiro')
    await waitFor(() => expect(screen.getByLabelText('% sobre referencia')).toHaveValue('90.00'))

    escribir_pct('88')
    await elegirCliente(dialogo, 'Agro Norte')
    await waitFor(() => expect(llamadasA('/api/tarifario/sugerencia')).toHaveLength(2))
    expect(screen.getByLabelText('% sobre referencia')).toHaveValue('88')
  })
})

function escribir_pct(valor: string) {
  fireEvent.change(screen.getByLabelText('% sobre referencia'), { target: { value: valor } })
}

describe('Órdenes · km y tarifa por tonelada en el listado y el detalle', () => {
  it('el listado tiene la columna «Km», opcional (se oculta en pantallas chicas), con «—» si no se sabe', async () => {
    responder([orden(1, { km: 80 }), orden(2)])
    abrir()
    await screen.findByText('R-1')
    const tabla = screen.getByRole('table')
    const encabezado = within(tabla).getByRole('columnheader', { name: 'Km' })
    expect(encabezado).toHaveClass('hidden', 'xl:table-cell')
    expect(within(tabla).getByText('80')).toBeInTheDocument()
  })

  it('el detalle muestra los km y la tarifa por tonelada, o «—»', async () => {
    responder([orden(1, { km: 80, tarifa_tonelada: '19724.73' }), orden(2)])
    abrir()
    let detalle = await verDetalle('R-1')
    const celda = (etiqueta: string) => within(detalle).getByText(etiqueta).nextElementSibling
    expect(celda('Km')).toHaveTextContent('80')
    expect(celda('Tarifa por tonelada')).toHaveTextContent('$ 19.724,73')
    fireEvent.click(within(detalle).getByRole('button', { name: 'Cerrar' }))

    detalle = await verDetalle('R-2')
    expect(celda('Km')).toHaveTextContent('—')
    expect(celda('Tarifa por tonelada')).toHaveTextContent('—')
  })
})
