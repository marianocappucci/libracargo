/** Órdenes de carga con etapa, kilos y adjuntos (ADR-037, fase 2).
 *
 * Lo que se prueba es lo que la pantalla decide y el backend no puede: el neto que se calcula en el formulario, la
 * tara que no pasa al bruto, «Liquidada» como lectura de «facturada», y a qué endpoint va cada acción (la etapa a
 * `PUT /etapa` también en una facturada; los archivos a `/adjuntos`). Las reglas de fondo son del servidor y su
 * 422 se muestra tal cual.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

function responder(ordenes: unknown[] = [], adjuntos: unknown[] = []) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
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
