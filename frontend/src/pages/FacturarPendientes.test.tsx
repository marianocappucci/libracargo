/** Los tests de «Facturar pendientes», que desde ADR-032 **genera la pre factura**.
 *
 * Nacieron como cuatro adentro de `Comprobantes.test.tsx` y probaban el `<Dialog>`; se mudaron a la pantalla.
 * La lógica que cubren —qué órdenes se ofrecen, cómo suma la vista previa, qué viaja en el POST— sigue: lo que
 * cambió es que ya no se factura acá. No hay punto de venta ni número (no se tipean más: el de la pre factura
 * lo pone el motor y el de la factura, ARCA), y el botón genera la pre factura y lleva a ella. La misma pantalla
 * edita una pre factura abierta (`/pre-facturas/:id/editar`).
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable, opcionesDe } from '@/test/buscable'

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
  return { ApiError, api: { get, post, put, del: vi.fn() } }
})

const { default: FacturarPendientes } = await import('./FacturarPendientes')
const { default: EditarPreFactura } = await import('./EditarPreFactura')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]

function responder(ordenes: unknown[] = [], propias: unknown[] = []) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    // Las reservadas en la pre factura que se edita, aparte de las libres.
    if (ruta.startsWith('/api/ordenes') && ruta.includes('pre_factura_id=')) return Promise.resolve(propias)
    if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta === '/api/comprobantes/fce/cuentas') return Promise.resolve(CUENTAS)
    return Promise.resolve([])
  })
}

/** Las cuentas de la empresa para cobrar una FCE (libracore ADR-040); Galicia es la predeterminada. */
const CUENTAS = {
  cuentas: [
    { cbu: '0110599520000001234567', alias: 'agencia.nacion', etiqueta: 'Nación' },
    { cbu: '0070999030004001234567', alias: 'agencia.galicia', etiqueta: 'Galicia' },
  ],
  predeterminada: '0070999030004001234567',
  transmision: 'SCA',
}

function orden(id: number, extra: Record<string, unknown> = {}) {
  return {
    id, fecha: '2026-08-10', cliente_id: 1, origen_id: 1, destino_id: 2,
    fletero_id: null, chofer_id: null, vehiculo_id: null, tipo_carga_id: null,
    remito: null, cantidad: null, unidad: null,
    tarifa: '1000.00', alicuota_iva: '21.00', iva: '210.00', total: '1210.00',
    comision: '0.00', estado: 'pendiente', comprobante_id: null,
    observaciones: null, ...extra,
  }
}

/** Monta la pantalla con las rutas a las que navega, y elige el cliente (por su nombre: el campo se busca escribiendo). */
async function abrir(cliente = 'Agro Norte') {
  render(
    <MemoryRouter initialEntries={['/comprobantes/facturar']}>
      <Routes>
        <Route path="/comprobantes/facturar" element={<FacturarPendientes />} />
        <Route path="/pre-facturas/:id" element={<p>Pantalla de la pre factura</p>} />
      </Routes>
    </MemoryRouter>)
  const campoCliente = await screen.findByLabelText('Cliente')
  await waitFor(() => expect(opcionesDe(campoCliente)).toEqual(['Elegir…', 'Agro Norte']))
  // Dentro de act: elegir el cliente dispara el pedido de las pendientes, y
  // ese estado llega despues del evento. Sin esto React avisa que la
  // actualizacion quedo afuera, y lo que se assertee puede ser el estado previo.
  await act(async () => {
    await elegirEnBuscable(campoCliente, cliente)
  })
}

const casilla = (id: number) => screen.getByLabelText(`Elegir la orden ${id}`)

