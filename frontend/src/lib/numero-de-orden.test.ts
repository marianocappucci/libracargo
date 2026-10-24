import { describe, expect, it } from 'vitest'

import { esOrdenProvisoria, numeroCorto, numeroDeOrden, numeroImpreso, tituloDeOrden } from './numero-de-orden'

describe('el id de una orden cargada en el nodo', () => {
  it('un id negativo es provisorio; el 0, los positivos y lo que no es un número, no', () => {
    expect(esOrdenProvisoria(-3)).toBe(true)
    expect(esOrdenProvisoria('-3')).toBe(true)
    for (const id of [0, 1, 41, null, undefined, '', 'abc', 1.5]) expect(esOrdenProvisoria(id as number)).toBe(false)
  })

  it('🔴 una orden provisoria no se dibuja como un número de orden real (nada de «Nº 000000-3» ni «#-3»)', () => {
    expect(tituloDeOrden(-3)).toBe('Orden provisoria P-3')
    expect(numeroImpreso(-3)).toBe('Provisoria P-3')
    expect(numeroCorto(-3)).toBe('P-3')
    expect(numeroDeOrden(-3)).toBe('P-3')
    for (const texto of [tituloDeOrden(-3), numeroImpreso(-3), numeroCorto(-3), numeroDeOrden(-3)]) {
      expect(texto).not.toMatch(/(?<!P)-3/)
      expect(texto).not.toMatch(/Nº/)
    }
  })

  it('una orden del central se muestra exactamente como siempre', () => {
    expect(tituloDeOrden(41)).toBe('Orden Nº 00000041')
    expect(numeroImpreso(41)).toBe('Nº 00000041')
    expect(numeroCorto(41)).toBe('41')
    expect(numeroDeOrden(41)).toBe('00000041')
  })

  it('la provisoria 3 y la orden 3 del central no se confunden', () => {
    expect(numeroCorto(-3)).not.toBe(numeroCorto(3))
    expect(tituloDeOrden(-3)).not.toBe(tituloDeOrden(3))
  })
})
