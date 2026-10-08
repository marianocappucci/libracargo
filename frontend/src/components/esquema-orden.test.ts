import { describe, expect, it } from 'vitest'

import {
  ORDEN_VACIA, esquemaOrden, formatearTamanio, hoyEnArgentina, netoCalculado,
} from './esquema-orden'

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

describe('esquema de la orden · etapa y kilos', () => {
  const base = {
    fecha: '2026-10-05', cliente_id: '1', origen_id: '2', destino_id: '3',
    tarifa: '1000.00', alicuota_iva: '21.00', comision: '0.00',
  }

  it('sin etapa ni kilos, la orden nace «asignada» y con los kilos en null', () => {
    const r = esquemaOrden.safeParse(base)
    expect(r.success).toBe(true)
    if (r.success) {
      expect(r.data.etapa).toBe('asignada')
      expect(r.data.kg_bruto_carga).toBeNull()
      expect(r.data.kg_neto_descarga).toBeNull()
    }
  })

  it('los kilos vacíos son «no se sabe» (null), no cero', () => {
    const r = esquemaOrden.safeParse({ ...base, kg_bruto_carga: '', kg_tara_carga: '', kg_neto_carga: '' })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.kg_neto_carga).toBeNull()
  })

  it('con bruto y tara el neto es la resta, aunque haya quedado otro tipeado', () => {
    const r = esquemaOrden.safeParse({
      ...base, kg_bruto_carga: '44000', kg_tara_carga: '14500', kg_neto_carga: '1',
      kg_bruto_descarga: '100', kg_tara_descarga: '100',
    })
    expect(r.success).toBe(true)
    if (r.success) {
      expect(r.data).toMatchObject({ kg_bruto_carga: 44000, kg_tara_carga: 14500, kg_neto_carga: 29500 })
      // Tara igual al bruto es válida: neto cero.
      expect(r.data.kg_neto_descarga).toBe(0)
    }
  })

  it('el neto solo se acepta', () => {
    const r = esquemaOrden.safeParse({ ...base, kg_neto_descarga: '29480' })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data).toMatchObject({ kg_neto_descarga: 29480, kg_bruto_descarga: null })
  })

  it('🔴 tara mayor que el bruto se rechaza en el campo de la tara, con el mensaje del backend', () => {
    const r = esquemaOrden.safeParse({ ...base, kg_bruto_carga: '10000', kg_tara_carga: '12000' })
    expect(r.success).toBe(false)
    if (!r.success) {
      expect(r.error.issues[0].path).toEqual(['kg_tara_carga'])
      expect(r.error.issues[0].message)
        .toBe('los kilos de carga: la tara (12000) no puede ser mayor que el bruto (10000)')
    }
  })

  it('kilos negativos, con decimales o que no son un número se rechazan', () => {
    for (const malo of ['-1', '10.5', 'mucho']) {
      expect(esquemaOrden.safeParse({ ...base, kg_bruto_carga: malo }).success, malo).toBe(false)
    }
  })

  it('una etapa que no existe se rechaza', () => {
    expect(esquemaOrden.safeParse({ ...base, etapa: 'volando' }).success).toBe(false)
    expect(esquemaOrden.safeParse({ ...base, etapa: 'en_viaje' }).success).toBe(true)
  })

  it('editar una orden sin remito, cantidad ni observaciones (null en la API) no se traba', () => {
    const r = esquemaOrden.safeParse({ ...base, remito: null, cantidad: null, unidad: null, observaciones: null })
    expect(r.success).toBe(true)
  })
})

describe('netoCalculado', () => {
  it('es bruto menos tara sólo cuando se puede', () => {
    expect(netoCalculado('44000', '14500')).toBe(29500)
    expect(netoCalculado(44000, 14500)).toBe(29500)
    expect(netoCalculado('', '14500')).toBeNull()
    expect(netoCalculado('44000', null)).toBeNull()
    expect(netoCalculado('10', '20')).toBeNull()
  })
})

describe('formatearTamanio', () => {
  it('lo lee como una persona', () => {
    expect(formatearTamanio(850)).toBe('850 B')
    expect(formatearTamanio(1536)).toBe('1,5 KB')
    expect(formatearTamanio(2048)).toBe('2 KB')
    expect(formatearTamanio(2_411_724)).toBe('2,3 MB')
    expect(formatearTamanio(10 * 1024 * 1024)).toBe('10 MB')
  })
})

describe('esquema de la orden · km y tarifa por tonelada', () => {
  const base = {
    fecha: '2026-10-05', cliente_id: '1', origen_id: '2', destino_id: '3',
    tarifa: '1000.00', alicuota_iva: '21.00', comision: '0.00',
  }
  const salida = (extra: Record<string, unknown>) => {
    const r = esquemaOrden.safeParse({ ...base, ...extra })
    return r.success ? r.data : r.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`)
  }

  it('sin km ni tarifa por tonelada se mandan null, no cero ni vacío', () => {
    expect(salida({})).toMatchObject({ km: null, tarifa_tonelada: null })
    expect(salida({ km: '', tarifa_tonelada: '' })).toMatchObject({ km: null, tarifa_tonelada: null })
    expect(salida({ km: null, tarifa_tonelada: null })).toMatchObject({ km: null, tarifa_tonelada: null })
  })

  it('los km son un entero de 1 a 99999 (el texto del input se convierte)', () => {
    expect(salida({ km: '80' })).toMatchObject({ km: 80 })
    expect(salida({ km: '99999' })).toMatchObject({ km: 99999 })
    expect(salida({ km: '0' })).toEqual(['km: los km son 1 o más'])
    expect(salida({ km: '100000' })).toEqual(['km: los km no pueden pasar de 99999'])
    expect(salida({ km: '80.5' })).toEqual(['km: los km son un número entero'])
    expect(salida({ km: 'lejos' })).toEqual(['km: los km tienen que ser un número'])
  })

  it('🔑 la tarifa por tonelada viaja como TEXTO con dos decimales, y acepta la coma', () => {
    expect(salida({ tarifa_tonelada: '19724.73' })).toMatchObject({ tarifa_tonelada: '19724.73' })
    expect(salida({ tarifa_tonelada: '19724.7' })).toMatchObject({ tarifa_tonelada: '19724.70' })
    expect(salida({ tarifa_tonelada: '19724' })).toMatchObject({ tarifa_tonelada: '19724.00' })
    expect(salida({ tarifa_tonelada: '19724,73' })).toMatchObject({ tarifa_tonelada: '19724.73' })
    expect(salida({ tarifa_tonelada: '19.724,73' })).toMatchObject({ tarifa_tonelada: '19724.73' })
  })

  it('una tarifa por tonelada que no es un importe se rechaza en su campo', () => {
    expect(salida({ tarifa_tonelada: 'mucho' })).toEqual(['tarifa_tonelada: importe inválido'])
    expect(salida({ tarifa_tonelada: '1.234' })).toEqual(['tarifa_tonelada: importe inválido'])
    expect(salida({ tarifa_tonelada: '-5' })).toEqual(['tarifa_tonelada: importe inválido'])
  })
})
