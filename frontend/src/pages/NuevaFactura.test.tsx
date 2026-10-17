/** Los tests de «Nueva factura» (ADR-048): conceptos libres, directo por ARCA.
 *
 * Lo que se mide: que la clase de comprobante la ofrece la empresa según el cliente, que la vista previa suma como el servidor,
 * que **no deja emitir** con alícuotas mezcladas ni con renglones a medio cargar (y dice por qué), que el botón pide confirmar
 * antes de emitir algo que no se deshace, y qué viaja en el POST: los conceptos y nada de importes, punto de venta ni número.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable, opcionesDe } from '@/test/buscable'

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

const { default: NuevaFactura } = await import('./NuevaFactura')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]
const CUENTAS = {
  cuentas: [
    { cbu: '0110599520000001234567', alias: 'agencia.nacion', etiqueta: 'Nación' },
    { cbu: '0070999030004001234567', alias: 'agencia.galicia', etiqueta: 'Galicia' },
  ],
  predeterminada: '0070999030004001234567',
  transmision: 'SCA',
}

type Tipos = { tipos: string[]; sugerido: string | null; fce_habilitada: boolean; problema: string | null }
const INSCRIPTO_A_INSCRIPTO: Tipos = { tipos: ['factura_a'], sugerido: 'factura_a', fce_habilitada: false, problema: null }

/** Lo que contesta el servidor; `tipos` es lo que `GET /api/comprobantes/tipos` devuelve según el cliente. */
function responder(tipos: Tipos | ((ruta: string) => Tipos) = INSCRIPTO_A_INSCRIPTO) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/comprobantes/tipos')) return Promise.resolve(typeof tipos === 'function' ? tipos(ruta) : tipos)
    if (ruta === '/api/comprobantes/fce/cuentas') return Promise.resolve(CUENTAS)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    return Promise.resolve([])
  })
}

async function abrir(ruta = '/comprobantes/nueva', elegirCliente = true) {
  render(
    <MemoryRouter initialEntries={[ruta]}>
      <Routes>
        <Route path="/comprobantes/nueva" element={<NuevaFactura />} />
        <Route path="/comprobantes" element={<p>Pantalla de los comprobantes</p>} />
        <Route path="/comprobantes/facturar" element={<p>Pantalla de facturar pendientes</p>} />
      </Routes>
    </MemoryRouter>)
  const campoCliente = await screen.findByLabelText('Cliente')
  await waitFor(() => expect(opcionesDe(campoCliente)).toEqual(['Elegir…', 'Agro Norte']))
  if (elegirCliente) await act(async () => { await elegirEnBuscable(campoCliente, 'Agro Norte') })
}

const descripcion = (n = 1) => screen.getByLabelText(`Descripción del concepto ${n}`)
const cantidad = (n = 1) => screen.getByLabelText(`Cantidad del concepto ${n}`)
const precio = (n = 1) => screen.getByLabelText(new RegExp(`^(Precio|Importe) del concepto ${n}$`))
/** Las clases que ofrece el selector de tipo (no las alícuotas, que también son `<option>`). */
const clases = () => within(screen.getByLabelText('Tipo')).getAllByRole('option').map((o) => o.textContent)
const alicuota = (n = 1) => screen.getByLabelText(`Alícuota de IVA del concepto ${n}`)
const escribir = (campo: HTMLElement, valor: string) => fireEvent.change(campo, { target: { value: valor } })

/** Un concepto completo en el renglón `n`. */
function cargar(n: number, d = 'Flete Suipacha - Rosario', c = '1', p = '1000.00') {
  escribir(descripcion(n), d)
  escribir(cantidad(n), c)
  escribir(precio(n), p)
}

async function emitir() {
  fireEvent.click(screen.getByText('Emitir factura'))
  fireEvent.click(await screen.findByText('Confirmar y emitir'))
}

