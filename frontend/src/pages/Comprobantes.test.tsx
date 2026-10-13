import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

const { default: Comprobantes } = await import('./Comprobantes')
const { ApiError } = await import('libra-ui/api-client')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]

type Respuestas = {
  totales?: unknown
  comprobantes?: unknown[]
  ordenes?: unknown[]
}

function responder({ totales = total({ cantidad_comprobantes: 0, cantidad_ordenes: 0,
                                      total_comprobantes: '0.00', total_ordenes: '0.00' }), comprobantes = [], ordenes = [] }: Respuestas) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    // `/totales` primero: `/api/comprobantes` es prefijo suyo, y al reves esta
    // ruta contestaria la lista y el panel del gate quedaria siempre vacio.
    if (ruta.startsWith('/api/comprobantes/totales')) return Promise.resolve(totales)
    if (ruta.startsWith('/api/comprobantes')) return Promise.resolve(comprobantes)
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    return Promise.resolve([])
  })
}

function total(extra: Record<string, unknown> = {}) {
  return {
    cantidad_comprobantes: 1,
    neto_comprobantes: '1000.00', iva_comprobantes: '210.00',
    total_comprobantes: '1210.00',
    cantidad_ordenes: 1, neto_ordenes: '1000.00', iva_ordenes: '210.00',
    total_ordenes: '1210.00', coinciden: true, cantidad_sin_ordenes: 0, total_sin_ordenes: '0.00', ...extra,
  }
}

/** El detalle de un comprobante, como lo devuelve `GET /api/comprobantes/9`. */
function detalleDe(cae: string | null, tipo = 'factura_a', extra: Record<string, unknown> = {}) {
  return {
    comprobante: {
      id: 9, tipo, punto_venta: 5, numero: 42,
      fecha: '2026-08-15', cliente_id: 1, neto: '1000.00', iva: '210.00', total: '1210.00',
      anulado: false, origen_legado: null, cae,
    },
    ordenes: [],
    suma_de_ordenes: { cantidad: 0, neto: '0.00', iva: '0.00', total: '0.00' },
    coinciden: true,
    ...extra,
  }
}

function abrirDetalle(cae: string | null, tipo = 'factura_a', extra: Record<string, unknown> = {}) {
  responder({})
  const base = get.getMockImplementation()!
  get.mockImplementation((ruta?: string) =>
    ruta === '/api/comprobantes/9' ? Promise.resolve(detalleDe(cae, tipo, extra)) : base(ruta))
  render(<MemoryRouter initialEntries={['/comprobantes?ver=9']}><Comprobantes /></MemoryRouter>)
}

