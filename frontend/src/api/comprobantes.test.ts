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

describe('previsualizarFactura (la vista previa de «Nueva factura»)', () => {
  const concepto = (extra: Record<string, string> = {}) => ({
    descripcion: 'Flete', cantidad: '1', precio_unitario: '1000.00', alicuota_iva: '21', ...extra,
  })

  it('el IVA se calcula una vez sobre el neto, como en el servidor', async () => {
    const { previsualizarFactura } = await import('./comprobantes')
    // 3 × 33.33 = 99.99 y 2 × 10.01 = 20.02: neto 120.01 e IVA 25.2021 → 25.20 (no la suma de IVA redondeados).
    const v = previsualizarFactura([concepto({ cantidad: '3', precio_unitario: '33.33' }),
      concepto({ cantidad: '2', precio_unitario: '10.01' })], false)
    expect(v).toMatchObject({ neto: '120.01', iva: '25.20', total: '145.21', alicuotas: ['21'] })
  })

  it('la mitad se redondea hacia arriba, no al par', async () => {
    const { previsualizarFactura } = await import('./comprobantes')
    // 1.5 × 0.01 = 0.015 → 0.02 (Python redondearía bien con ROUND_HALF_UP; JS con toFixed daría 0.01 o 0.02 según el float).
    expect(previsualizarFactura([concepto({ cantidad: '1.5', precio_unitario: '0.01' }),
      concepto({ precio_unitario: '100.00', alicuota_iva: '0' })], false).neto).toBe('100.02')
  })

  it.each([['0', '0.00'], ['10.5', '105.00'], ['21', '210.00'], ['27', '270.00']])(
    'la alícuota %s%% sobre 1000.00 da %s', async (alicuota, iva) => {
      const { previsualizarFactura } = await import('./comprobantes')
      expect(previsualizarFactura([concepto({ alicuota_iva: alicuota })], false).iva).toBe(iva)
    })

  it('una clase C no discrimina IVA: el precio es el total y la alícuota no cuenta', async () => {
    const { previsualizarFactura } = await import('./comprobantes')
    const v = previsualizarFactura([concepto({ alicuota_iva: '21' }), concepto({ alicuota_iva: '10.5' })], true)
    expect(v).toMatchObject({ neto: '2000.00', iva: '0.00', total: '2000.00', alicuotas: [] })
  })

  it('con alícuotas mezcladas informa cuáles son (la pantalla no deja emitir) y no inventa un IVA', async () => {
    const { previsualizarFactura } = await import('./comprobantes')
    const v = previsualizarFactura([concepto({ alicuota_iva: '21' }), concepto({ alicuota_iva: '10.5' })], false)
    expect(v.alicuotas.sort()).toEqual(['10.5', '21'])
    expect(v.iva).toBe('0.00')
  })

  it('un renglón a medio escribir no rompe la suma ni da NaN', async () => {
    const { previsualizarFactura } = await import('./comprobantes')
    const v = previsualizarFactura([concepto({ precio_unitario: '' }), concepto({ cantidad: 'abc' }),
      concepto({ cantidad: '2', precio_unitario: '10.00' })], false)
    expect(v).toMatchObject({ neto: '20.00', iva: '4.20', total: '24.20' })
    expect(previsualizarFactura([], false)).toMatchObject({ neto: '0.00', iva: '0.00', total: '0.00' })
  })
})

describe('esFactura', () => {
  it('sólo las facturas y las FCE admiten una nota; una nota no admite otra', async () => {
    const { esFactura } = await import('./comprobantes')
    for (const t of ['factura_a', 'factura_b', 'factura_c', 'fce_a', 'fce_b', 'fce_c'] as const) expect(esFactura(t)).toBe(true)
    for (const t of ['nota_credito_a', 'nota_credito_fce_c', 'nota_debito_b', 'nota_debito_fce_a'] as const) {
      expect(esFactura(t)).toBe(false)
    }
  })
})
