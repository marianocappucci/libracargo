import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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
})
