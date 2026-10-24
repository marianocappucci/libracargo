/** La orden de carga en un nodo (ADR-056 del backend, libra-ui ADR-094): el aviso «sin CPE válida» y el id provisorio.
 *
 *  🔴 Una carga cuya carta de porte quedó en la cola del nodo (sin conexión) o a revisar **no tiene CPE válida y no puede viajar**: es un
 *  límite legal y la ficha de la orden lo dice en rojo. El pedido de la cola se reconoce por `datos.orden_id` —el `origen_id` es
 *  `orden<id>:<uuid>`— y fuera de un nodo, con la CPE emitida o de otra orden no aparece.
 *
 *  Una orden cargada en el nodo nace con un id NEGATIVO y lo conserva hasta que sube al central: no se la muestra como una orden «Nº -3».
 */
import { act, configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20_000 })

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { default: Ordenes } = await import('./Ordenes')

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

/** Un pedido de la cola tal como lo deja LibraCargo (`app/servicios/emisores.py`). */
const pedidoDeCpe = (ordenId: number, extra: Record<string, unknown> = {}) => ({
  id: 5, origen_producto: 'libracargo', origen_instancia: 'oficina', origen_tipo: 'cpe', origen_id: `orden${ordenId}:3f1c9a`,
  estado: 'esperando', datos: { orden_id: ordenId, solicitud: {}, confirmo: true }, fecha_ref: '', concepto: 1, intentos: 0,
  ultimo_error: '', resultado: null, revision: 1, created_at: '2026-10-24T10:00:00', updated_at: '2026-10-24T10:00:00',
  resuelto_at: '', ...extra,
})
const COLA_DE_UN_NODO = (pedidos: unknown[]) => ({ es_nodo: true, en_linea: false, node_id: 'oficina', cuentas: {}, a_revisar: 0, pedidos })
const FUERA_DE_UN_NODO = { es_nodo: false, en_linea: true, node_id: null, cuentas: {}, a_revisar: 0, pedidos: [] }

function responder(ordenes: Record<string, unknown>[], cola: unknown = FUERA_DE_UN_NODO) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/nodo/cola')) return Promise.resolve(cola)
    if (ruta.includes('/adjuntos')) return Promise.resolve([])
    const uno = /^\/api\/ordenes\/(-?\d+)$/.exec(ruta)
    if (uno) return Promise.resolve(ordenes.find((o) => o.id === Number(uno[1])))
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve([{ id: 1, razon_social: 'Agro Norte', es_cliente: true }])
    if (ruta.startsWith('/api/localidades')) return Promise.resolve([{ id: 1, nombre: 'Suipacha' }, { id: 2, nombre: 'Rosario' }])
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({})
    return Promise.resolve([])
  })
}

/** Abre el detalle de una orden por el enlace profundo (`?ver=`). */
async function verLaOrden(id: number) {
  render(<MemoryRouter initialEntries={[`/ordenes?ver=${id}`]}><Ordenes /></MemoryRouter>)
  return screen.findByRole('dialog')
}

/** Deja pasar la respuesta de la cola: un «no aparece» que se mira antes de que llegue no prueba nada. */
const esperarLaCola = async () => {
  await waitFor(() => expect(get).toHaveBeenCalledWith(expect.stringContaining('/api/nodo/cola')))
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
}

const SIN_CPE = /todavía no tiene CPE válida: no puede viajar hasta que se emita/

