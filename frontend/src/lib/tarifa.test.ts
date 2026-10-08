import { describe, expect, it } from 'vitest'

import {
  aDecimal, conDosDecimales, formatearPorcentaje, porcentajeDesdeTarifa, tarifaDesdePorcentaje,
} from './tarifa'

describe('tarifa por tonelada · referencia × porcentaje', () => {
  it('🔑 el caso de Pereiro: 85 % de 23.205,57 es 19.724,73', () => {
    expect(tarifaDesdePorcentaje('23205.57', '85')).toBe('19724.73')
    expect(tarifaDesdePorcentaje('23205.57', '85.00')).toBe('19724.73')
  })

  it('100 % es la referencia misma, y 0 % es cero', () => {
    expect(tarifaDesdePorcentaje('23205.57', '100')).toBe('23205.57')
    expect(tarifaDesdePorcentaje('23205.57', '0')).toBe('0.00')
  })

  it('redondea al centavo, hacia arriba en la mitad: 50 % de 0,01 es 0,01 (0,005 → 0,01)', () => {
    expect(tarifaDesdePorcentaje('0.01', '50')).toBe('0.01')
    expect(tarifaDesdePorcentaje('0.01', '49.99')).toBe('0.00')
  })

  it('admite porcentajes con decimales y por encima de 100', () => {
    expect(tarifaDesdePorcentaje('10000.00', '82.5')).toBe('8250.00')
    expect(tarifaDesdePorcentaje('10000.00', '110')).toBe('11000.00')
  })

  it('🔴 no pasa por punto flotante: una referencia de nueve cifras no pierde centavos', () => {
    expect(tarifaDesdePorcentaje('123456789.99', '100')).toBe('123456789.99')
    // Con floats, 1.15 * 100 = 114.99999999999999.
    expect(tarifaDesdePorcentaje('1.15', '100')).toBe('1.15')
  })

  it('lo que no es un número da null, no NaN', () => {
    expect(tarifaDesdePorcentaje('23205.57', '')).toBeNull()
    expect(tarifaDesdePorcentaje('23205.57', 'mucho')).toBeNull()
    expect(tarifaDesdePorcentaje('', '85')).toBeNull()
  })

  it('acepta la coma como decimal y el punto como miles cuando hay coma', () => {
    expect(tarifaDesdePorcentaje('23205.57', '82,5')).toBe('19144.60')
    expect(tarifaDesdePorcentaje('23.205,57', '85')).toBe('19724.73')
  })
})

describe('tarifa por tonelada · el porcentaje de una tarifa', () => {
  it('19.724,73 sobre 23.205,57 es 85,00 %', () => {
    expect(porcentajeDesdeTarifa('23205.57', '19724.73')).toBe('85.00')
  })

  it('siempre con dos decimales', () => {
    expect(porcentajeDesdeTarifa('23205.57', '20000')).toBe('86.19')
    expect(porcentajeDesdeTarifa('10000.00', '8250')).toBe('82.50')
    expect(porcentajeDesdeTarifa('10000.00', '10000')).toBe('100.00')
  })

  it('sin referencia, con referencia cero o con una tarifa que no es número no hay porcentaje', () => {
    expect(porcentajeDesdeTarifa('0.00', '100')).toBeNull()
    expect(porcentajeDesdeTarifa('23205.57', '')).toBeNull()
    expect(porcentajeDesdeTarifa('23205.57', 'x')).toBeNull()
    expect(porcentajeDesdeTarifa('', '100')).toBeNull()
  })

  it('ida y vuelta: del porcentaje a la tarifa y de la tarifa al porcentaje vuelve al mismo', () => {
    for (const pct of ['85.00', '90.00', '72.50', '100.00']) {
      const tarifa = tarifaDesdePorcentaje('23205.57', pct) as string
      expect(porcentajeDesdeTarifa('23205.57', tarifa)).toBe(pct)
    }
  })
})

describe('texto decimal', () => {
  it('aDecimal normaliza lo que se escribe a punto decimal, hasta dos decimales', () => {
    expect(aDecimal('19724.73')).toBe('19724.73')
    expect(aDecimal('19724,73')).toBe('19724.73')
    expect(aDecimal('19.724,73')).toBe('19724.73')
    expect(aDecimal(' $ 19724 ')).toBe('19724')
    expect(aDecimal('19724.731')).toBeNull()
    expect(aDecimal('-5')).toBeNull()
    expect(aDecimal('')).toBeNull()
    expect(aDecimal(null)).toBeNull()
  })

  it('conDosDecimales completa los ceros', () => {
    expect(conDosDecimales('19724')).toBe('19724.00')
    expect(conDosDecimales('19724.7')).toBe('19724.70')
    expect(conDosDecimales('19724.73')).toBe('19724.73')
  })

  it('formatearPorcentaje saca los ceros de más y usa la coma', () => {
    expect(formatearPorcentaje('85.00')).toBe('85')
    expect(formatearPorcentaje('82.50')).toBe('82,5')
    expect(formatearPorcentaje('82.55')).toBe('82,55')
  })
})
