import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
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
  return { ApiError, api: { get, post, put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { default: Gastos } = await import('./Gastos')

const TERCEROS = [
  { id: 1, razon_social: 'Gomería Del Centro', es_cliente: false, es_fletero: false,
    es_proveedor: true },
  { id: 2, razon_social: 'Fletes SRL', es_cliente: false, es_fletero: true,
    es_proveedor: false },
]

const GASTO = {
  id: 7, fecha: '2026-08-21', proveedor_id: 1, fletero_id: 2,
  comprobante: '0001-00000123', descripcion: '2 cubiertas', importe: '150000.00',
  anulado: false,
}

function Donde() {
  const { pathname, search } = useLocation()
  return <span data-testid="donde">{pathname + search}</span>
}

function responder(gastos: unknown[]) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/gastos')) return Promise.resolve(gastos)
    return Promise.resolve([])
  })
}

describe('Gastos de proveedor', () => {
  beforeEach(() => { get.mockReset(); post.mockReset() })

  it('muestra a quien se le descuenta, y no solo el proveedor', async () => {
    // Es la columna que explica el documento: sin ella la pantalla parece un
    // listado de compras y no un descuento al fletero.
    responder([GASTO])
    render(<MemoryRouter><Gastos /></MemoryRouter>)
    await screen.findByText('2 cubiertas')
    // `getAllByText`: los dos nombres estan tambien en los desplegables de
    // filtro, asi que `getByText` encuentra mas de uno y falla por eso y no
    // porque la columna no este.
    expect(screen.getAllByText('Gomería Del Centro').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Fletes SRL').length).toBeGreaterThan(0)
    expect(screen.getByText('Se le descuenta a')).toBeInTheDocument()
  })

  it('🔑 el alta avisa que mueve DOS cuentas antes de guardar', async () => {
    // En el sistema viejo el alta tocaba dos cuentas y nada en pantalla lo
    // decia. Es la clase de efecto que se descubre al mirar un saldo raro.
    responder([])
    render(<MemoryRouter><Gastos /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Nuevo gasto'))
    // Se busca el PARRAFO y no el `<strong>`: `findByText(/suma/)` matchea el
    // nodo mas chico que contiene el texto, que es la palabra suelta.
    const aviso = await screen.findByText(/Al guardar, este gasto/)
    expect(aviso.textContent).toContain('suma')
    expect(aviso.textContent).toContain('descuenta')
  })

  it('no deja guardar sin proveedor, fletero, detalle e importe', async () => {
    responder([])
    render(<MemoryRouter><Gastos /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Nuevo gasto'))
    const guardar = await screen.findByText('Guardar')
    expect((guardar as HTMLButtonElement).disabled).toBe(true)
  })

  it('clickear una fila lleva a la cuenta del proveedor', async () => {
    responder([GASTO])
    render(<MemoryRouter><Donde /><Gastos /></MemoryRouter>)
    fireEvent.click(await screen.findByText('2 cubiertas'))
    await waitFor(() => {
      expect(screen.getByTestId('donde').textContent).toBe('/cuentas?rol=proveedor&tercero=1')
    })
  })

  it('un gasto anulado no se puede editar ni volver a anular', async () => {
    responder([{ ...GASTO, anulado: true }])
    render(<MemoryRouter><Gastos /></MemoryRouter>)
    await screen.findByText('anulado')
    expect((screen.getByLabelText('Editar') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Anular') as HTMLButtonElement).disabled).toBe(true)
  })
})
