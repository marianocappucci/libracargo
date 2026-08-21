import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { default: CuentaCorriente } = await import('./CuentaCorriente')

const TERCEROS = [
  { id: 1, razon_social: 'Agro Norte', es_cliente: true, es_fletero: false, es_proveedor: false },
  { id: 2, razon_social: 'Fletes SRL', es_cliente: false, es_fletero: true, es_proveedor: false },
  // Proveedor PURO. Es el caso real: los 15 de la instancia del cliente no son
  // ademas cliente ni fletero, asi que si la lista no los contempla, NINGUNO se
  // puede elegir.
  { id: 3, razon_social: 'Gomeria Del Centro', es_cliente: false, es_fletero: false,
    es_proveedor: true },
]

/** Escribe la ruta actual en el DOM, para poder asertar sobre la navegacion
 *  sin mockear `useNavigate` -- lo que probaria que se llamo a una funcion, no
 *  que se llego a algun lado. */
function Donde() {
  const { pathname, search } = useLocation()
  return <span data-testid="donde">{pathname + search}</span>
}

function responder(cuenta: unknown) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/cuentas')) return Promise.resolve(cuenta)
    return Promise.resolve([])
  })
}

/** La cuenta no se pide hasta que hay tercero elegido: la cuenta es el PAR
 *  (tercero, rol), no el tercero solo. */
async function elegirTercero() {
  const select = await screen.findByLabelText('Tercero')
  await waitFor(() => expect(select.querySelectorAll('option').length).toBe(2))
  fireEvent.change(select, { target: { value: '1' } })
}

describe('CuentaCorriente', () => {
  beforeEach(() => get.mockReset())

  it('🔴 avisa cuando los dos caminos NO coinciden', async () => {
    // Es la razon de que el endpoint devuelva los dos numeros. Si la pantalla
    // mostrara solo uno, un saldo divergente se veria igual de confiable que
    // uno sano, y esa es justo la situacion en la que NO hay que usarlo.
    responder({
      tercero_id: 1, rol: 'cliente', saldo: '100.00',
      saldo_recorriendo: '90.00', coinciden: false, movimientos: [],
    })
    render(<MemoryRouter><CuentaCorriente /></MemoryRouter>)
    await elegirTercero()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toContain('NO coinciden')
    // Los dos numeros a la vista, no solo el de la base.
    expect(screen.getByText('$ 100,00')).toBeInTheDocument()
    expect(screen.getByText('$ 90,00')).toBeInTheDocument()
  })

  it('con los dos saldos iguales no aparece ninguna alarma', async () => {
    // El control del test de arriba: sin este, una pantalla que gritara SIEMPRE
    // pasaria igual y la alarma dejaria de significar algo.
    responder({
      tercero_id: 1, rol: 'cliente', saldo: '100.00',
      saldo_recorriendo: '100.00', coinciden: true, movimientos: [],
    })
    render(<MemoryRouter><CuentaCorriente /></MemoryRouter>)
    await elegirTercero()
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('🔴 con el rol Proveedor elegido, la lista es de PROVEEDORES', async () => {
    // Decia `rol === 'fletero' ? fleteros : clientes`, asi que "Proveedor"
    // mostraba la lista de CLIENTES. Con los 15 proveedores reales -- que son
    // proveedor-puro -- eso dejaba su cuenta corriente inalcanzable, y sus
    // 3.347 movimientos migrados sin forma de abrirse.
    responder({
      tercero_id: 3, rol: 'proveedor', saldo: '0.00',
      saldo_recorriendo: '0.00', coinciden: true, movimientos: [],
    })
    render(<MemoryRouter><CuentaCorriente /></MemoryRouter>)

    const cuenta = await screen.findByLabelText('Cuenta')
    fireEvent.change(cuenta, { target: { value: 'proveedor' } })

    const tercero = await screen.findByLabelText('Tercero')
    await waitFor(() => {
      const nombres = [...tercero.querySelectorAll('option')].map((o) => o.textContent)
      expect(nombres).toContain('Gomeria Del Centro')
      // Y el control: la lista NO es la de clientes.
      expect(nombres).not.toContain('Agro Norte')
    })
  })

  it('cada rol ofrece su propia lista, no la del rol de al lado', async () => {
    responder({
      tercero_id: 1, rol: 'cliente', saldo: '0.00',
      saldo_recorriendo: '0.00', coinciden: true, movimientos: [],
    })
    render(<MemoryRouter><CuentaCorriente /></MemoryRouter>)
    const cuenta = await screen.findByLabelText('Cuenta')
    const tercero = await screen.findByLabelText('Tercero')

    const nombresPara = async (rol: string) => {
      fireEvent.change(cuenta, { target: { value: rol } })
      await waitFor(() => expect(tercero.querySelectorAll('option').length).toBe(2))
      return [...tercero.querySelectorAll('option')].map((o) => o.textContent)
    }

    expect(await nombresPara('cliente')).toContain('Agro Norte')
    expect(await nombresPara('fletero')).toContain('Fletes SRL')
    expect(await nombresPara('proveedor')).toContain('Gomeria Del Centro')
  })

  it('🔴 clickear una fila lleva al documento que la explica', async () => {
    // Es el pedido textual: "que me mande a la orden de carga o a la factura".
    // Antes de esto la pantalla tenia cero forma de llegar: el asiento mostraba
    // el importe y el concepto, y el documento quedaba a mano de nadie.
    responder({
      tercero_id: 1, rol: 'cliente', saldo: '100.00', saldo_recorriendo: '100.00',
      coinciden: true,
      movimientos: [{
        movimiento: {
          id: 1, fecha: '2026-08-20', tercero_id: 1, rol: 'cliente',
          concepto: 'Factura A 0001-00000009', descripcion: null,
          debe: '100.00', haber: '0.00',
          orden_id: 7, comprobante_id: 9, movimiento_caja_id: null,
        },
        saldo: '100.00',
      }],
    })

    render(
      <MemoryRouter>
        <Donde />
        <CuentaCorriente />
      </MemoryRouter>,
    )
    await elegirTercero()
    await waitFor(() => expect(screen.getByText('Factura A 0001-00000009')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Factura A 0001-00000009'))

    // Al comprobante y NO a la orden: el asiento apunta a los dos y gana el
    // documento que explica el importe de la linea.
    await waitFor(() => {
      expect(screen.getByTestId('donde').textContent).toBe('/comprobantes?ver=9')
    })
  })
})
