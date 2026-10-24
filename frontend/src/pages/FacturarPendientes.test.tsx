/** Los tests de «Facturar pendientes», que desde ADR-048 **emite directo por ARCA** (antes, ADR-032, generaba una pre factura).
 *
 * Nacieron como cuatro adentro de `Comprobantes.test.tsx` y probaban el `<Dialog>`; se mudaron a la pantalla.
 * La lógica que cubren —qué órdenes se ofrecen, cómo suma la vista previa, qué viaja en el POST— sigue. Lo que cambió es
 * que acá sale el CAE: no hay pre factura que revisar después, así que el botón pide una confirmación, y no hay punto
 * de venta ni número (los pone ARCA). El comprobante emitido se abre en Comprobantes.
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

const { default: FacturarPendientes } = await import('./FacturarPendientes')

const TERCEROS = [{ id: 1, razon_social: 'Agro Norte', es_cliente: true }]

function responder(ordenes: unknown[] = []) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
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
        <Route path="/comprobantes" element={<p>Pantalla de los comprobantes</p>} />
        <Route path="/comprobantes/nueva" element={<p>Pantalla de la nueva factura</p>} />
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

/** Facturar: el primer click pide confirmar (emitir por ARCA no se deshace) y el segundo emite. */
async function emitir() {
  fireEvent.click(screen.getByText('Facturar'))
  fireEvent.click(await screen.findByText('Confirmar y emitir'))
}

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

  it('emite directo por ARCA las órdenes elegidas y abre el comprobante', async () => {
    responder([orden(1)])
    post.mockResolvedValue({ id: 9 })
    await abrir()

    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    await emitir()

    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/api/comprobantes/desde-ordenes')
    expect(post.mock.calls[0][1]).toMatchObject({
      cliente_id: 1, tipo: 'factura_a', orden_ids: [1],
    })
    expect(post.mock.calls[0][1]).not.toHaveProperty('razon_social_id')
    // 🔴 Se sacó el registro a mano: ni el punto de venta ni el número viajan, ni se ofrecen. Tampoco importes ni ítems.
    for (const campo of ['punto_venta', 'numero', 'items', 'neto', 'iva', 'total']) {
      expect(post.mock.calls[0][1], campo).not.toHaveProperty(campo)
    }
    expect(await screen.findByText('Pantalla de los comprobantes')).toBeInTheDocument()
  })

  it('🔑 el primer click no emite: pide confirmar, y cambiar algo desarma la confirmación', async () => {
    responder([orden(1, { total: '100.00' }), orden(2, { total: '50.00' })])
    post.mockResolvedValue({ id: 9 })
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))

    fireEvent.click(screen.getByText('Facturar'))
    expect(post).not.toHaveBeenCalled()
    expect(screen.getByText('Se emite por ARCA ahora y no se deshace.')).toBeInTheDocument()

    // «No» vuelve atrás sin emitir.
    fireEvent.click(screen.getByText('No'))
    expect(screen.queryByText('Confirmar y emitir')).toBeNull()
    expect(post).not.toHaveBeenCalled()

    // Y cambiar lo que se va a emitir también: no se confirma una cosa y se emite otra.
    fireEvent.click(screen.getByText('Facturar'))
    expect(screen.getByText('Confirmar y emitir')).toBeInTheDocument()
    fireEvent.click(casilla(2))
    expect(screen.queryByText('Confirmar y emitir')).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })

  it('contra homologación avisa que fue un ensayo, no guarda nada y se queda', async () => {
    responder([orden(1)])
    post.mockResolvedValue({
      ensayo: true, ambiente: 'homologacion', tipo: 'factura_a', punto_venta: 5, numero: 42, total: '1210.00',
      cae: '75123456789012', cae_vencimiento: '2026-12-31',
    })
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    await emitir()

    expect(await screen.findByRole('status')).toHaveTextContent('Ensayo contra homologacion')
    expect(screen.getByRole('status')).toHaveTextContent('no se guardó nada')
    expect(screen.queryByText('Pantalla de los comprobantes')).toBeNull()
    expect(screen.getByText('Facturar')).toBeEnabled()
  })

  it('tiene el acceso a «Nueva factura», para lo que no sale de órdenes', async () => {
    responder([orden(1)])
    await abrir()
    fireEvent.click(screen.getByRole('link', { name: 'Nueva factura' }))
    expect(await screen.findByText('Pantalla de la nueva factura')).toBeInTheDocument()
  })

  it('no pide punto de venta ni número', async () => {
    // El control de lo de arriba: que el POST no los mande no alcanza si el formulario los sigue pidiendo.
    responder([orden(1)])
    await abrir()
    expect(screen.queryByLabelText('Punto de venta')).toBeNull()
    expect(screen.queryByLabelText('Número')).toBeNull()
    expect(screen.queryByText('Generar pre factura')).toBeNull()
  })

  it('pide las pendientes del cliente, sin filtros de reserva (la pre factura ya no existe)', async () => {
    responder([orden(1)])
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    const pedidas = get.mock.calls.map((c) => String(c[0])).filter((r) => r.startsWith('/api/ordenes'))
    expect(pedidas.length).toBeGreaterThan(0)
    for (const pedida of pedidas) {
      expect(pedida).toContain('cliente_id=1')
      expect(pedida).toContain('estado=pendiente')
      expect(pedida).not.toContain('reservada')
      expect(pedida).not.toContain('pre_factura_id')
    }
  })

  it('si el servidor rechaza, muestra el motivo y se queda', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    responder([orden(1)])
    post.mockRejectedValue(new ApiError(409, 'la orden 1 no esta pendiente (esta facturada)'))
    await abrir()
    await waitFor(() => expect(casilla(1)).toBeInTheDocument())
    fireEvent.click(casilla(1))
    await emitir()

    expect(await screen.findByRole('alert')).toHaveTextContent('la orden 1 no esta pendiente')
    expect(screen.queryByText('Pantalla de los comprobantes')).toBeNull()
    // Vuelve a «Facturar»: la confirmación se desarma y se puede reintentar.
    expect(screen.getByText('Facturar')).toBeEnabled()
  })

  // ── Un nodo sin conexión: la factura queda en la cola (ADR-056, libra-ui ADR-094) ───────────────
  describe('en un nodo sin conexión', () => {
    const EN_COLA = {
      codigo: 'en_cola', pedido_id: 4, estado: 'esperando', motivo: '',
      mensaje: 'Sin conexión con el central o con ARCA: la factura queda en cola y se emite sola al volver la conexión.',
    }

    it('🔴 un 202 `en_cola` NO abre un comprobante: se queda en la pantalla con el aviso «Se emite al volver la conexión.»', async () => {
      responder([orden(1), orden(2)])
      post.mockResolvedValue(EN_COLA)
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))
      await emitir()

      expect(await screen.findByText('Se emite al volver la conexión.')).toBeInTheDocument()
      // No se navegó a Comprobantes (no hay comprobante) y la confirmación se desarmó.
      expect(screen.queryByText('Pantalla de los comprobantes')).toBeNull()
      expect(screen.getByRole('heading', { name: 'Facturar pendientes' })).toBeInTheDocument()
      expect(screen.queryByText('Confirmar y emitir')).toBeNull()
      // La orden ya está en un pedido abierto: se suelta de la selección, para no pedirla dos veces.
      expect(screen.getByText('0 orden/es elegida/s')).toBeInTheDocument()
      expect(screen.getByText('Facturar')).toBeDisabled()
    })

    it('el aviso de una factura es un estado (no una alarma) y se puede cerrar', async () => {
      responder([orden(1)])
      post.mockResolvedValue(EN_COLA)
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))
      await emitir()
      const aviso = (await screen.findByText('Se emite al volver la conexión.')).closest('[data-slot="aviso-en-cola"]')!
      expect(aviso).toHaveAttribute('role', 'status')
      fireEvent.click(within(aviso as HTMLElement).getByRole('button', { name: 'Cerrar aviso' }))
      expect(screen.queryByText('Se emite al volver la conexión.')).toBeNull()
    })

    it('un 201 con el comprobante (hay conexión) sigue abriendo el comprobante, sin aviso de cola', async () => {
      responder([orden(1)])
      post.mockResolvedValue({ id: 9 })
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))
      await emitir()
      expect(await screen.findByText('Pantalla de los comprobantes')).toBeInTheDocument()
      expect(screen.queryByText('Se emite al volver la conexión.')).toBeNull()
    })

    it('🔴 el 409 `solo_en_el_nodo` (la web con un nodo vinculado) se lee con su mensaje', async () => {
      const { ApiError } = await import('libra-ui/api-client')
      const mensaje = 'Esta instancia opera desde la oficina con su nodo: facturá desde la versión de escritorio.'
      responder([orden(1)])
      post.mockRejectedValue(new ApiError(409, mensaje, { codigo: 'solo_en_el_nodo', mensaje }))
      await abrir()
      await waitFor(() => expect(casilla(1)).toBeInTheDocument())
      fireEvent.click(casilla(1))
      await emitir()
      expect(await screen.findByRole('alert')).toHaveTextContent(mensaje)
    })

    it('una orden cargada en el nodo (id negativo) se lee «P-3» y no «-3», que no es un número de orden', async () => {
      responder([orden(-3)])
      await abrir()
      const marca = await screen.findByLabelText('Elegir la orden P-3')
      expect(marca).toBeInTheDocument()
      expect(screen.getByText('P-3')).toBeInTheDocument()
      expect(screen.queryByText('-3')).toBeNull()
    })
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
    await emitir()

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
    await emitir()
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toMatchObject({ fce_cbu: '' })
  })

  it('una FCE puede cobrarse en otra cuenta, reconocida por su alias', async () => {
    await elegirFce('2026-08-15')
    await elegirEnBuscable(await screen.findByLabelText('Cobrar en'), /^agencia\.nacion · /)
    await emitir()
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
    await emitir()
    await waitFor(() => expect(post).toHaveBeenCalled())
    // `undefined` no viaja: lo que importa es el JSON que sale.
    expect(JSON.parse(JSON.stringify(post.mock.calls[0][1]))).not.toHaveProperty('fce_cbu')
  })

  it('sin vencimiento de pago una FCE no se puede facturar', async () => {
    await elegirFce()
    fireEvent.change(screen.getByLabelText('Vencimiento de pago'), { target: { value: '' } })

    expect(screen.getByText('Facturar')).toBeDisabled()
    expect(screen.getByText('Falta el vencimiento de pago.')).toBeInTheDocument()
  })

  it('si la fecha pasa del vencimiento propuesto, la FCE no se puede facturar', async () => {
    // La fecha se puede cambiar DESPUÉS de elegir FCE: el vencimiento propuesto a 30
    // días queda atrás y el backend la rechazaría con un 422.
    await elegirFce('2026-08-15')
    fireEvent.change(screen.getByLabelText('Fecha', { selector: '#n-fecha' }),
                     { target: { value: '2026-12-01' } })

    expect(screen.getByText('Facturar')).toBeDisabled()
    expect(screen.getByText('El vencimiento de pago no puede ser anterior a la fecha del comprobante.'))
      .toBeInTheDocument()
  })

  it('una factura común no manda vencimiento, y al volver a ella desaparece el campo', async () => {
    await elegirFce()
    fireEvent.change(screen.getByLabelText('Tipo', { selector: '#n-tipo' }),
                     { target: { value: 'factura_a' } })
    expect(screen.queryByLabelText('Vencimiento de pago')).toBeNull()
    await emitir()

    await waitFor(() => expect(post).toHaveBeenCalled())
    const cuerpo = post.mock.calls[0][1]
    expect(cuerpo).toMatchObject({ tipo: 'factura_a' })
    expect(cuerpo.fecha_vencimiento_pago).toBeUndefined()
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
      expect(screen.getByText('Facturar')).toBeEnabled()
    })
  })
})
