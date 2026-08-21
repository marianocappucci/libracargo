import { fireEvent, render, screen } from '@testing-library/react'
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
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { default: Caja } = await import('./Caja')

const TERCEROS = [
  { id: 1, razon_social: 'Agro Norte', es_cliente: true, es_fletero: false, es_proveedor: false },
]

const MOVIMIENTO = {
  id: 5, fecha: '2026-08-21', tipo: 'ingreso', concepto: 'Cobro',
  descripcion: null, tercero_id: 1, importe: '100000.00',
  medio_pago: 'efectivo', recibo: '0001-555', anulado: false,
}

function responder(movimientos: unknown[]) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/caja')) return Promise.resolve(movimientos)
    return Promise.resolve([])
  })
}

describe('Caja', () => {
  beforeEach(() => { get.mockReset() })

  it('🔑 un movimiento anulado SIGUE en el listado, con su recibo', async () => {
    // `elimina_novedad.php` lo borraba, y el numero de recibo quedaba con un
    // hueco que nadie podia explicar. Se ve, marcado, y no suma en los totales.
    responder([{ ...MOVIMIENTO, anulado: true }])
    render(<MemoryRouter><Caja /></MemoryRouter>)
    expect(await screen.findByText('anulado')).toBeInTheDocument()
    expect(screen.getByText('0001-555')).toBeInTheDocument()
  })

  it('un anulado no se puede editar ni volver a anular', async () => {
    responder([{ ...MOVIMIENTO, anulado: true }])
    render(<MemoryRouter><Caja /></MemoryRouter>)
    await screen.findByText('anulado')
    expect((screen.getByLabelText('Editar') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Anular') as HTMLButtonElement).disabled).toBe(true)
  })

  it('uno vigente si se puede editar, y el formulario abre con sus valores', async () => {
    // El control del test de arriba: sin este, unos botones siempre
    // deshabilitados pasarian igual.
    responder([MOVIMIENTO])
    render(<MemoryRouter><Caja /></MemoryRouter>)
    await screen.findByText('vigente')
    const editar = screen.getByLabelText('Editar') as HTMLButtonElement
    expect(editar.disabled).toBe(false)

    fireEvent.click(editar)
    expect(await screen.findByText(/Editar movimiento 5/)).toBeInTheDocument()
    expect((screen.getByLabelText('Importe') as HTMLInputElement).value).toBe('100000.00')
  })

  it('🔴 la tabla no pide mas ancho del que entra en un portatil', async () => {
    // El scroll horizontal que reporto el humano. La causa no es CSS suelto:
    // el `DataTable` pasa a `table-fixed` en cuanto ALGUNA columna declara
    // `size`, y le pone a la tabla un `minWidth` **inline** igual a la suma de
    // los anchos. Las que no declaran ninguno caen al default de TanStack (150),
    // asi que con siete sin declarar el minimo era 1.240 px.
    //
    // Se mide el estilo inline y no el layout: jsdom no calcula anchos, pero el
    // `minWidth` que causa el desborde SI esta en el DOM, y es exactamente la
    // magnitud que hay que controlar.
    responder([MOVIMIENTO])
    render(<MemoryRouter><Caja /></MemoryRouter>)
    await screen.findByText('vigente')

    const tabla = document.querySelector('table')!
    expect(tabla.className).toContain('table-fixed')
    const minimo = Number.parseInt(tabla.style.minWidth, 10)
    expect(minimo).toBe(1060)
    // 1280 es el ancho de un portatil comun, y la pantalla ademas tiene la
    // barra lateral. Si alguien agrega una columna sin `size`, esto se va a
    // 1.210 y el test lo dice antes de que lo diga el usuario.
    expect(minimo).toBeLessThan(1100)
  })
})
