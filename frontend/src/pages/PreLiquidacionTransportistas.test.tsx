import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', () => ({
  ApiError: class extends Error {},
  api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { default: PreLiquidacionTransportistas } = await import('./PreLiquidacionTransportistas')
const { default: ReportesIndice } = await import('./ReportesIndice')

const RUTA = '/api/reportes/pre-liquidacion-transportistas'

// Datos ficticios, con los importes calculados a mano (ver tests/test_pre_liquidacion.py).
const DATOS = {
  desde: '2026-07-01', hasta: '2026-07-31', fletero_id: null,
  transportistas: [
    {
      tercero_id: 2, transportista: 'Juan Pérez', cuit: '20-12345678-6',
      condicion_iva: 'monotributo', condicion_iva_texto: 'Monotributista',
      discrimina_iva: false, aviso: null, cantidad_fletes: 1,
      neto: '500.00', iva: '0.00', total: '500.00',
      fletes: [{
        orden_id: 7, fecha: '2026-07-10', remito: 'R-0007', cliente: 'Molino Sur',
        origen: 'Suipacha', destino: 'Rosario', cantidad: '10.000', unidad: 'tn',
        cantidad_legado: null, alicuota_iva: '21.00',
        neto: '500.00', iva: '0.00', total: '500.00',
      }],
    },
    {
      tercero_id: 3, transportista: 'Transportes del Oeste', cuit: '30-12345678-1',
      condicion_iva: 'responsable_inscripto', condicion_iva_texto: 'Responsable inscripto',
      discrimina_iva: true, aviso: null, cantidad_fletes: 2,
      neto: '1333.33', iva: '280.00', total: '1613.33',
      fletes: [
        {
          orden_id: 1, fecha: '2026-07-01', remito: 'R-0001', cliente: 'Agro Norte',
          origen: 'Suipacha', destino: 'Rosario', cantidad: '12.500', unidad: 'tn',
          cantidad_legado: null, alicuota_iva: '21.00',
          neto: '1000.00', iva: '210.00', total: '1210.00',
        },
        {
          orden_id: 6, fecha: '2026-07-31', remito: null, cliente: 'Agro Norte',
          origen: 'Rosario', destino: 'Suipacha', cantidad: null, unidad: null,
          cantidad_legado: '3 camiones', alicuota_iva: '21.00',
          neto: '333.33', iva: '70.00', total: '403.33',
        },
      ],
    },
    {
      tercero_id: 4, transportista: 'Sin Categoría SA', cuit: null,
      condicion_iva: 'no_categorizado', condicion_iva_texto: 'Sin categorizar',
      discrimina_iva: false, cantidad_fletes: 1,
      aviso: 'No tiene condición de IVA cargada: se liquida sin IVA.',
      neto: '100.00', iva: '0.00', total: '100.00',
      fletes: [{
        orden_id: 9, fecha: '2026-07-02', remito: null, cliente: 'Agro Norte',
        origen: 'Suipacha', destino: 'Rosario', cantidad: null, unidad: null,
        cantidad_legado: null, alicuota_iva: '21.00',
        neto: '100.00', iva: '0.00', total: '100.00',
      }],
    },
  ],
  fletes: 4, neto: '1933.33', iva: '280.00', total: '2213.33',
}

const TERCEROS = [
  { id: 2, razon_social: 'Juan Pérez', es_fletero: true },
  { id: 3, razon_social: 'Transportes del Oeste', es_fletero: true },
]

function responder(datos: unknown = DATOS) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith(RUTA)) return Promise.resolve(datos)
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    return Promise.resolve([])
  })
}

const pedidos = () => get.mock.calls.map((l) => String(l[0] ?? '')).filter((r) => r.startsWith(RUTA))

/** Abre la pantalla y espera a que carguen las opciones del select: si no, el `setState` de la
 *  carga llega después del test y React avisa que no estaba envuelto en `act`. */
async function abrir() {
  const vista = render(
    <MemoryRouter initialEntries={['/reportes/pre-liquidacion-transportistas']}>
      <Routes>
        <Route path="/reportes/pre-liquidacion-transportistas"
               element={<PreLiquidacionTransportistas />} />
      </Routes>
    </MemoryRouter>,
  )
  await waitFor(() =>
    expect(screen.getByLabelText('Transportista').querySelectorAll('option').length).toBe(3))
  return vista
}

async function ponerElRango() {
  fireEvent.change(await screen.findByLabelText('Desde'), { target: { value: '2026-07-01' } })
  // `act` asíncrono: el pedido se resuelve en la misma vuelta que el cambio.
  await act(async () => {
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-07-31' } })
  })
}