describe('Facturar pendientes', () => {
  beforeEach(() => { get.mockReset(); post.mockReset(); put.mockReset() })

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

  it('no pide la razón social: el emisor es la empresa (ADR-035)', async () => {
    responder([orden(1)])
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    expect(screen.queryByLabelText('Razón social')).toBeNull()
  })

  it('la vista previa suma lo elegido, y sin nada elegido no deja facturar', async () => {
    responder([orden(1, { total: '0.10' }), orden(2, { total: '0.20' })])
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    expect(screen.getByText('Total: $ 0,00')).toBeInTheDocument()
    expect(screen.getByText('Generar pre factura')).toBeDisabled()
    expect(screen.getByText('No elegiste ninguna orden.')).toBeInTheDocument()

    fireEvent.click(casilla(1))
    fireEvent.click(casilla(2))
    // 0.10 + 0.20 en punto flotante da 0.30000000000000004: la suma va en
    // centavos enteros justamente por esto.
    expect(screen.getByText('Total: $ 0,30')).toBeInTheDocument()
    expect(screen.getByText('Generar pre factura')).toBeEnabled()
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

  it('genera la pre factura de las ordenes elegidas y va a ella', async () => {
    responder([orden(1)])
    post.mockResolvedValue({ id: 9 })
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    fireEvent.click(screen.getByText('Generar pre factura'))

    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/api/pre-facturas')
    expect(post.mock.calls[0][1]).toMatchObject({
      cliente_id: 1, tipo: 'factura_a', orden_ids: [1],
    })
    expect(post.mock.calls[0][1]).not.toHaveProperty('razon_social_id')
    // 🔴 Se sacó el registro a mano: ni el punto de venta ni el número viajan, ni se ofrecen.
    expect(post.mock.calls[0][1]).not.toHaveProperty('punto_venta')
    expect(post.mock.calls[0][1]).not.toHaveProperty('numero')
    expect(await screen.findByText('Pantalla de la pre factura')).toBeInTheDocument()
  })

  it('no pide punto de venta ni número', async () => {
    // El control de lo de arriba: que el POST no los mande no alcanza si el formulario los sigue pidiendo.
    responder([orden(1)])
    await abrir()
    expect(screen.queryByLabelText('Punto de venta')).toBeNull()
    expect(screen.queryByLabelText('Número')).toBeNull()
    expect(screen.queryByText('Facturar')).toBeNull()
  })

  it('sólo ofrece las ordenes libres: las reservadas en otra pre factura no se piden', async () => {
    responder([orden(1)])
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    const pedidas = get.mock.calls.map((c) => String(c[0])).filter((r) => r.startsWith('/api/ordenes'))
    expect(pedidas.length).toBeGreaterThan(0)
    expect(pedidas.every((r) => r.includes('reservada=false'))).toBe(true)
  })

  it('si el servidor rechaza, muestra el motivo y se queda', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    responder([orden(1)])
    post.mockRejectedValue(new ApiError(409, 'la orden 1 ya esta en la pre factura PF-0003'))
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    fireEvent.click(screen.getByText('Generar pre factura'))

    expect(await screen.findByRole('alert')).toHaveTextContent('ya esta en la pre factura PF-0003')
    expect(screen.queryByText('Pantalla de la pre factura')).toBeNull()
    expect(screen.getByText('Generar pre factura')).toBeEnabled()
  })

  // ── La Factura de Crédito Electrónica MiPyME ─────────────────────────────
  //
  // Se emite sólo por ARCA, que da el número. En cambio exige el vencimiento de
  // pago, y sin él ARCA la rechaza. La pantalla es la misma: el selector tiene
  // tres opciones más y aparece el campo del vencimiento.

  async function elegirFce(fecha = '2026-08-15') {
    responder([orden(1)])
    post.mockResolvedValue({ id: 9 })
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Fecha', { selector: '#n-fecha' }),
                     { target: { value: fecha } })
    fireEvent.change(screen.getByLabelText('Tipo', { selector: '#n-tipo' }),
                     { target: { value: 'fce_a' } })
    fireEvent.click(casilla(1))
  }

  it('una FCE pide el vencimiento de pago, a 30 días', async () => {
    await elegirFce('2026-08-15')

    expect(screen.getByLabelText('Vencimiento de pago')).toHaveValue('2026-09-14')
  })

  it('una FCE viaja con el vencimiento', async () => {
    await elegirFce('2026-08-15')
    fireEvent.change(screen.getByLabelText('Vencimiento de pago'),
                     { target: { value: '2026-10-01' } })
    fireEvent.click(screen.getByText('Generar pre factura'))

    await waitFor(() => expect(post).toHaveBeenCalled())
    const cuerpo = post.mock.calls[0][1]
    expect(cuerpo).toMatchObject({
      tipo: 'fce_a', fecha_vencimiento_pago: '2026-10-01', orden_ids: [1],
    })
  })

  it('una FCE muestra en qué cuenta se cobra: arranca en la predeterminada y no la manda', async () => {
    await elegirFce('2026-08-15')
    const cuenta = await screen.findByLabelText('Cobrar en')
    expect(cuenta).toHaveValue('agencia.galicia · CBU 0070999030004001234567 · Galicia (predeterminada)')
    expect(opcionesDe(cuenta)).toContain('agencia.nacion · CBU 0110599520000001234567 · Nación')
    fireEvent.click(screen.getByText('Generar pre factura'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toMatchObject({ fce_cbu: '' })
  })

  it('una FCE puede cobrarse en otra cuenta, reconocida por su alias', async () => {
    await elegirFce('2026-08-15')
    await elegirEnBuscable(await screen.findByLabelText('Cobrar en'), /^agencia\.nacion · /)
    fireEvent.click(screen.getByText('Generar pre factura'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toMatchObject({ tipo: 'fce_a', fce_cbu: '0110599520000001234567' })
  })

  it('una factura común no pide cuenta ni la manda', async () => {
    responder([orden(1)])
    post.mockResolvedValue({ id: 9 })
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    expect(screen.queryByLabelText('Cobrar en')).toBeNull()
    fireEvent.click(screen.getByText('Generar pre factura'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    // `undefined` no viaja: lo que importa es el JSON que sale.
    expect(JSON.parse(JSON.stringify(post.mock.calls[0][1]))).not.toHaveProperty('fce_cbu')
  })

  it('sin vencimiento de pago una FCE no se puede facturar', async () => {
    await elegirFce()
    fireEvent.change(screen.getByLabelText('Vencimiento de pago'), { target: { value: '' } })

    expect(screen.getByText('Generar pre factura')).toBeDisabled()
    expect(screen.getByText('Falta el vencimiento de pago.')).toBeInTheDocument()
  })

  it('si la fecha pasa del vencimiento propuesto, la FCE no se puede facturar', async () => {
    // La fecha se puede cambiar DESPUÉS de elegir FCE: el vencimiento propuesto a 30
    // días queda atrás y el backend la rechazaría con un 422.
    await elegirFce('2026-08-15')
    fireEvent.change(screen.getByLabelText('Fecha', { selector: '#n-fecha' }),
                     { target: { value: '2026-12-01' } })

    expect(screen.getByText('Generar pre factura')).toBeDisabled()
    expect(screen.getByText('El vencimiento de pago no puede ser anterior a la fecha del comprobante.'))
      .toBeInTheDocument()
  })

  it('una factura común no manda vencimiento, y al volver a ella desaparece el campo', async () => {
    await elegirFce()
    fireEvent.change(screen.getByLabelText('Tipo', { selector: '#n-tipo' }),
                     { target: { value: 'factura_a' } })
    expect(screen.queryByLabelText('Vencimiento de pago')).toBeNull()
    fireEvent.click(screen.getByText('Generar pre factura'))

    await waitFor(() => expect(post).toHaveBeenCalled())
    const cuerpo = post.mock.calls[0][1]
    expect(cuerpo).toMatchObject({ tipo: 'factura_a' })
    expect(cuerpo.fecha_vencimiento_pago).toBeUndefined()
  })

  // ── Editar una pre factura ───────────────────────────────────────────────
  //
  // La misma pantalla sobre una pre factura que ya existe (`/pre-facturas/:id/editar`): el cliente es el de
  // la pre factura y no se cambia, sus órdenes ya están elegidas, y a las libres del cliente se suman las
  // que ya tiene reservadas.

  function preFactura(extra: Record<string, unknown> = {}) {
    return {
      id: 7, numero_interno: 'PF-0007', estado: 'pendiente', cliente_id: 1, cliente_razon: 'Agro Norte',
      cliente_cuit: '', tipo_comprobante: 6,
      fecha_sugerida: '2026-08-20', fecha_vencimiento_pago: null, observaciones: '', items: [],
      orden_ids: [1], total: '1210.00', ...extra,
    }
  }

  async function editar(pf: Record<string, unknown>, libres: unknown[], propias: unknown[]) {
    responder(libres, propias)
    get.mockImplementation(((previa) => (ruta?: string) => (
      ruta === '/api/pre-facturas/7' ? Promise.resolve(pf) : previa(ruta)
    ))(get.getMockImplementation()!))
    render(
      <MemoryRouter initialEntries={['/pre-facturas/7/editar']}>
        <Routes>
          <Route path="/pre-facturas/:id/editar" element={<EditarPreFactura />} />
          <Route path="/pre-facturas/:id" element={<p>Pantalla de la pre factura</p>} />
        </Routes>
      </MemoryRouter>)
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
  }

  it('al editar carga la pre factura: cliente fijo, datos puestos y sus órdenes elegidas', async () => {
    await editar(preFactura(), [orden(2, { total: '500.00' })], [orden(1, { total: '1210.00' })])

    expect(screen.getByRole('heading', { name: 'Editar pre factura PF-0007' })).toBeInTheDocument()
    expect(screen.getByLabelText('Cliente')).toBeDisabled()
    expect((screen.getByLabelText('Tipo', { selector: '#n-tipo' }) as HTMLSelectElement).value).toBe('factura_b')
    expect(screen.getByLabelText('Fecha', { selector: '#n-fecha' })).toHaveValue('2026-08-20')
    // Las suyas, ya elegidas; las libres, para sumar.
    expect(casilla(1)).toBeChecked()
    expect(casilla(2)).not.toBeChecked()
    expect(screen.getByText('Total: $ 1.210,00')).toBeInTheDocument()
  })

  it('al guardar manda los cambios con PUT y vuelve a la pre factura', async () => {
    put.mockResolvedValue(preFactura())
    await editar(preFactura(), [orden(2, { total: '500.00' })], [orden(1)])

    fireEvent.click(casilla(2))
    fireEvent.click(screen.getByText('Guardar cambios'))

    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][0]).toBe('/api/pre-facturas/7')
    expect(put.mock.calls[0][1]).toMatchObject({
      tipo: 'factura_b', fecha: '2026-08-20',
    })
    // El orden lo da la lista (la más nueva primero) y al servidor no le importa.
    expect([...put.mock.calls[0][1].orden_ids].sort()).toEqual([1, 2])
    expect(post).not.toHaveBeenCalled()
    expect(await screen.findByText('Pantalla de la pre factura')).toBeInTheDocument()
  })

  it('una pre factura enviada o aceptada avisa que al guardar vuelve a pendiente', async () => {
    await editar(preFactura({ estado: 'aceptado' }), [], [orden(1)])
    expect(screen.getByRole('status')).toHaveTextContent('vuelve a Pendiente')
  })

  it('una pre factura facturada o anulada no se edita', async () => {
    await editar(preFactura({ estado: 'facturado' }), [], [orden(1)])
    expect(screen.getByRole('alert')).toHaveTextContent('PF-0007 está facturada: no se edita.')
    expect(screen.getByText('Guardar cambios')).toBeDisabled()
  })

  describe('el aviso de FCE', () => {
    /** Las respuestas de siempre, más la del aviso. Anota con qué se preguntó. */
    function conAviso(aviso: unknown, ordenes: unknown[] = [orden(1, { total: '5000000.00' })]) {
      const preguntas: string[] = []
      get.mockImplementation((ruta?: string) => {
        if (!ruta) return Promise.resolve([])
        if (ruta.startsWith('/api/comprobantes/fce/corresponde')) {
          preguntas.push(ruta)
          return Promise.resolve(aviso)
        }
        if (ruta.startsWith('/api/ordenes')) return Promise.resolve(ordenes)
        if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
            return Promise.resolve([])
      })
      return preguntas
    }

    it('avisa antes de emitir, con lo que se está por facturar, y ofrece pasar a FCE', async () => {
      const preguntas = conAviso({ disponible: true, corresponde: true, obligado: true,
                                   monto_desde: '3958316', fce_habilitada: true })
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))

      const aviso = await screen.findByRole('status', { name: 'Aviso de FCE' }, { timeout: 2000 })
      expect(aviso).toHaveTextContent('le corresponde ser una factura de crédito electrónica')
      const pregunta = new URLSearchParams(preguntas.at(-1)!.split('?')[1])
      expect(Object.fromEntries(pregunta)).toMatchObject(
        { cliente_id: '1', total: '5000000.00' })
      expect(pregunta.has('razon_social_id')).toBe(false)

      fireEvent.click(screen.getByText('Pasar a factura de crédito electrónica'))
      expect((screen.getByLabelText('Tipo') as HTMLSelectElement).value).toBe('fce_a')
      // Ya es FCE: el aviso se va, y aparece el vencimiento de pago propuesto.
      expect(screen.queryByRole('status', { name: 'Aviso de FCE' })).toBeNull()
      expect(screen.getByLabelText('Vencimiento de pago')).toBeInTheDocument()
    })

    it('si la empresa no puede emitir FCE, dice qué cargar', async () => {
      conAviso({ disponible: true, corresponde: true, monto_desde: '3958316', fce_habilitada: false })
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))

      const aviso = await screen.findByRole('status', { name: 'Aviso de FCE' }, { timeout: 2000 })
      expect(aviso).toHaveTextContent('cargá el CBU y la modalidad')
      expect(screen.queryByText('Pasar a factura de crédito electrónica')).toBeNull()
    })

    it.each([
      ['no corresponde', { disponible: true, corresponde: false, fce_habilitada: true }],
      ['no se pudo preguntar', { disponible: false, motivo: 'ARCA no contestó', fce_habilitada: false }],
    ])('si %s, no muestra nada y no frena', async (_caso, respuesta) => {
      const preguntas = conAviso(respuesta)
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))
      await waitFor(() => expect(preguntas.length).toBeGreaterThan(0), { timeout: 2000 })
      expect(screen.queryByRole('status', { name: 'Aviso de FCE' })).toBeNull()
      expect(screen.getByText('Generar pre factura')).toBeEnabled()
    })
  })
})
