/** Los tests del flujo de facturar, mudados del modal a la pantalla.
 *
 * Eran cuatro adentro de `Comprobantes.test.tsx` y probaban el `<Dialog>`. La
 * lógica que cubren —qué órdenes se ofrecen, cómo suma la vista previa, qué
 * viaja en el POST— no cambió al mudarse: lo que cambió es dónde vive.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

const { default: FacturarPendientes } = await import('./FacturarPendientes')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]
const RAZONES = [
  { id: 5, nombre: 'Suitrans' },
  { id: 6, nombre: 'Mauricio' },
]

function responder(ordenes: unknown[] = []) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/razones-sociales')) return Promise.resolve(RAZONES)
    return Promise.resolve([])
  })
}

function orden(id: number, extra: Record<string, unknown> = {}) {
  return {
    id, fecha: '2026-08-10', cliente_id: 1, origen_id: 1, destino_id: 2,
    fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
    razon_social_id: null, remito: null, cantidad: null, unidad: null,
    tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
    comision: '0.00', estado: 'pendiente', comprobante_id: null,
    observaciones: null, ...extra,
  }
}

/** Monta la pantalla y elige cliente y razón social. */
async function abrir(cliente = '1', razon = '5') {
  render(<MemoryRouter><FacturarPendientes /></MemoryRouter>)
  const selectCliente = await screen.findByLabelText('Cliente')
  await waitFor(() => expect(selectCliente.querySelectorAll('option').length).toBe(2))
  // Dentro de act: elegir el cliente dispara el pedido de las pendientes, y
  // ese estado llega despues del evento. Sin esto React avisa que la
  // actualizacion quedo afuera, y lo que se assertee puede ser el estado previo.
  await act(async () => {
    fireEvent.change(selectCliente, { target: { value: cliente } })
    fireEvent.change(screen.getByLabelText('Razón social', { selector: '#n-razon' }),
                     { target: { value: razon } })
  })
}

const casilla = (id: number) => screen.getByLabelText(`Elegir la orden ${id}`)

