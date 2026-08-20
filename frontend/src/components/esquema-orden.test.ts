import { describe, expect, it } from 'vitest'

import { ORDEN_VACIA, esquemaOrden, hoyEnArgentina } from './esquema-orden'

describe('esquema de la orden', () => {
  it('rechaza el origen igual al destino, y lo dice en el campo destino', () => {
    const r = esquemaOrden.safeParse({
      fecha: '2026-08-18', cliente_id: '1', origen_id: '2', destino_id: '2',
      tarifa: '1000.00', alicuota_iva: '21.00', comision: '0.00',
    })
    expect(r.success).toBe(false)
    if (!r.success) {
      expect(r.error.issues[0].path).toEqual(['destino_id'])
      expect(r.error.issues[0].message).toContain('origen y el destino')
    }
  })

  it('convierte los ids de texto a numero, porque un select devuelve texto', () => {
    const r = esquemaOrden.safeParse({
      fecha: '2026-08-18', cliente_id: '7', origen_id: '2', destino_id: '3',
      tarifa: '1000.00', alicuota_iva: '21.00', comision: '0.00',
    })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.cliente_id).toBe(7)
  })

  it('rechaza un importe que no es un importe', () => {
    const base = {
      fecha: '2026-08-18', cliente_id: '1', origen_id: '2', destino_id: '3',
      alicuota_iva: '21.00', comision: '0.00',
    }
    expect(esquemaOrden.safeParse({ ...base, tarifa: 'mil pesos' }).success).toBe(false)
    expect(esquemaOrden.safeParse({ ...base, tarifa: '1000.999' }).success).toBe(false)
    expect(esquemaOrden.safeParse({ ...base, tarifa: '1000.99' }).success).toBe(true)
  })

  it('🔴 la fecha por defecto es la de Argentina, no la de UTC', () => {
    // `toISOString()` da UTC: a las 21:00 de Argentina ya es el dia siguiente,
    // y una orden cargada de noche nacia con la fecha de manana. El error es
    // invisible --la fecha es plausible-- hasta que no cierra un listado.
    const enUtc = new Date().toISOString().slice(0, 10)
    const enArgentina = hoyEnArgentina()
    expect(ORDEN_VACIA.fecha).toBe(enArgentina)
    // Nunca puede estar ADELANTE de UTC: Argentina es UTC-3.
    expect(enArgentina <= enUtc).toBe(true)
  })
})
