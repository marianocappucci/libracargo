/** El detalle de una pre factura: lo que se puede hacer según el estado, y qué pasa al hacerlo.
 *
 * Datos ficticios (Agro Norte, Suitrans). Lo que más importa es **facturar**: que pida confirmación, que
 * mande la fecha, que muestre la factura emitida, el error tal cual lo dice el servidor (sin certificado,
 * ARCA que rechaza) y que un ensayo no se confunda con una factura.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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

const { default: PreFactura } = await import('./PreFactura')
const { ApiError } = await import('libra-ui/api-client')

function pf(estado = 'pendiente', extra: Record<string, unknown> = {}) {
  return {
    id: 7, numero_interno: 'PF-0007', estado, cliente_id: 1, cliente_razon: 'Agro Norte',
    cliente_cuit: '30-12345678-1', razon_social_id: 5, razon_social: 'Suitrans',
    tipo_comprobante: 1, fecha_sugerida: '2026-08-20', fecha_vencimiento_pago: null,
    observaciones: '', orden_ids: [3, 4], total: '2420.00', created_at: '2026-08-20 10:15:00',
    enviado_at: null, enviado_a: null, aceptado_at: null, aceptado_por: null, factura_id: null,
    motivo_descarte: null, resuelto_por: null, resuelto_at: null,
    items: [
      { description: 'Flete', detalle: 'Orden 3 del 10/08/2026', qty: 1, unit_price: 1000, iva_rate: 0.21, orden_id: 3 },
      { description: 'Flete', detalle: 'Orden 4 del 11/08/2026, remito 0001-1', qty: 1, unit_price: 1000, iva_rate: 0.21, orden_id: 4 },
    ],
    ...extra,
  }
}

/** Lo que el servidor devuelve ahora: lo último que se le hizo, para que `ver` después de una acción cambie. */
let actual: ReturnType<typeof pf>

function servidor(inicial: ReturnType<typeof pf>, tercero: Record<string, unknown> = {}) {
  actual = inicial
  get.mockImplementation((ruta?: string) => {
    if (ruta === '/api/pre-facturas/7') return Promise.resolve(actual)
    if (ruta?.startsWith('/api/terceros/')) return Promise.resolve({ id: 1, ...tercero })
    return Promise.resolve([])
  })
}

function abrir() {
  render(
    <MemoryRouter initialEntries={['/pre-facturas/7']}>
      <Routes>
        <Route path="/pre-facturas/:id" element={<PreFactura />} />
        <Route path="/pre-facturas/:id/editar" element={<p>Pantalla de editar</p>} />
      </Routes>
    </MemoryRouter>)
}

const FACTURA = {
  id: 42, tipo: 'factura_a', punto_venta: 5, numero: 42, fecha: '2026-08-20', cae: '75123456789012',
}