describe('Nueva factura', () => {
  beforeEach(() => { get.mockReset(); post.mockReset() })

  it('🔑 el cliente que no está cargado se da de alta ahí mismo (con CUIT y condición de IVA) y queda elegido para la factura', async () => {
    responder()
    post.mockResolvedValue({ id: 77, razon_social: 'Cereales del Sur', cuit: '30-71234567-8', es_cliente: true })
    await abrir('/comprobantes/nueva', false)
    fireEvent.click(screen.getByRole('button', { name: 'Agregar nuevo cliente' }))
    const panel = await screen.findByRole('group', { name: 'Nuevo cliente' })
    fireEvent.change(within(panel).getByLabelText('Nombre *'), { target: { value: 'Cereales del Sur' } })
    fireEvent.change(within(panel).getByLabelText('CUIT'), { target: { value: '30-71234567-8' } })
    fireEvent.click(within(panel).getByRole('combobox', { name: 'Condición frente al IVA' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Responsable Inscripto' }))
    fireEvent.click(within(panel).getByRole('button', { name: 'Crear cliente' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros', {
      razon_social: 'Cereales del Sur', es_cliente: true, cuit: '30-71234567-8', condicion_iva: 'responsable_inscripto',
    }))
    // Queda elegido, y la pantalla pide las clases de comprobante de ESE cliente.
    await waitFor(() => expect(screen.getByLabelText('Cliente')).toHaveValue('Cereales del Sur'))
    await waitFor(() => expect(get).toHaveBeenCalledWith(expect.stringContaining('/api/comprobantes/tipos?cliente_id=77')))
  })

  it('es una pantalla con su título, y no un modal', async () => {
    responder()
    await abrir()
    expect(screen.getByRole('heading', { name: 'Nueva factura' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('link', { name: 'Volver a Comprobantes' })).toHaveAttribute('href', '/comprobantes')
  })

  it('no pide punto de venta, número ni razón social: los pone ARCA y el emisor es la empresa', async () => {
    responder()
    await abrir()
    for (const nombre of ['Punto de venta', 'Número', 'Razón social']) expect(screen.queryByLabelText(nombre)).toBeNull()
  })

  it('ofrece sólo las clases que le corresponden a la empresa y a ese cliente, y arranca en la sugerida', async () => {
    responder((ruta) => (ruta.includes('cliente_id=1')
      ? { tipos: ['factura_a'], sugerido: 'factura_a', fce_habilitada: false, problema: null }
      : { tipos: ['factura_a', 'factura_b'], sugerido: null, fce_habilitada: false, problema: null }))
    await abrir('/comprobantes/nueva', false)
    // Sin cliente, las dos del inscripto.
    await waitFor(() => expect(clases()).toEqual(['Factura A', 'Factura B']))

    await act(async () => { await elegirEnBuscable(screen.getByLabelText('Cliente'), 'Agro Norte') })
    await waitFor(() => expect(clases()).toEqual(['Factura A']))
    expect((screen.getByLabelText('Tipo') as HTMLSelectElement).value).toBe('factura_a')
    expect(get.mock.calls.map((c) => String(c[0]))).toContain('/api/comprobantes/tipos?cliente_id=1')
  })

  it('si la empresa no puede emitir ninguna clase (sin condición de IVA), lo dice y no deja emitir', async () => {
    responder({ tipos: [], sugerido: null, fce_habilitada: false, problema: 'La empresa no tiene cargada la condición de IVA: cargala en Datos de la empresa.' })
    await abrir()
    cargar(1)
    expect((await screen.findAllByText(/no tiene cargada la condición de IVA/)).length).toBeGreaterThan(0)
    expect(screen.getByText('Emitir factura')).toBeDisabled()
  })

  it('la vista previa calcula el IVA una vez sobre el neto, en centavos enteros', async () => {
    responder()
    await abrir()
    cargar(1, 'Flete', '3', '33.33')
    fireEvent.click(screen.getByText('Agregar concepto'))
    cargar(2, 'Peaje', '2', '10.01')

    expect(screen.getByText(/Neto \$ 120,01 · IVA \$ 25,20/)).toBeInTheDocument()
    expect(screen.getByText('Total: $ 145,21')).toBeInTheDocument()
  })

  it('sin nada cargado no deja emitir, y dice qué falta', async () => {
    responder()
    await abrir('/comprobantes/nueva', false)
    expect(screen.getByText('Emitir factura')).toBeDisabled()
    expect(screen.getByText('Elegí el cliente.')).toBeInTheDocument()

    await act(async () => { await elegirEnBuscable(screen.getByLabelText('Cliente'), 'Agro Norte') })
    expect(await screen.findByText('Falta la descripción de un concepto.')).toBeInTheDocument()
    escribir(descripcion(), 'Flete')
    escribir(precio(), '')
    expect(screen.getByText(/El precio de cada concepto tiene que ser mayor que cero/)).toBeInTheDocument()
    escribir(precio(), '1000.005')
    expect(screen.getByText(/hasta dos decimales/)).toBeInTheDocument()
    escribir(precio(), '1000')
    escribir(cantidad(), '0')
    expect(screen.getByText(/La cantidad de cada concepto tiene que ser mayor que cero/)).toBeInTheDocument()
    escribir(cantidad(), '1.5')
    expect(screen.getByText('Emitir factura')).toBeEnabled()
  })

  it('🔑 con alícuotas mezcladas no deja emitir y explica que ARCA recibe un solo bloque de IVA', async () => {
    responder()
    await abrir()
    cargar(1)
    fireEvent.click(screen.getByText('Agregar concepto'))
    cargar(2, 'Seguro', '1', '100.00')
    expect(screen.getByText('Emitir factura')).toBeEnabled()

    fireEvent.change(alicuota(2), { target: { value: '10.5' } })
    expect(screen.getByText('Emitir factura')).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('ARCA recibe un solo bloque de IVA')
    expect(screen.getByRole('alert')).toHaveTextContent('emití una factura por alícuota')
    // El control: volver a la misma alícuota lo habilita.
    fireEvent.change(alicuota(2), { target: { value: '21' } })
    expect(screen.getByText('Emitir factura')).toBeEnabled()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('un concepto nuevo arranca con la alícuota del primero, y se puede quitar (menos el último)', async () => {
    responder()
    await abrir()
    fireEvent.change(alicuota(1), { target: { value: '10.5' } })
    fireEvent.click(screen.getByText('Agregar concepto'))
    expect(alicuota(2)).toHaveValue('10.5')

    expect(screen.getByLabelText('Quitar el concepto 1')).toBeEnabled()
    fireEvent.click(screen.getByLabelText('Quitar el concepto 2'))
    expect(screen.queryByLabelText('Descripción del concepto 2')).toBeNull()
    expect(screen.getByLabelText('Quitar el concepto 1')).toBeDisabled()
  })

  it('🔑 emite directo por ARCA: pide confirmar y manda los conceptos, sin importes ni punto de venta ni número', async () => {
    responder()
    post.mockResolvedValue({ id: 9 })
    await abrir()
    cargar(1, '  Flete Suipacha - Rosario ', '1,5', '1000,50')
    escribir(screen.getByLabelText(/Observaciones/), 'Entrega del 14')

    fireEvent.click(screen.getByText('Emitir factura'))
    expect(post).not.toHaveBeenCalled()
    expect(screen.getByText('Se emite por ARCA ahora y no se deshace.')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Confirmar y emitir'))

    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/api/comprobantes/directa')
    expect(post.mock.calls[0][1]).toEqual({
      cliente_id: 1, tipo: 'factura_a', fecha: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      conceptos: [{ descripcion: 'Flete Suipacha - Rosario', cantidad: '1.5', precio_unitario: '1000.50', alicuota_iva: '21' }],
      observaciones: 'Entrega del 14',
    })
    const cuerpo = JSON.parse(JSON.stringify(post.mock.calls[0][1]))
    for (const campo of ['punto_venta', 'numero', 'neto', 'iva', 'total', 'orden_ids', 'fecha_vencimiento_pago', 'fce_cbu']) {
      expect(cuerpo, campo).not.toHaveProperty(campo)
    }
  })

  it('cambiar un concepto desarma la confirmación: no se confirma una cosa y se emite otra', async () => {
    responder()
    post.mockResolvedValue({ id: 9 })
    await abrir()
    cargar(1)
    fireEvent.click(screen.getByText('Emitir factura'))
    expect(screen.getByText('Confirmar y emitir')).toBeInTheDocument()
    escribir(precio(), '2000.00')
    expect(screen.queryByText('Confirmar y emitir')).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })

  it('tras emitir abre el comprobante', async () => {
    responder()
    post.mockResolvedValue({ id: 9 })
    await abrir()
    cargar(1)
    await emitir()
    expect(await screen.findByText('Pantalla de los comprobantes')).toBeInTheDocument()
  })

  it('contra homologación avisa que fue un ensayo y no guarda nada', async () => {
    responder()
    post.mockResolvedValue({
      ensayo: true, ambiente: 'homologacion', tipo: 'factura_a', punto_venta: 5, numero: 42, total: '1210.00',
      cae: '75123456789012', cae_vencimiento: '2026-12-31',
    })
    await abrir()
    cargar(1)
    await emitir()
    expect(await screen.findByRole('status')).toHaveTextContent('Ensayo contra homologacion')
    expect(screen.getByRole('status')).toHaveTextContent('no se guardó nada')
    expect(screen.queryByText('Pantalla de los comprobantes')).toBeNull()
    expect(screen.getByText('Emitir factura')).toBeEnabled()
  })

  it('si el servidor rechaza (sin certificado, ARCA), muestra el motivo, se queda y se puede reintentar', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    responder()
    post.mockRejectedValue(new ApiError(409, 'ARCA no está configurado: cargá el certificado. No se emitió nada'))
    await abrir()
    cargar(1)
    await emitir()
    expect(await screen.findByRole('alert')).toHaveTextContent('No se emitió nada')
    expect(screen.queryByText('Pantalla de los comprobantes')).toBeNull()
    expect(screen.getByText('Emitir factura')).toBeEnabled()
  })

  // ── Clase C: sin IVA discriminado ────────────────────────────────────────
  it('una clase C no pide alícuota: el importe es el total y no se manda IVA', async () => {
    responder({ tipos: ['factura_c'], sugerido: 'factura_c', fce_habilitada: false, problema: null })
    post.mockResolvedValue({ id: 9 })
    await abrir()
    cargar(1, 'Flete', '1', '1000.00')

    expect(screen.queryByLabelText('Alícuota de IVA del concepto 1')).toBeNull()
    expect(screen.getByLabelText('Importe del concepto 1')).toBeInTheDocument()
    expect(screen.getByText('Total: $ 1.000,00')).toBeInTheDocument()
    expect(screen.queryByText(/IVA \$/)).toBeNull()
    await emitir()
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1].tipo).toBe('factura_c')
  })

  // ── FCE ──────────────────────────────────────────────────────────────────
  async function elegirFce() {
    responder({ tipos: ['factura_a', 'fce_a'], sugerido: 'factura_a', fce_habilitada: true, problema: null })
    post.mockResolvedValue({ id: 9 })
    await abrir()
    cargar(1, 'Flete', '1', '5000.00')
    fireEvent.change(screen.getByLabelText('Fecha'), { target: { value: '2026-08-15' } })
    fireEvent.change(screen.getByLabelText('Tipo'), { target: { value: 'fce_a' } })
  }

  it('una FCE pide el vencimiento, propuesto a 30 días, y la cuenta de cobro', async () => {
    await elegirFce()
    expect(screen.getByLabelText('Vencimiento de pago')).toHaveValue('2026-09-14')
    const cuenta = await screen.findByLabelText('Cobrar en')
    expect(cuenta).toHaveValue('agencia.galicia · CBU 0070999030004001234567 · Galicia (predeterminada)')
    escribir(screen.getByLabelText('Vencimiento de pago'), '')
    expect(screen.getByText('Emitir factura')).toBeDisabled()
    expect(screen.getByText('Falta el vencimiento de pago.')).toBeInTheDocument()
    escribir(screen.getByLabelText('Vencimiento de pago'), '2026-08-01')
    expect(screen.getByText('El vencimiento de pago no puede ser anterior a la fecha del comprobante.')).toBeInTheDocument()
  })

  it('una FCE viaja con el vencimiento y la cuenta elegida, reconocida por su alias', async () => {
    await elegirFce()
    await elegirEnBuscable(await screen.findByLabelText('Cobrar en'), /^agencia\.nacion · /)
    await emitir()
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toMatchObject({
      tipo: 'fce_a', fecha: '2026-08-15', fecha_vencimiento_pago: '2026-09-14', fce_cbu: '0110599520000001234567',
    })
  })

  it('una factura común no manda vencimiento ni cuenta', async () => {
    responder({ tipos: ['factura_a', 'fce_a'], sugerido: 'factura_a', fce_habilitada: true, problema: null })
    post.mockResolvedValue({ id: 9 })
    await abrir()
    cargar(1)
    expect(screen.queryByLabelText('Vencimiento de pago')).toBeNull()
    expect(screen.queryByLabelText('Cobrar en')).toBeNull()
    await emitir()
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(JSON.parse(JSON.stringify(post.mock.calls[0][1]))).not.toHaveProperty('fecha_vencimiento_pago')
  })

  // ── La entrada ───────────────────────────────────────────────────────────
  it('con ?cliente= llega con el cliente ya elegido, y tiene el acceso a «Facturar pendientes» del mismo cliente', async () => {
    responder()
    await abrir('/comprobantes/nueva?cliente=1', false)
    await waitFor(() => expect(get.mock.calls.map((c) => String(c[0]))).toContain('/api/comprobantes/tipos?cliente_id=1'))
    expect(screen.getByRole('link', { name: 'Facturar pendientes' })).toHaveAttribute('href', '/comprobantes/facturar?cliente=1')
  })
})
