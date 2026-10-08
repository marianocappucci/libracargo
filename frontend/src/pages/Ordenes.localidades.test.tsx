/** El origen y el destino de una orden se eligen con el buscador combinado (ADR-041, ADR-042): maestro + catálogo (Argentina y Mercosur).
 *
 *  La prueba de fondo es de punta a punta en lo que importa: elegir una localidad **del catálogo** en una orden la trae al
 *  maestro y lo que viaja en la orden es el **id del maestro** que devolvió el servidor, no el código censal.
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
  return { ApiError, api: { get, post, put, del: vi.fn(), postForm: vi.fn() } }
})

const { default: Ordenes } = await import('./Ordenes')

const orden = {
  id: 1, fecha: '2026-10-05', cliente_id: 1, origen_id: 1, destino_id: 2,
  fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
  remito: 'R-1', cantidad: null, unidad: null,
  tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
  comision: '0.00', estado: 'pendiente', comprobante_id: null,
  observaciones: null, cantidad_legado: null, origen_legado: null, etapa: 'asignada',
  kg_bruto_carga: null, kg_tara_carga: null, kg_neto_carga: null,
  kg_bruto_descarga: null, kg_tara_descarga: null, kg_neto_descarga: null,
  km: null, tarifa_tonelada: null,
}
const MAESTRO = [
  { id: 1, nombre: 'Suipacha', provincia: 'Buenos Aires', pais: 'AR', es_paraje: false, activo: true, catalogo_id: '06784020' },
  { id: 2, nombre: 'Rosario', provincia: 'Santa Fe', pais: 'AR', es_paraje: false, activo: true, catalogo_id: '82084010' },
]

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset()
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/localidades/buscar/combinado')) {
      return Promise.resolve({
        maestro: [],
        catalogo: [{ id: '30003010', nombre: 'Paraná', provincia_id: '30', provincia: 'Entre Ríos' }],
      })
    }
    if (ruta.startsWith('/api/localidades')) return Promise.resolve(MAESTRO)
    if (ruta.startsWith('/api/terceros')) {
      return Promise.resolve([{ id: 1, razon_social: 'Agro Norte', es_cliente: true }])
    }
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve([orden])
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({})
    return Promise.resolve([])
  })
})

describe('Órdenes · origen y destino con el catálogo', () => {
  it('🔑 elegir una del catálogo la trae al maestro y la orden viaja con el id del maestro', async () => {
    post.mockResolvedValue({ id: 55, nombre: 'Paraná', provincia: 'Entre Ríos', pais: 'AR', es_paraje: false, activo: true, catalogo_id: '30003010' })
    put.mockResolvedValue(orden)
    render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
    await screen.findByText('R-1')
    fireEvent.click(screen.getByLabelText('Editar'))
    const dialogo = await screen.findByRole('dialog')

    // La orden trae su origen: se lee con la provincia.
    const origen = await within(dialogo).findByRole('combobox', { name: 'Origen' })
    await waitFor(() => expect(origen).toHaveValue('Suipacha — Buenos Aires'))
    expect(within(dialogo).getByRole('combobox', { name: 'Destino' })).toHaveValue('Rosario — Santa Fe')

    fireEvent.focus(origen)
    fireEvent.change(origen, { target: { value: 'para' } })
    expect(await within(dialogo).findByText('Del catálogo (Argentina y Mercosur)')).toBeInTheDocument()
    fireEvent.click(within(dialogo).getByRole('option', { name: 'Paraná — Entre Ríos' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/localidades/desde-catalogo', { catalogo_id: '30003010' }))
    await waitFor(() => expect(origen).toHaveValue('Paraná — Entre Ríos'))

    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    const [ruta, cuerpo] = put.mock.calls[0]
    expect(ruta).toBe('/api/ordenes/1')
    expect(cuerpo).toMatchObject({ origen_id: 55, destino_id: 2 })
  })

  it('el origen y el destino siguen sin poder ser el mismo lugar', async () => {
    render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
    await screen.findByText('R-1')
    fireEvent.click(screen.getByLabelText('Editar'))
    const dialogo = await screen.findByRole('dialog')
    const destino = await within(dialogo).findByRole('combobox', { name: 'Destino' })
    await waitFor(() => expect(destino).toHaveValue('Rosario — Santa Fe'))

    // Se busca en el destino la misma localidad que ya es el origen.
    get.mockImplementation((ruta?: string) =>
      ruta?.startsWith('/api/localidades/buscar/combinado')
        ? Promise.resolve({ maestro: [MAESTRO[0]], catalogo: [] })
        : Promise.resolve(ruta?.startsWith('/api/ordenes') ? [orden] : []))
    fireEvent.focus(destino)
    fireEvent.change(destino, { target: { value: 'suip' } })
    fireEvent.click(await within(dialogo).findByRole('option', { name: 'Suipacha — Buenos Aires' }))
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByText('el origen y el destino no pueden ser el mismo lugar')).toBeInTheDocument()
    expect(put).not.toHaveBeenCalled()
  })
})