describe('Orden de carga · el aviso «sin CPE válida» (la CPE quedó en la cola del nodo)', () => {
  beforeEach(() => { get.mockReset() })

  it('🔴 con la CPE de esta orden esperando en la cola, la ficha dice en rojo que no puede viajar', async () => {
    responder([orden(41)], COLA_DE_UN_NODO([pedidoDeCpe(41)]))
    const dialogo = await verLaOrden(41)
    const alerta = await within(dialogo).findByRole('alert')
    expect(alerta).toHaveTextContent('Esta carga todavía no tiene CPE válida: no puede viajar hasta que se emita.')
    expect(alerta).toHaveAttribute('data-estado', 'esperando')
    // Se pidió sólo la cola de CPE abiertas, no todo el historial.
    const pedida = String(get.mock.calls.map((c) => c[0]).find((r) => String(r).startsWith('/api/nodo/cola')))
    expect(pedida).toContain('tipo=cpe')
    expect(pedida).toContain('estado=esperando')
  })

  it('un pedido a revisar o incierto suma qué dijo ARCA', async () => {
    responder([orden(41)], COLA_DE_UN_NODO([pedidoDeCpe(41, { estado: 'a_revisar', ultimo_error: 'ARCA rechazó la carta de porte: 1015' })]))
    const dialogo = await verLaOrden(41)
    expect(await within(dialogo).findByText('ARCA rechazó la carta de porte: 1015')).toBeInTheDocument()
  })

  it('🔴 con la CPE emitida (o descartada) no aparece: la carga ya tiene CPE válida', async () => {
    responder([orden(41)], COLA_DE_UN_NODO([
      pedidoDeCpe(41, { id: 6, estado: 'emitido', resultado: { ctg: 10123456781 } }),
      pedidoDeCpe(41, { id: 7, estado: 'descartado' }),
    ]))
    const dialogo = await verLaOrden(41)
    await esperarLaCola()
    expect(within(dialogo).queryByText(SIN_CPE)).toBeNull()
  })

  it('el pedido de OTRA orden no cuenta: se compara `datos.orden_id` y no el `origen_id`', async () => {
    responder([orden(41)], COLA_DE_UN_NODO([pedidoDeCpe(99)]))
    const dialogo = await verLaOrden(41)
    await esperarLaCola()
    expect(within(dialogo).queryByText(SIN_CPE)).toBeNull()
  })

  it('fuera de un nodo no cambia nada visible: ni aviso ni etiqueta', async () => {
    responder([orden(41)])
    const dialogo = await verLaOrden(41)
    await esperarLaCola()
    expect(within(dialogo).queryByRole('alert')).toBeNull()
    expect(within(dialogo).queryByText('Sin subir al central')).toBeNull()
    expect(within(dialogo).getByText('Orden Nº 00000041')).toBeInTheDocument()
  })

  it('si la cola no contesta, tampoco inventa una alerta', async () => {
    responder([orden(41)])
    get.mockImplementation((ruta?: string) => (String(ruta).startsWith('/api/nodo/cola')
      ? Promise.reject(new Error('sin red'))
      : Promise.resolve(String(ruta).startsWith('/api/ordenes/41') ? orden(41) : [])))
    const dialogo = await verLaOrden(41)
    await esperarLaCola()
    expect(within(dialogo).queryByRole('alert')).toBeNull()
  })
})

describe('Orden de carga · el id provisorio de una orden cargada en el nodo', () => {
  beforeEach(() => { get.mockReset() })

  it('🔴 una orden con id negativo no se muestra como «Nº -3»: es provisoria, y dice que no subió al central', async () => {
    responder([orden(-3, { remito: 'R-77' })], COLA_DE_UN_NODO([]))
    const dialogo = await verLaOrden(-3)
    expect(await within(dialogo).findByText('Orden provisoria P-3')).toBeInTheDocument()
    expect(within(dialogo).getByText('Sin subir al central')).toBeInTheDocument()
    expect(dialogo.textContent).not.toMatch(/Nº/)
    expect(dialogo.textContent).not.toMatch(/(?<!P)-3/)
  })

  it('el aviso «sin CPE válida» también sale en una orden provisoria', async () => {
    responder([orden(-3)], COLA_DE_UN_NODO([pedidoDeCpe(-3, { origen_id: 'orden-3:aa' })]))
    const dialogo = await verLaOrden(-3)
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent(SIN_CPE)
  })

  it('el botón de emitir la carta de porte lleva a la página de la orden con su id negativo', async () => {
    responder([orden(-3)], COLA_DE_UN_NODO([]))
    const dialogo = await verLaOrden(-3)
    const enlace = await within(dialogo).findByRole('link', { name: /Emitir carta de porte/ })
    expect(enlace).toHaveAttribute('href', '/cartas-porte/emitir/-3')
  })

  it('anular una provisoria pregunta por la «orden provisoria P-3» y no por un número', async () => {
    responder([orden(-3)], COLA_DE_UN_NODO([]))
    render(<MemoryRouter initialEntries={['/ordenes']}><Ordenes /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: /Anular/ }))
    expect(await screen.findByText('¿Anular la orden provisoria P-3?')).toBeInTheDocument()
  })
})