describe('Facturar pendientes', () => {
  beforeEach(() => { get.mockReset(); post.mockReset() })

  it('es una pantalla y no un modal', async () => {
    // 🔑 Lo que el humano pidió. Un `<Dialog>` de shadcn monta `role="dialog"`
    // con `aria-modal`, y encima marca el resto del documento como inerte: si
    // esto volviera a ser un modal, el assert lo diría. Sin este test, mudar la
    // pantalla de vuelta a un `<Dialog>` no rompería nada.
    responder([orden(1)])
    await abrir()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Facturar pendientes' })).toBeInTheDocument()
  })

  it('no ofrece las ordenes que ya tienen otra razón social', async () => {
    // El backend las rechaza con un 422 --pisarles la razon social moveria
    // plata de una a la otra--, asi que ofrecerlas seria invitar al error.
    responder([orden(1), orden(2, { razon_social_id: 6 }), orden(3, { razon_social_id: 5 })])
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    expect(casilla(3)).toBeInTheDocument()
    expect(screen.queryByLabelText('Elegir la orden 2')).toBeNull()
  })

  it('la vista previa suma lo elegido, y sin nada elegido no deja facturar', async () => {
    responder([orden(1, { total: '0.10' }), orden(2, { total: '0.20' })])
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    // El numero va PRIMERO: sin el, el boton estaria deshabilitado por eso y no
    // por lo que este test dice medir.
    fireEvent.change(screen.getByLabelText('Número'), { target: { value: '123' } })
    expect(screen.getByText('Total: $ 0,00')).toBeInTheDocument()
    expect(screen.getByText('Facturar')).toBeDisabled()
    expect(screen.getByText('No elegiste ninguna orden.')).toBeInTheDocument()

    fireEvent.click(casilla(1))
    fireEvent.click(casilla(2))
    // 0.10 + 0.20 en punto flotante da 0.30000000000000004: la suma va en
    // centavos enteros justamente por esto.
    expect(screen.getByText('Total: $ 0,30')).toBeInTheDocument()
    expect(screen.getByText('Facturar')).toBeEnabled()
  })

  it('la casilla del encabezado marca y desmarca todas', async () => {
    responder([orden(1, { total: '100.00' }), orden(2, { total: '50.00' })])
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Marcar todas'))
    expect(screen.getByText('Total: $ 150,00')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Desmarcar todas'))
    expect(screen.getByText('Total: $ 0,00')).toBeInTheDocument()
  })

  it('hacer click en la fila alterna la orden, sin contarla dos veces', async () => {
    // La fila entera es clickeable y la casilla vive adentro. Sin el
    // `stopPropagation` de la casilla, el click en ella dispara los dos
    // manejadores y la orden queda como estaba.
    responder([orden(1, { total: '100.00' })])
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(screen.getByText('2026-08-10'))
    expect(screen.getByText('Total: $ 100,00')).toBeInTheDocument()

    fireEvent.click(casilla(1))
    expect(screen.getByText('Total: $ 0,00')).toBeInTheDocument()
  })

  it('cambiar la razón social saca de la cuenta lo que ya no se puede facturar', async () => {
    // Sin esto, una orden elegida antes del cambio seguiria sumando en la vista
    // previa y viajaria en el pedido, para que el backend la rechace.
    responder([orden(1), orden(2, { razon_social_id: 6, total: '500.00' })])
    await abrir('1', '6')

    await waitFor(() => expect(casilla(2)).toBeInTheDocument())
    fireEvent.click(casilla(2))
    expect(screen.getByText('Total: $ 500,00')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Razón social', { selector: '#n-razon' }),
                     { target: { value: '5' } })
    expect(screen.getByText('Total: $ 0,00')).toBeInTheDocument()
    expect(screen.getByText('Facturar')).toBeDisabled()
  })

  it('factura las ordenes elegidas con el numero tipeado', async () => {
    responder([orden(1)])
    post.mockResolvedValue({ id: 9 })
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    fireEvent.change(screen.getByLabelText('Número'), { target: { value: '123' } })
    fireEvent.click(screen.getByText('Facturar'))

    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/api/comprobantes')
    expect(post.mock.calls[0][1]).toMatchObject({
      cliente_id: 1, razon_social_id: 5, tipo: 'factura_a',
      punto_venta: 1, numero: 123, orden_ids: [1],
    })
  })

  // ── El ensayo contra homologación ────────────────────────────────────────
  //
  // Con el ambiente de ARCA en homologación el backend corre el alta entera y
  // la revierte, así que contesta algo que **no tiene `id`**. Lo que se prueba
  // acá es que la pantalla lo muestre en vez de navegar: un `navigate` con un
  // id `undefined` deja al operador en el listado, sin su comprobante y sin
  // ninguna explicación — que parece que no funcionó.

  const ENSAYO = {
    ensayo: true, ambiente: 'homologacion', tipo: 'factura_a',
    punto_venta: 5, numero: 42, total: '1210.00',
    cae: '75123456789012', cae_vencimiento: '2026-12-31',
  }

  async function facturarConRespuesta(respuesta: unknown) {
    responder([orden(1)])
    post.mockResolvedValue(respuesta)
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    fireEvent.change(screen.getByLabelText('Número'), { target: { value: '123' } })
    fireEvent.click(screen.getByText('Facturar'))
    await waitFor(() => expect(post).toHaveBeenCalled())
  }

  it('un ensayo se muestra en la pantalla, con su número y su CAE', async () => {
    await facturarConRespuesta(ENSAYO)

    const panel = await screen.findByRole('status', { name: 'Resultado del ensayo' })
    expect(panel).toHaveTextContent('no se guardó nada')
    expect(panel).toHaveTextContent('0005-00000042')
    expect(panel).toHaveTextContent('75123456789012')
  })

  it('un ensayo NO navega: la pantalla se queda donde está', async () => {
    // El control de lo de arriba. Sin esto, "se ve el panel" pasaría igual con
    // una pantalla que además se fue a otro lado.
    await facturarConRespuesta(ENSAYO)

    expect(screen.getByRole('heading', { name: 'Facturar pendientes' }))
      .toBeInTheDocument()
    expect(screen.getByText('Facturar')).not.toBeDisabled()
  })

  it('un comprobante de verdad no muestra el panel del ensayo', async () => {
    // La otra dirección: si el panel apareciera siempre, los dos tests de
    // arriba pasarían y la pantalla mentiría en el caso normal.
    await facturarConRespuesta({ id: 9 })

    expect(screen.queryByRole('status', { name: 'Resultado del ensayo' })).toBeNull()
  })
})