describe('Comprobantes', () => {
  beforeEach(() => { get.mockReset(); post.mockReset() })

  it('🔴 avisa cuando los dos lados NO coinciden', async () => {
    // Es la razon de que el endpoint devuelva los dos totales. Mostrar solo uno
    // haria que un total divergente se viera igual de confiable que uno sano.
    responder({ totales: total({ total_ordenes: '0.00', cantidad_ordenes: 0, coinciden: false }) })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toContain('NO')
    // Los dos numeros a la vista, no solo el de los comprobantes.
    expect(screen.getByText('1210.00')).toBeInTheDocument()
    expect(screen.getByText('0.00')).toBeInTheDocument()
  })

  it('con los dos totales iguales no aparece ninguna alarma', async () => {
    // El control del test de arriba: sin este, una pantalla que gritara SIEMPRE
    // pasaria igual y la alarma dejaria de significar algo.
    responder({ totales: total() })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)

    await waitFor(() => expect(screen.getAllByText('1210.00').length).toBe(2))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  // Los tests de facturar viven en `FacturarPendientes.test.tsx`: el flujo
  // dejo de ser un modal de esta pantalla y paso a ser una pantalla propia.
  // 🔴 Un comprobante con CAE no se anula desde acá: anular no llega a ARCA y el
  // comprobante seguiría vigente allá mientras sus órdenes se podrían facturar de nuevo.
  it('un comprobante con CAE no ofrece anular y dice por qué', async () => {
    abrirDetalle('75123456789012')

    const nota = await screen.findByRole('note')
    expect(nota).toHaveTextContent('75123456789012')
    expect(nota).toHaveTextContent('no se anula desde acá')
    expect(screen.queryByText('Anular comprobante')).toBeNull()
    expect(nota).toHaveTextContent('emití una nota de crédito')
  })

  // La nota de crédito sale de ARCA (motor) y es la forma de revertir lo que tiene CAE.
  it('una factura con CAE ofrece la nota de crédito, que pide un motivo y se confirma aparte', async () => {
    abrirDetalle('75123456789012')
    post.mockResolvedValue({ id: 10, tipo: 'nota_credito_a' })

    fireEvent.click(await screen.findByText('Emitir nota de crédito'))
    const confirmar = await screen.findByText('Confirmar nota de crédito')
    expect(confirmar).toBeDisabled() // sin motivo no se puede
    fireEvent.change(screen.getByLabelText('Motivo de la nota de crédito'),
      { target: { value: 'Error de tarifa' } })
    expect(confirmar).toBeEnabled()
    fireEvent.click(confirmar)

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/nota-de-credito', { motivo: 'Error de tarifa' }))
    // Sin importe, fecha ni tipo: los decide el servidor.
    expect(Object.keys(post.mock.calls[0][1])).toEqual(['motivo'])
  })

  it('contra homologación avisa que fue un ensayo y no se guardó nada', async () => {
    abrirDetalle('75123456789012')
    post.mockResolvedValue({ ensayo: true, ambiente: 'homologacion', cae: '99', tipo: 'nota_credito_a' })

    fireEvent.click(await screen.findByText('Emitir nota de crédito'))
    fireEvent.change(await screen.findByLabelText('Motivo de la nota de crédito'),
      { target: { value: 'Prueba' } })
    fireEvent.click(screen.getByText('Confirmar nota de crédito'))

    expect(await screen.findByRole('status')).toHaveTextContent('no se guardó nada')
  })

  // ── La nota parcial (ADR-028): el servidor manda lo acreditado y el saldo ──
  const SIN_NOTAS = { notas: [], acreditado: '0.00', saldo_acreditable: '1210.00' }

  function abrirNota(motivo = 'Diferencia de kilos') {
    return screen.findByText('Emitir nota de crédito').then((b) => {
      fireEvent.click(b)
      fireEvent.change(screen.getByLabelText('Motivo de la nota de crédito'), { target: { value: motivo } })
    })
  }

  it('con el saldo a la vista, la nota puede ser por un importe, que viaja como texto', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    post.mockResolvedValue({ id: 10, tipo: 'nota_credito_a' })
    await abrirNota()

    fireEvent.click(screen.getByLabelText('Por un importe'))
    fireEvent.change(screen.getByLabelText('Importe a acreditar (con IVA)'), { target: { value: '121,5' } })
    fireEvent.click(screen.getByText('Confirmar nota de crédito'))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/nota-de-credito', { motivo: 'Diferencia de kilos', importe: '121.50' }))
  })

  it('no deja confirmar un importe de más ni uno con tres decimales', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    await abrirNota()
    fireEvent.click(screen.getByLabelText('Por un importe'))
    const importe = screen.getByLabelText('Importe a acreditar (con IVA)')
    const confirmar = screen.getByText('Confirmar nota de crédito')

    fireEvent.change(importe, { target: { value: '1210.01' } })
    expect(confirmar).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Supera lo que queda por acreditar')
    fireEvent.change(importe, { target: { value: '1.234' } })
    expect(confirmar).toBeDisabled()
    fireEvent.change(importe, { target: { value: '1210' } })
    expect(confirmar).toBeEnabled()
  })

  it('con notas previas no ofrece la total, propone el saldo y las lista', async () => {
    abrirDetalle('75123456789012', 'factura_a', {
      notas: [{ id: 11, tipo: 'nota_credito_a', punto_venta: 5, numero: 43, fecha: '2026-10-05',
                total: '121.00', motivo: 'Kilos', anulado: false }],
      acreditado: '121.00', saldo_acreditable: '1089.00',
    })
    expect(await screen.findByText(/Nota de crédito A 0005-00000043/)).toBeInTheDocument()
    expect(screen.getByText(/queda por/)).toHaveTextContent('1.089,00')
    await abrirNota()

    expect(screen.getByLabelText('Por el total')).toBeDisabled()
    expect(screen.getByLabelText('Importe a acreditar (con IVA)')).toHaveValue('1089.00')
  })

  it('una FCE con CAE ofrece sólo la nota por un importe menor que el saldo', async () => {
    abrirDetalle('75123456789012', 'fce_a', SIN_NOTAS)
    expect(await screen.findByRole('note')).toHaveTextContent('menos que su saldo')
    await abrirNota()

    expect(screen.getByLabelText('Por el total')).toBeDisabled()
    const importe = screen.getByLabelText('Importe a acreditar (con IVA)')
    fireEvent.change(importe, { target: { value: '1210.00' } })
    expect(screen.getByText('Confirmar nota de crédito')).toBeDisabled()
    fireEvent.change(importe, { target: { value: '1209.99' } })
    expect(screen.getByText('Confirmar nota de crédito')).toBeEnabled()
  })

  it('el comprobante sin CAE (registrado a mano o migrado) se sigue pudiendo anular', async () => {
    abrirDetalle(null)

    expect(await screen.findByText('Anular comprobante')).toBeInTheDocument()
    expect(screen.queryByRole('note')).toBeNull()
  })

  // ── El PDF del comprobante (ADR-034) ──
  it('un comprobante con CAE ofrece ver y bajar el PDF, que se piden por enlace', async () => {
    abrirDetalle('75123456789012')

    const ver = (await screen.findByText('Ver PDF')).closest('a')!
    expect(ver).toHaveAttribute('href', '/api/comprobantes/9/pdf')
    expect(ver).toHaveAttribute('target', '_blank')
    const bajar = screen.getByText('Descargar PDF').closest('a')!
    expect(bajar).toHaveAttribute('href', '/api/comprobantes/9/pdf')
    expect(bajar).toHaveAttribute('download', 'Factura A 0005-00000042.pdf')
    expect(screen.getByText('Enviar por correo')).toBeInTheDocument()
  })

  it('una nota de crédito con CAE también tiene su PDF', async () => {
    abrirDetalle('75123456789012', 'nota_credito_a', { comprobante: {
      ...detalleDe('75123456789012', 'nota_credito_a').comprobante, comprobante_asociado_id: 3 } })
    const ver = (await screen.findByText('Ver PDF')).closest('a')!
    expect(ver).toHaveAttribute('href', '/api/comprobantes/9/pdf')
  })

  it('cada nota de la lista lleva el enlace a su PDF', async () => {
    abrirDetalle('75123456789012', 'factura_a', {
      notas: [{ id: 11, tipo: 'nota_credito_a', punto_venta: 5, numero: 43, fecha: '2026-10-05',
                total: '121.00', motivo: 'Kilos', anulado: false, cae: '75123456789099' }],
      acreditado: '121.00', saldo_acreditable: '1089.00',
    })
    const enlace = await screen.findByLabelText('PDF de la nota 0005-00000043')
    expect(enlace).toHaveAttribute('href', '/api/comprobantes/11/pdf')
  })

  it('🔴 un comprobante sin CAE (a mano o del legado) no ofrece PDF: parecería una factura que ARCA no conoce', async () => {
    abrirDetalle(null)

    expect(await screen.findByText('Anular comprobante')).toBeInTheDocument()
    expect(screen.queryByText('Ver PDF')).toBeNull()
    expect(screen.queryByText('Descargar PDF')).toBeNull()
    expect(screen.queryByText('Enviar por correo')).toBeNull()
  })

  it('enviar por correo prellena el correo del cliente y manda el PDF a ese destino', async () => {
    abrirDetalle('75123456789012')
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta?: string) =>
      ruta === '/api/terceros/1' ? Promise.resolve({ id: 1, email: 'compras@agronorte.test' }) : base(ruta))
    post.mockResolvedValue({ ok: true })

    fireEvent.click(await screen.findByText('Enviar por correo'))
    const campo = await screen.findByLabelText('Correo del cliente')
    await waitFor(() => expect(campo).toHaveValue('compras@agronorte.test'))
    fireEvent.click(screen.getByText('Enviar'))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/enviar-email', { email: 'compras@agronorte.test' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Enviado a compras@agronorte.test')
    expect(screen.queryByLabelText('Correo del cliente')).toBeNull()
  })

  it('sin correo cargado se tipea a mano, y no deja enviar uno que no es un correo', async () => {
    abrirDetalle('75123456789012')
    post.mockResolvedValue({ ok: true })

    fireEvent.click(await screen.findByText('Enviar por correo'))
    const campo = await screen.findByLabelText('Correo del cliente')
    expect(campo).toHaveValue('')
    expect(screen.getByText('Enviar')).toBeDisabled()
    fireEvent.change(campo, { target: { value: 'compras' } })
    expect(screen.getByText('Enviar')).toBeDisabled()
    fireEvent.change(campo, { target: { value: ' otro@agronorte.test ' } })
    fireEvent.click(screen.getByText('Enviar'))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/enviar-email', { email: 'otro@agronorte.test' }))
  })

  it('si el correo no sale, el error del servidor se ve en el detalle y el campo queda para reintentar', async () => {
    abrirDetalle('75123456789012')
    post.mockRejectedValue(new ApiError(400, 'Configurá el servidor SMTP en Configuración → Email.'))

    fireEvent.click(await screen.findByText('Enviar por correo'))
    fireEvent.change(await screen.findByLabelText('Correo del cliente'),
      { target: { value: 'compras@agronorte.test' } })
    fireEvent.click(screen.getByText('Enviar'))

    expect(await screen.findByText(/Configuración → Email/)).toBeInTheDocument()
    expect(screen.getByLabelText('Correo del cliente')).toHaveValue('compras@agronorte.test')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('🔑 no hay acceso a las pre facturas (se retiraron, ADR-048): los dos botones emiten directo por ARCA', async () => {
    responder({})
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    expect((await screen.findByText('Nueva factura')).closest('a')).toHaveAttribute('href', '/comprobantes/nueva')
    expect(screen.queryByText('Pre facturas')).toBeNull()
  })

  it('el boton de facturar lleva a la pantalla, no abre un modal', async () => {
    responder({})
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    const boton = await screen.findByText('Facturar pendientes')
    expect(boton.closest('a')).toHaveAttribute('href', '/comprobantes/facturar')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  // ── Las acciones de la fila: nota de crédito y nota de débito (ADR-048) ────
  function fila(id: number, tipo: string, extra: Record<string, unknown> = {}) {
    return {
      id, tipo, punto_venta: 5, numero: id + 40, fecha: '2026-08-15', cliente_id: 1, neto: '1000.00', iva: '210.00',
      total: '1210.00', anulado: false, origen_legado: null, cae: '75123456789012', ...extra,
    }
  }

  it('🔑 cada factura con CAE vigente tiene en su fila las acciones Nota de crédito y Nota de débito', async () => {
    responder({ comprobantes: [fila(9, 'factura_a')] })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    expect(await screen.findByRole('button', { name: /Nota de crédito de Factura A 0005-00000049/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Nota de débito de Factura A 0005-00000049/ })).toBeInTheDocument()
  })

  it('una FCE con CAE también las tiene', async () => {
    responder({ comprobantes: [fila(9, 'fce_a')] })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    expect(await screen.findByRole('button', { name: /Nota de crédito de Factura de crédito electrónica A/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Nota de débito de Factura de crédito electrónica A/ })).toBeInTheDocument()
  })

  it.each([
    ['una factura sin CAE (se anula, no se acredita)', fila(9, 'factura_a', { cae: null })],
    ['una factura anulada (ya está acreditada entera)', fila(9, 'factura_a', { anulado: true })],
    ['una nota de crédito (una nota no admite otra)', fila(9, 'nota_credito_a')],
    ['una nota de débito', fila(9, 'nota_debito_a')],
  ])('%s no muestra las acciones', async (_caso, comprobante) => {
    responder({ comprobantes: [comprobante] })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    expect(await screen.findByText(/0005-00000049/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Nota de crédito de/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Nota de débito de/ })).toBeNull()
  })

  it('«Nota de débito» de la fila abre el detalle con el formulario de la nota de débito ya abierto', async () => {
    responder({ comprobantes: [fila(9, 'factura_a')] })
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta?: string) =>
      ruta === '/api/comprobantes/9' ? Promise.resolve(detalleDe('75123456789012', 'factura_a', SIN_NOTAS)) : base(ruta))
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)

    fireEvent.click(await screen.findByRole('button', { name: /Nota de débito de Factura A/ }))
    expect(await screen.findByLabelText('Motivo de la nota de débito')).toBeInTheDocument()
    expect(screen.getByLabelText('Importe a debitar (con IVA)')).toBeInTheDocument()
    // Y el click de la fila no lo abrió una segunda vez ni lo cerró: sigue abierto el formulario de débito.
    expect(screen.queryByLabelText('Motivo de la nota de crédito')).toBeNull()
  })

  it('«Nota de crédito» de la fila abre el detalle con el formulario de la nota de crédito', async () => {
    responder({ comprobantes: [fila(9, 'factura_a')] })
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta?: string) =>
      ruta === '/api/comprobantes/9' ? Promise.resolve(detalleDe('75123456789012', 'factura_a', SIN_NOTAS)) : base(ruta))
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)

    fireEvent.click(await screen.findByRole('button', { name: /Nota de crédito de Factura A/ }))
    expect(await screen.findByLabelText('Motivo de la nota de crédito')).toBeInTheDocument()
    expect(screen.getByLabelText('Por el total')).toBeEnabled()
  })

  // ── La nota de débito (ADR-048): motivo e importe, sin total y sin tope ────
  it('el detalle de una factura con CAE ofrece las dos notas', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    expect(await screen.findByText('Emitir nota de débito')).toBeInTheDocument()
    expect(screen.getByText('Emitir nota de crédito')).toBeInTheDocument()
  })

  it('la nota de débito pide motivo e importe, viaja como texto y no tiene «por el total»', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    post.mockResolvedValue({ id: 10, tipo: 'nota_debito_a' })

    fireEvent.click(await screen.findByText('Emitir nota de débito'))
    const confirmar = await screen.findByText('Confirmar nota de débito')
    expect(confirmar).toBeDisabled()
    // No hay nota de débito total: no copia la factura. Va siempre por un importe.
    expect(screen.queryByLabelText('Por el total')).toBeNull()
    expect(screen.queryByLabelText('Por un importe')).toBeNull()

    fireEvent.change(screen.getByLabelText('Motivo de la nota de débito'), { target: { value: 'Intereses por mora' } })
    expect(confirmar).toBeDisabled() // falta el importe
    fireEvent.change(screen.getByLabelText('Importe a debitar (con IVA)'), { target: { value: '121,5' } })
    expect(confirmar).toBeEnabled()
    fireEvent.click(confirmar)

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/comprobantes/9/nota-de-debito', { motivo: 'Intereses por mora', importe: '121.50' }))
  })

  it('🔑 la nota de débito no tiene tope: un importe mayor que el total de la factura se puede confirmar', async () => {
    // El control de la diferencia con la de crédito, que no deja pasar del saldo (ver más arriba).
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    fireEvent.click(await screen.findByText('Emitir nota de débito'))
    fireEvent.change(screen.getByLabelText('Motivo de la nota de débito'), { target: { value: 'Diferencia de precio' } })
    const importe = screen.getByLabelText('Importe a debitar (con IVA)')
    fireEvent.change(importe, { target: { value: '5000.00' } })
    expect(screen.getByText('Confirmar nota de débito')).toBeEnabled()
    expect(screen.queryByText(/Supera lo que queda/)).toBeNull()
    // Pero sí tiene que ser un monto: mayor que cero y con dos decimales.
    for (const malo of ['0', '-5', '1.234', 'abc', '']) {
      fireEvent.change(importe, { target: { value: malo } })
      expect(screen.getByText('Confirmar nota de débito'), malo).toBeDisabled()
    }
  })

  it('contra homologación la nota de débito avisa que fue un ensayo', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    post.mockResolvedValue({ ensayo: true, ambiente: 'homologacion', cae: '99', tipo: 'nota_debito_a' })
    fireEvent.click(await screen.findByText('Emitir nota de débito'))
    fireEvent.change(screen.getByLabelText('Motivo de la nota de débito'), { target: { value: 'Prueba' } })
    fireEvent.change(screen.getByLabelText('Importe a debitar (con IVA)'), { target: { value: '10' } })
    fireEvent.click(screen.getByText('Confirmar nota de débito'))

    const aviso = await screen.findByRole('status')
    expect(aviso).toHaveTextContent('Ensayo contra homologacion')
    expect(aviso).toHaveTextContent('nota de débito de prueba')
    expect(aviso).toHaveTextContent('no se guardó nada')
  })

  it('si ARCA rechaza la nota de débito se ve el motivo', async () => {
    abrirDetalle('75123456789012', 'factura_a', SIN_NOTAS)
    post.mockRejectedValue(new ApiError(502, 'ARCA rechazo la nota de debito: IVA inconsistente'))
    fireEvent.click(await screen.findByText('Emitir nota de débito'))
    fireEvent.change(screen.getByLabelText('Motivo de la nota de débito'), { target: { value: 'Intereses' } })
    fireEvent.change(screen.getByLabelText('Importe a debitar (con IVA)'), { target: { value: '10' } })
    fireEvent.click(screen.getByText('Confirmar nota de débito'))
    expect(await screen.findByText(/IVA inconsistente/)).toBeInTheDocument()
  })

  it('la nota de débito de una FCE avisa que todavía no se probó contra ARCA', async () => {
    abrirDetalle('75123456789012', 'fce_a', SIN_NOTAS)
    fireEvent.click(await screen.findByText('Emitir nota de débito'))
    const avisos = screen.getAllByRole('note')
    expect(avisos.map((n) => n.textContent).join(' ')).toContain('todavía no se probó contra ARCA')
  })

  it('las notas de débito de una factura se listan aparte de las de crédito, con su PDF', async () => {
    abrirDetalle('75123456789012', 'factura_a', {
      ...SIN_NOTAS,
      notas_debito: [{ id: 12, tipo: 'nota_debito_a', punto_venta: 5, numero: 7, fecha: '2026-10-13',
                       total: '605.00', motivo: 'Intereses por mora', anulado: false, cae: '75123456789098' }],
    })
    expect(await screen.findByText('Notas de débito')).toBeInTheDocument()
    expect(screen.getByText(/Nota de débito A 0005-00000007/)).toBeInTheDocument()
    expect(screen.getByText(/Intereses por mora/)).toBeInTheDocument()
    expect(screen.getByLabelText('PDF de la nota 0005-00000007')).toHaveAttribute('href', '/api/comprobantes/12/pdf')
    expect(screen.queryByText('Notas de crédito')).toBeNull()
  })

  it('una nota de débito se muestra como tal: a qué factura suma, con su PDF, y sin ofrecer más notas', async () => {
    abrirDetalle('75123456789012', 'nota_debito_a', {
      comprobante: { ...detalleDe('75123456789012', 'nota_debito_a').comprobante,
        comprobante_asociado_id: 3, motivo: 'Intereses', sin_ordenes: true },
    })
    expect(await screen.findByText(/Suma al comprobante #3/)).toBeInTheDocument()
    expect(screen.getByText('Ver PDF')).toBeInTheDocument()
    expect(screen.queryByText('Emitir nota de débito')).toBeNull()
    expect(screen.queryByText('Emitir nota de crédito')).toBeNull()
    expect(screen.queryByText(/Suma de sus/)).toBeNull()
  })

  it('una factura directa no agrupa órdenes: no muestra la suma de sus órdenes ni marca alarma', async () => {
    abrirDetalle('75123456789012', 'factura_b', {
      comprobante: { ...detalleDe('75123456789012', 'factura_b').comprobante, sin_ordenes: true },
      ...SIN_NOTAS,
    })
    expect(await screen.findByText('Factura directa: no agrupa órdenes ni remitos.')).toBeInTheDocument()
    expect(screen.queryByText(/Suma de sus/)).toBeNull()
    expect(screen.queryByText(/no dice lo mismo que sus órdenes/)).toBeNull()
    // Y se corrige como cualquier factura con CAE.
    expect(screen.getByText('Emitir nota de crédito')).toBeInTheDocument()
  })

  it('los comprobantes sin órdenes se cuentan aparte del gate, que no se pone en rojo', async () => {
    responder({ totales: total({ cantidad_sin_ordenes: 2, total_sin_ordenes: '1815.00' }) })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    expect(await screen.findByText(/2 comprobante\/s sin órdenes/)).toHaveTextContent('1815.00')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('con sólo facturas directas el panel aparece igual', async () => {
    responder({ totales: total({
      cantidad_comprobantes: 0, cantidad_ordenes: 0, total_comprobantes: '0.00', total_ordenes: '0.00',
      cantidad_sin_ordenes: 1, total_sin_ordenes: '605.00' }) })
    render(<MemoryRouter><Comprobantes /></MemoryRouter>)
    expect(await screen.findByText(/1 comprobante\/s sin órdenes/)).toBeInTheDocument()
  })
})