describe('Pre factura', () => {
  beforeEach(() => { get.mockReset(); post.mockReset() })

  it('muestra el número interno, el estado, el cliente, quién emite, el total y el detalle', async () => {
    servidor(pf())
    abrir()

    expect(await screen.findByRole('heading', { name: 'Pre factura PF-0007' })).toBeInTheDocument()
    expect(screen.getByText('Pendiente')).toBeInTheDocument()
    expect(screen.getByText('Agro Norte')).toBeInTheDocument()
    expect(screen.getByText('Suitrans')).toBeInTheDocument()
    expect(screen.getByText('Factura A')).toBeInTheDocument()
    expect(screen.getByText('$ 2.420,00')).toBeInTheDocument()
    expect(screen.getByText(/Orden 4 del 11\/08\/2026, remito 0001-1/)).toBeInTheDocument()
    expect(screen.getAllByText('21%')).toHaveLength(2)
  })

  it('el PDF se ve y se descarga por un enlace común, de cualquier estado', async () => {
    servidor(pf('descartado', { motivo_descarte: 'Pedido repetido', resuelto_por: 'admin' }))
    abrir()

    const ver = await screen.findByText('Ver PDF')
    expect(ver.closest('a')).toHaveAttribute('href', '/api/pre-facturas/7/pdf')
    expect(ver.closest('a')).toHaveAttribute('target', '_blank')
    const bajar = screen.getByText('Descargar PDF').closest('a')
    expect(bajar).toHaveAttribute('href', '/api/pre-facturas/7/pdf')
    expect(bajar).toHaveAttribute('download', 'PF-0007.pdf')
  })

  it('una anulada o una facturada no ofrece ninguna acción: sólo el PDF', async () => {
    servidor(pf('descartado', { motivo_descarte: 'Pedido repetido', resuelto_por: 'admin' }))
    abrir()
    await screen.findByText('Ver PDF')
    for (const boton of ['Enviar por correo', 'Editar', 'Marcar aceptada', 'Anular', 'Facturar por ARCA']) {
      expect(screen.queryByText(boton)).toBeNull()
    }
    expect(screen.getByText('Anulada por admin: Pedido repetido.')).toBeInTheDocument()
  })

  it('una facturada lleva a su comprobante', async () => {
    servidor(pf('facturado', { factura_id: 42, resuelto_at: '2026-08-21 09:00:00' }))
    abrir()
    const enlace = await screen.findByText('Ver el comprobante')
    expect(enlace.closest('a')).toHaveAttribute('href', '/comprobantes?ver=42')
    expect(screen.queryByText('Facturar por ARCA')).toBeNull()
  })

  it('editar lleva a la pantalla que cambia las órdenes', async () => {
    servidor(pf())
    abrir()
    fireEvent.click(await screen.findByText('Editar'))
    expect(await screen.findByText('Pantalla de editar')).toBeInTheDocument()
  })

  // ── Enviar por correo ────────────────────────────────────────────────────

  it('enviar por correo prellena el email del cliente y la deja enviada', async () => {
    servidor(pf(), { email: 'compras@agronorte.test' })
    post.mockImplementation(() => {
      actual = pf('enviado', { enviado_a: 'compras@agronorte.test', enviado_at: '2026-08-20 11:00:00' })
      return Promise.resolve(actual)
    })
    abrir()

    fireEvent.click(await screen.findByText('Enviar por correo'))
    const email = await screen.findByLabelText('Correo del cliente')
    await waitFor(() => expect(email).toHaveValue('compras@agronorte.test'))
    fireEvent.click(screen.getByText('Enviar'))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/pre-facturas/7/enviar-email', { email: 'compras@agronorte.test' }))
    expect(await screen.findByText('Enviada a compras@agronorte.test.')).toBeInTheDocument()
    expect(screen.getByText('Enviada')).toBeInTheDocument()
    expect(screen.getByText(/Enviada a compras@agronorte.test el 20-08-2026 11:00/)).toBeInTheDocument()
  })

  it('sin email cargado se escribe a mano, y sin arroba no se puede enviar', async () => {
    servidor(pf(), { email: null })
    abrir()
    fireEvent.click(await screen.findByText('Enviar por correo'))
    const email = await screen.findByLabelText('Correo del cliente')
    expect(email).toHaveValue('')
    expect(screen.getByText('Enviar')).toBeDisabled()
    fireEvent.change(email, { target: { value: 'otro@agronorte.test' } })
    expect(screen.getByText('Enviar')).toBeEnabled()
  })

  it('si el servidor no puede enviar (sin SMTP), dice qué falta', async () => {
    servidor(pf())
    post.mockRejectedValue(new ApiError(400, 'Configurá el servidor SMTP en Configuración → Email.'))
    abrir()
    fireEvent.click(await screen.findByText('Enviar por correo'))
    fireEvent.change(await screen.findByLabelText('Correo del cliente'),
                     { target: { value: 'compras@agronorte.test' } })
    fireEvent.click(screen.getByText('Enviar'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Configuración → Email')
  })

  // ── Aceptar ──────────────────────────────────────────────────────────────

  it('marcar aceptada la deja aceptada, y el botón desaparece', async () => {
    servidor(pf())
    post.mockImplementation(() => {
      actual = pf('aceptado', { aceptado_at: '2026-08-20 12:00:00', aceptado_por: 'admin' })
      return Promise.resolve(actual)
    })
    abrir()

    fireEvent.click(await screen.findByText('Marcar aceptada'))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/pre-facturas/7/aceptar', {}))
    expect(await screen.findByText('Aceptada')).toBeInTheDocument()
    expect(screen.queryByText('Marcar aceptada')).toBeNull()
    expect(screen.getByText(/Aceptada por el cliente el 20-08-2026 12:00 \(la marcó admin\)/)).toBeInTheDocument()
  })

  // ── Anular ───────────────────────────────────────────────────────────────

  it('anular pide un motivo y confirma antes de hacerlo', async () => {
    servidor(pf())
    post.mockImplementation(() => {
      actual = pf('descartado', { motivo_descarte: 'El cliente cambió el pedido', resuelto_por: 'admin' })
      return Promise.resolve(actual)
    })
    abrir()

    fireEvent.click(await screen.findByText('Anular'))
    const confirmar = await screen.findByText('Confirmar anulación')
    // Sin motivo no se puede: una anulación sin explicación no se entiende después.
    expect(confirmar).toBeDisabled()
    expect(post).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Motivo'), { target: { value: 'El cliente cambió el pedido' } })
    fireEvent.click(confirmar)

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/pre-facturas/7/anular', { motivo: 'El cliente cambió el pedido' }))
    expect(await screen.findByText(/Las órdenes quedaron libres/)).toBeInTheDocument()
    expect(screen.getByText('Anulada')).toBeInTheDocument()
  })

  it('"No" cierra la confirmación de anular sin hacer nada', async () => {
    servidor(pf())
    abrir()
    fireEvent.click(await screen.findByText('Anular'))
    fireEvent.click(await screen.findByText('No'))
    await waitFor(() => expect(screen.queryByText('Confirmar anulación')).toBeNull())
    expect(post).not.toHaveBeenCalled()
  })

  // ── Facturar por ARCA ────────────────────────────────────────────────────

  async function abrirFacturar(estado = 'aceptado') {
    servidor(pf(estado))
    abrir()
    fireEvent.click(await screen.findByText('Facturar por ARCA'))
    return screen.findByRole('dialog')
  }

  it('facturar pide confirmación y no hace nada hasta confirmar', async () => {
    const dialogo = await abrirFacturar()
    expect(within(dialogo).getByText(/ARCA le pone el número y el punto de venta/)).toBeInTheDocument()
    expect(within(dialogo).getByLabelText('Fecha del comprobante')).toHaveValue('2026-08-20')
    expect(post).not.toHaveBeenCalled()
    // Aceptada: no hay nada que advertir.
    expect(within(dialogo).queryByRole('note')).toBeNull()
  })

  it('si todavía no está aceptada, lo advierte pero deja facturar', async () => {
    const dialogo = await abrirFacturar('pendiente')
    expect(within(dialogo).getByRole('note')).toHaveTextContent('Todavía no está marcada como aceptada')
    expect(within(dialogo).getByText('Confirmar y facturar')).toBeEnabled()
  })

  it('al confirmar emite, muestra la factura con su CAE y deja la pre factura facturada', async () => {
    const dialogo = await abrirFacturar()
    post.mockImplementation(() => {
      actual = pf('facturado', { factura_id: 42 })
      return Promise.resolve(FACTURA)
    })
    fireEvent.change(within(dialogo).getByLabelText('Fecha del comprobante'), { target: { value: '2026-08-25' } })
    fireEvent.click(within(dialogo).getByText('Confirmar y facturar'))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/pre-facturas/7/facturar', { fecha: '2026-08-25' }))
    const panel = await screen.findByRole('status', { name: 'Factura emitida' })
    expect(panel).toHaveTextContent('Factura A 0005-00000042')
    expect(panel).toHaveTextContent('CAE 75123456789012')
    expect(within(panel).getByText('Ver el comprobante').closest('a')).toHaveAttribute('href', '/comprobantes?ver=42')
    expect(await screen.findByText('Facturada')).toBeInTheDocument()
    expect(screen.queryByText('Facturar por ARCA')).toBeNull()
  })

  it('sin certificado de ARCA muestra el error tal cual, y la pre factura sigue abierta', async () => {
    const dialogo = await abrirFacturar()
    post.mockRejectedValue(new ApiError(
      409, 'La razon social Suitrans no tiene configurado el certificado de ARCA: la pre factura '
        + 'queda lista para facturar cuando este'))
    fireEvent.click(within(dialogo).getByText('Confirmar y facturar'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La razon social Suitrans no tiene configurado el certificado de ARCA')
    expect(screen.queryByRole('status', { name: 'Factura emitida' })).toBeNull()
    expect(screen.getByText('Aceptada')).toBeInTheDocument()
    expect(screen.getByText('Facturar por ARCA')).toBeInTheDocument()
  })

  it('si ARCA rechaza, muestra el motivo de ARCA', async () => {
    const dialogo = await abrirFacturar()
    post.mockRejectedValue(new ApiError(502, 'ARCA rechazo el comprobante: El comprobante ya fue autorizado'))
    fireEvent.click(within(dialogo).getByText('Confirmar y facturar'))
    expect(await screen.findByRole('alert')).toHaveTextContent('ya fue autorizado')
  })

  it('un ensayo contra homologación NO es una factura: muestra qué contestó ARCA y no cierra nada', async () => {
    const dialogo = await abrirFacturar()
    post.mockResolvedValue({
      ensayo: true, ambiente: 'homologacion', tipo: 'factura_a', punto_venta: 5, numero: 42,
      total: '2420.00', cae: '75123456789012', cae_vencimiento: '2026-12-31',
    })
    fireEvent.click(within(dialogo).getByText('Confirmar y facturar'))

    const panel = await screen.findByRole('status', { name: 'Resultado del ensayo' })
    expect(panel).toHaveTextContent('no se guardó nada')
    expect(panel).toHaveTextContent('0005-00000042')
    expect(panel).toHaveTextContent('75123456789012')
    expect(screen.queryByRole('status', { name: 'Factura emitida' })).toBeNull()
    // Sigue abierta: se puede facturar de verdad cuando se pase a producción.
    expect(screen.getByText('Facturar por ARCA')).toBeInTheDocument()
    expect(screen.getByText('Aceptada')).toBeInTheDocument()
  })

  // ── Lo que no existe ─────────────────────────────────────────────────────

  it('una pre factura que no existe dice el motivo y vuelve a la lista', async () => {
    get.mockRejectedValue(new ApiError(404, 'no existe la pre factura 7'))
    abrir()
    expect(await screen.findByRole('alert')).toHaveTextContent('no existe la pre factura 7')
    expect(screen.getByText('Volver a Pre facturas').closest('a')).toHaveAttribute('href', '/pre-facturas')
  })
})
