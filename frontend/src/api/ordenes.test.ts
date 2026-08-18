import { describe, expect, it } from 'vitest'

import { consulta } from './ordenes'

describe('consulta de filtros', () => {
  it('no manda los filtros que no se eligieron', () => {
    expect(consulta({})).toBe('')
    expect(consulta({ cliente_id: undefined, q: '' })).toBe('')
  })

  it('🔴 conserva `facturada=false`, que NO es lo mismo que no filtrar', () => {
    // Es el caso que un `if (v)` se come: `false` es falsy. Y es justo el
    // filtro que en el legado era una pantalla propia, la de facturar
    // pendientes -- o sea que perderlo devuelve TODAS las ordenes, incluidas
    // las ya facturadas, en la pantalla que sirve para facturar.
    expect(consulta({ facturada: false })).toBe('facturada=false')
    expect(consulta({ facturada: true })).toBe('facturada=true')
    expect(consulta({ facturada: undefined })).toBe('')
  })

  it('conserva el cero, que es un id valido para la base', () => {
    expect(consulta({ cliente_id: 0 })).toBe('cliente_id=0')
  })

  it('combina los filtros, que es el punto de F3', () => {
    const qs = consulta({ desde: '2026-08-01', cliente_id: 3, facturada: false })
    expect(new URLSearchParams(qs).get('desde')).toBe('2026-08-01')
    expect(new URLSearchParams(qs).get('cliente_id')).toBe('3')
    expect(new URLSearchParams(qs).get('facturada')).toBe('false')
  })
})
