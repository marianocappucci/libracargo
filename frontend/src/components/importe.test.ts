import { describe, expect, it } from 'vitest'

import { formatearImporte } from './esquema-orden'

describe('formatearImporte', () => {
  it('el formato argentino: $ adelante, miles con punto, decimales con coma', () => {
    expect(formatearImporte('23000.34')).toBe('$ 23.000,34')
    expect(formatearImporte('1173307438.05')).toBe('$ 1.173.307.438,05')
    expect(formatearImporte('500.00')).toBe('$ 500,00')
  })

  it('🔴 NO pasa por `Number`: formatea sobre el texto', () => {
    // El importe llega como string porque es NUMERIC en la base y Decimal en
    // Python. `Number('9007199254740993.99')` pierde digitos --el entero ya no
    // entra en un float-- y este es el defecto que el producto vino a reparar.
    const enorme = '9007199254740993.99'
    expect(formatearImporte(enorme)).toBe('$ 9.007.199.254.740.993,99')
    expect(String(Number(enorme))).not.toContain('740993')
  })

  it('el signo va antes del peso, como se escribe en Argentina', () => {
    expect(formatearImporte('-30435034.47')).toBe('-$ 30.435.034,47')
  })

  it('completa los centavos que falten, para que la columna se lea derecha', () => {
    expect(formatearImporte('100')).toBe('$ 100,00')
    expect(formatearImporte('100.5')).toBe('$ 100,50')
  })

  it('un valor ausente no dice "$ 0,00": dice nada', () => {
    // Un cero y un dato que no vino son cosas distintas, y en una columna de
    // plata confundirlos es peor que dejar el hueco.
    expect(formatearImporte(null)).toBe('')
    expect(formatearImporte(undefined)).toBe('')
    expect(formatearImporte('')).toBe('')
    expect(formatearImporte('0.00')).toBe('$ 0,00')
  })
})
