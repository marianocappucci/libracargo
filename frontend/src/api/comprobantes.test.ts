import { describe, expect, it, vi } from 'vitest'

vi.mock('libra-ui/api-client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { numeroDe, sumarImportes } = await import('./comprobantes')

describe('sumarImportes', () => {
  it('suma en centavos enteros, no en punto flotante', () => {
    // `0.1 + 0.2` en JavaScript da 0.30000000000000004. La vista previa de lo
    // que se va a facturar no puede depender de eso.
    expect(sumarImportes(['0.10', '0.20'])).toBe('0.30')
    expect(Number('0.10') + Number('0.20')).not.toBe(0.3)
  })

  it('no pierde centavos sobre importes grandes', () => {
    expect(sumarImportes(['1234567.89', '0.07', '2500.55'])).toBe('1237068.51')
  })

  it('sin nada elegido da cero, no vacio ni NaN', () => {
    // Es el estado inicial del dialogo: si diera NaN, la pantalla mostraria
    // "Total: NaN" antes de que nadie toque nada.
    expect(sumarImportes([])).toBe('0.00')
  })

  it('un importe sin decimales vale lo mismo que con ceros', () => {
    expect(sumarImportes(['100', '0.50'])).toBe('100.50')
  })

  it('resta cuando el importe viene en negativo', () => {
    expect(sumarImportes(['100.00', '-0.50'])).toBe('99.50')
    expect(sumarImportes(['-100.00', '0.50'])).toBe('-99.50')
  })
})

describe('numeroDe', () => {
  it('arma el numero como se lee en el papel', () => {
    const c = { punto_venta: 1, numero: 123 } as Parameters<typeof numeroDe>[0]
    expect(numeroDe(c)).toBe('0001-00000123')
  })
})