describe('Pre liquidación de transportistas', () => {
  beforeEach(() => { get.mockReset(); responder() })

  it('🔑 pide el rango: sin desde y hasta no corre y no hay botones de salida', async () => {
    await abrir()
    await waitFor(() => expect(screen.getByLabelText('Desde')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Pre liquidación de transportistas' }))
      .toBeInTheDocument()
    expect(screen.getByLabelText('Hasta')).toBeInTheDocument()
    expect(screen.getByLabelText('Transportista')).toBeInTheDocument()
    expect(screen.getByText(/Elegí un/)).toBeInTheDocument()
    expect(screen.queryByText('Imprimir')).toBeNull()
    expect(screen.queryByText('Ver PDF')).toBeNull()
    // Y no se pidió el reporte: la guarda no es cosmética.
    expect(pedidos()).toEqual([])
  })

  it('con una sola fecha tampoco corre', async () => {
    await abrir()
    fireEvent.change(await screen.findByLabelText('Desde'), { target: { value: '2026-07-01' } })
    await waitFor(() => expect(screen.getByText(/Elegí un/)).toBeInTheDocument())
    expect(pedidos()).toEqual([])
  })

  it('con el rango pide el reporte y muestra un bloque por transportista con sus subtotales', async () => {
    await abrir()
    await ponerElRango()

    await waitFor(() => expect(screen.getByLabelText('Juan Pérez')).toBeInTheDocument())
    expect(pedidos().some((r) => r.includes('desde=2026-07-01') && r.includes('hasta=2026-07-31')))
      .toBe(true)

    const oeste = screen.getByLabelText('Transportes del Oeste')
    // Los datos del transportista: CUIT, condición y si suma IVA.
    expect(within(oeste).getByText(/CUIT 30-12345678-1 · Responsable inscripto \(suma IVA\)/))
      .toBeInTheDocument()
    const monotributo = screen.getByLabelText('Juan Pérez')
    expect(within(monotributo).getByText(/Monotributista \(sin IVA\)/)).toBeInTheDocument()

    // El flete: fecha, remito, cliente, tramo, cantidad y los tres importes.
    const fila = within(oeste).getByText('R-0001').closest('tr') as HTMLElement
    for (const texto of ['01-07-2026', 'Agro Norte', 'Suipacha → Rosario', '12,5 tn',
                         '$ 1.000,00', '$ 210,00', '$ 1.210,00']) {
      expect(within(fila).getByText(texto)).toBeInTheDocument()
    }
    // La cantidad del legado que no parseaba sale como estaba.
    expect(within(oeste).getByText('3 camiones')).toBeInTheDocument()

    // El subtotal de cada bloque.
    const subtotal = within(oeste).getByText(/Subtotal · 2 fletes/).closest('tr') as HTMLElement
    for (const texto of ['$ 1.333,33', '$ 280,00', '$ 1.613,33']) {
      expect(within(subtotal).getByText(texto)).toBeInTheDocument()
    }
    expect(within(monotributo).getByText(/Subtotal · 1 flete$/)).toBeInTheDocument()
  })

  it('muestra el total general al final y el aviso del transportista sin categorizar', async () => {
    await abrir()
    await ponerElRango()
    const total = await screen.findByLabelText('Total general')
    expect(within(total).getByText('Total general · 4 fletes')).toBeInTheDocument()
    expect(within(total).getByText('$ 1.933,33')).toBeInTheDocument()
    expect(within(total).getByText('$ 280,00')).toBeInTheDocument()
    expect(within(total).getByText('$ 2.213,33')).toBeInTheDocument()

    const sinCategoria = screen.getByLabelText('Sin Categoría SA')
    expect(within(sinCategoria).getByRole('note')).toHaveTextContent('se liquida sin IVA')
    // Los que tienen condición real no llevan aviso.
    expect(within(screen.getByLabelText('Juan Pérez')).queryByRole('note')).toBeNull()
  })

  it('ofrece imprimir y el PDF, con el mismo rango y transportista que lo que se ve', async () => {
    await abrir()
    await ponerElRango()
    await screen.findByLabelText('Juan Pérez')
    expect(screen.getByText('Imprimir')).toBeInTheDocument()

    const ver = screen.getByText('Ver PDF').closest('a') as HTMLAnchorElement
    expect(ver.getAttribute('href')).toBe(`${RUTA}/pdf?desde=2026-07-01&hasta=2026-07-31`)
    expect(ver.getAttribute('target')).toBe('_blank')
    const bajar = screen.getByText('Descargar PDF').closest('a') as HTMLAnchorElement
    expect(bajar.getAttribute('href')).toBe(ver.getAttribute('href'))
    expect(bajar.getAttribute('download')).toBe(
      'pre-liquidacion-transportistas-2026-07-01-2026-07-31.pdf')
  })

  it('elegir un transportista vuelve a pedir el reporte con fletero_id y lo lleva al PDF', async () => {
    await abrir()
    await ponerElRango()
    await screen.findByLabelText('Juan Pérez')
    const select = screen.getByLabelText('Transportista')
    await waitFor(() => expect(select.querySelectorAll('option').length).toBe(3))

    get.mockClear()
    await act(async () => { fireEvent.change(select, { target: { value: '2' } }) })
    await waitFor(() => expect(pedidos().some((r) => r.includes('fletero_id=2'))).toBe(true))
    await waitFor(() =>
      expect((screen.getByText('Ver PDF').closest('a') as HTMLAnchorElement).getAttribute('href'))
        .toContain('fletero_id=2'))
  })

  it('imprimir arma la hoja con el título, la leyenda y los totales, y llama a window.print', async () => {
    // Lo que importa es lo que hay en el DOM **en el momento de imprimir**: el navegador fotografía eso.
    let hoja = ''
    const imprimir = vi.spyOn(window, 'print').mockImplementation(() => {
      hoja = document.getElementById('hoja-impresa')?.textContent ?? ''
    })
    await abrir()
    await ponerElRango()
    await screen.findByLabelText('Juan Pérez')
    fireEvent.click(screen.getByText('Imprimir'))

    await waitFor(() => expect(imprimir).toHaveBeenCalled())
    imprimir.mockRestore()
    expect(hoja).toContain('Pre liquidación de transportistas')
    expect(hoja).toContain('Pre liquidación — no es un comprobante')
    expect(hoja).toContain('Período: 01-07-2026 al 31-07-2026')
    expect(hoja).toContain('Transportes del Oeste')
    expect(hoja).toContain('Subtotal · 2 fletes')
    expect(hoja).toContain('Total a liquidar: $ 2.213,33')
    // Y la hoja se saca del DOM después de imprimir.
    await waitFor(() => expect(document.getElementById('hoja-impresa')).toBeNull())
  })

  it('un rango sin fletes lo dice, y sin botones de salida', async () => {
    responder({ ...DATOS, transportistas: [], fletes: 0, neto: '0.00', iva: '0.00', total: '0.00' })
    await abrir()
    await ponerElRango()
    await waitFor(() =>
      expect(screen.getByText(/No hay fletes con comisión en ese período/)).toBeInTheDocument())
    expect(screen.queryByText('Imprimir')).toBeNull()
    expect(screen.queryByText('Ver PDF')).toBeNull()
  })

  it('un rango al revés avisa y no pide nada', async () => {
    await abrir()
    fireEvent.change(await screen.findByLabelText('Desde'), { target: { value: '2026-07-31' } })
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-07-01' } })
    await waitFor(() => expect(screen.getByText(/El rango está al revés/)).toBeInTheDocument())
    expect(pedidos()).toEqual([])
  })

  it('si el servidor rechaza, muestra el error', async () => {
    get.mockImplementation((ruta?: string) => {
      if (ruta?.startsWith(RUTA)) return Promise.reject(new Error('se cayó'))
      return Promise.resolve(ruta?.startsWith('/api/terceros') ? TERCEROS : [])
    })
    await abrir()
    await ponerElRango()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})

describe('el índice de reportes', () => {
  beforeEach(() => get.mockReset())

  it('ofrece la pre liquidación entre los listados, con su ruta propia', async () => {
    get.mockImplementation((ruta?: string) => Promise.resolve(
      ruta === '/api/reportes' ? [{
        slug: 'pre-liquidacion-transportistas', titulo: 'Pre liquidación de transportistas',
        descripcion: 'Los fletes que hizo cada transportista.',
        parametros: ['rango', 'fletero'], detalle: true, solo_admin: false,
      }] : []))
    render(<MemoryRouter><ReportesIndice /></MemoryRouter>)
    const tarjeta = await screen.findByText('Pre liquidación de transportistas')
    expect(tarjeta.closest('a')?.getAttribute('href'))
      .toBe('/reportes/pre-liquidacion-transportistas')
    expect(screen.getByText('Listados para imprimir')).toBeInTheDocument()
    expect(screen.getByText(/Se filtra por: fechas, fletero\/transporte/)).toBeInTheDocument()
  })
})
