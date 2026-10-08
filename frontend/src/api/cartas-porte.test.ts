import { describe, expect, it } from 'vitest'

import {
  MAX_CTGS, esEstadoFinal, etiquetaDeDelegacion, formatearCuit, formatearDiaDelInstante, formatearInstante,
  formatearKilos, leerCtgs, lineaDeCartaDePorte, nombreOCuit, textoDeInstrucciones, tonoDeDelegacion, tonoDeEstado,
} from './cartas-porte'

describe('formatearCuit', () => {
  it('pone los guiones a un CUIT de once dígitos', () => {
    expect(formatearCuit('30222222223')).toBe('30-22222222-3')
  })
  it('lo que ya tiene guiones queda igual, y lo que no es un CUIT vuelve tal cual', () => {
    expect(formatearCuit('30-22222222-3')).toBe('30-22222222-3')
    expect(formatearCuit('123')).toBe('123')
    expect(formatearCuit(null)).toBe('')
  })
})

describe('nombreOCuit', () => {
  it('prefiere el nombre; sin nombre, el CUIT con guiones; sin nada, un guion', () => {
    expect(nombreOCuit({ cuit: '30222222223', nombre: 'Agro SA' })).toBe('Agro SA')
    expect(nombreOCuit({ cuit: '30222222223', nombre: null })).toBe('30-22222222-3')
    expect(nombreOCuit({ cuit: null, nombre: null })).toBe('—')
  })
})

describe('leerCtgs', () => {
  it('acepta uno o varios separados por espacio, coma, punto y coma o renglón', () => {
    const r = leerCtgs('10123456781 10123456782,10123456783;10123456784\n10123456785\r\n10123456786')
    expect(r.validos).toEqual([10123456781, 10123456782, 10123456783, 10123456784, 10123456785, 10123456786])
    expect(r.invalidos).toEqual([])
    expect(r.repetidos).toBe(0)
  })
  it('quita los repetidos y cuenta cuántos quitó', () => {
    const r = leerCtgs('10123456781 10123456781, 10123456782 10123456781')
    expect(r.validos).toEqual([10123456781, 10123456782])
    expect(r.repetidos).toBe(2)
  })
  it('separa lo que no tiene exactamente 11 dígitos', () => {
    const r = leerCtgs('10123456781 1234 101234567812 abc 10123456781x')
    expect(r.validos).toEqual([10123456781])
    expect(r.invalidos).toEqual(['1234', '101234567812', 'abc', '10123456781x'])
  })
  it('el vacío no es nada: ni válidos ni inválidos', () => {
    expect(leerCtgs('  \n , ')).toEqual({ validos: [], invalidos: [], repetidos: 0, excede: false })
  })
  it(`avisa cuando pasa de ${MAX_CTGS}`, () => {
    const ctgs = (n: number) => Array.from({ length: n }, (_, i) => String(10000000000 + i)).join(' ')
    expect(leerCtgs(ctgs(MAX_CTGS)).excede).toBe(false)
    expect(leerCtgs(ctgs(MAX_CTGS + 1)).excede).toBe(true)
  })
})

describe('formatearKilos', () => {
  it('agrupa los miles con punto y no inventa decimales', () => {
    expect(formatearKilos(0)).toBe('0')
    expect(formatearKilos(950)).toBe('950')
    expect(formatearKilos(29500)).toBe('29.500')
    expect(formatearKilos(1234567)).toBe('1.234.567')
  })
  it('sin dato, un guion', () => {
    expect(formatearKilos(null)).toBe('—')
  })
})

describe('fechas de la carta', () => {
  it('un instante sin zona se reordena como texto: no pasa por Date', () => {
    expect(formatearInstante('2026-10-05T14:30:00')).toBe('05-10-2026 14:30')
    expect(formatearDiaDelInstante('2026-10-05T14:30:00')).toBe('05-10-2026')
  })
  it('un instante con zona se lee en hora de Argentina', () => {
    expect(formatearInstante('2026-10-05T16:00:00-03:00')).toBe('05-10-2026 16:00')
    expect(formatearInstante('2026-10-05T19:00:00Z')).toBe('05-10-2026 16:00')
    // Las 01:00 UTC del 6 son las 22:00 del 5 en Argentina: el día también se corre.
    expect(formatearDiaDelInstante('2026-10-06T01:00:00Z')).toBe('05-10-2026')
  })
  it('sin fecha, un guion', () => {
    expect(formatearInstante(null)).toBe('—')
    expect(formatearDiaDelInstante(null)).toBe('—')
  })
})

describe('estado', () => {
  it('los finales son los mismos que no vuelve a consultar el backend', () => {
    for (const e of ['AN', 'RE', 'DE']) expect(esEstadoFinal(e)).toBe(true)
    for (const e of ['AC', 'CF', 'CN', 'DD', 'CO']) expect(esEstadoFinal(e)).toBe(false)
  })
  it('cada estado tiene su tono y un código desconocido queda neutro', () => {
    expect(tonoDeEstado('AC')).toBe('curso')
    expect(tonoDeEstado('DD')).toBe('ok')
    expect(tonoDeEstado('CO')).toBe('atencion')
    expect(tonoDeEstado('AN')).toBe('negativo')
    expect(tonoDeEstado('XX')).toBe('neutro')
  })
})

describe('titulares: cómo se leen (ADR-044)', () => {
  it('cada estado de delegación tiene su texto y su tono', () => {
    expect(etiquetaDeDelegacion('delegado')).toBe('Delegado ✓')
    expect(etiquetaDeDelegacion('pendiente')).toBe('Pendiente')
    expect(etiquetaDeDelegacion('sin_verificar')).toBe('Sin verificar')
    // Emite él: la delegación se muestra igual, con para qué sirve (consultar).
    expect(etiquetaDeDelegacion('delegado', 'titular')).toBe('Emite él · consulta habilitada ✓')
    expect(etiquetaDeDelegacion('pendiente', 'titular')).toBe('Emite él · falta delegar (para consultar)')
    expect(etiquetaDeDelegacion('sin_verificar', 'titular')).toBe('Emite él · sin verificar')
    expect(tonoDeDelegacion('delegado')).toBe('ok')
    expect(tonoDeDelegacion('pendiente')).toBe('atencion')
    expect(tonoDeDelegacion('sin_verificar')).toBe('neutro')
  })

  it('la línea de la ficha del cliente', () => {
    expect(lineaDeCartaDePorte({ emite: 'nosotros', delegacion: 'delegado', activo: true })).toBe('delegó a nosotros ✓')
    expect(lineaDeCartaDePorte({ emite: 'titular', delegacion: 'delegado', activo: true }))
      .toBe('emite él · consulta habilitada ✓')
    expect(lineaDeCartaDePorte({ emite: 'titular', delegacion: 'pendiente', activo: true }))
      .toBe('emite él · falta que delegue (para consultar sus cartas por CTG)')
    expect(lineaDeCartaDePorte({ emite: 'titular', delegacion: 'sin_verificar', activo: true }))
      .toBe('emite él (sin verificar en ARCA)')
    expect(lineaDeCartaDePorte({ emite: 'nosotros', delegacion: 'pendiente', activo: true })).toMatch(/^pendiente/)
    expect(lineaDeCartaDePorte({ emite: 'nosotros', delegacion: 'sin_verificar', activo: true }))
      .toBe('emitimos nosotros (sin verificar en ARCA)')
    expect(lineaDeCartaDePorte({ emite: 'titular', delegacion: 'delegado', activo: false }))
      .toBe('emite él · consulta habilitada ✓ · dado de baja')
  })
})

describe('textoDeInstrucciones', () => {
  const cert = { alias: 'libracargowscpeprod', cuit_representante: '20111111112', ambiente: 'produccion' as const }

  it('arma el paso a paso con el CUIT del representante y el alias, sin escribir ninguno a mano', () => {
    const t = textoDeInstrucciones(cert)
    expect(t).toContain('actuando en representación del titular')
    expect(t).toContain('wscpe (Carta de Porte Electrónica)')
    expect(t).toContain('Representante: Buscar → CUIT 20-11111111-2')
    expect(t).toContain('en Computador Fiscal elegir libracargowscpeprod (no el que termina en «homo»)')
    expect(t).toContain('Confirmar dos veces')
    const otro = textoDeInstrucciones({ ...cert, alias: 'otroalias', cuit_representante: '27222222224' })
    expect(otro).toContain('CUIT 27-22222222-4')
    expect(otro).toContain('elegir otroalias')
    expect(otro).not.toContain('libracargowscpeprod')
  })

  it('para el que emite él pide delegar la consulta, no la emisión', () => {
    expect(textoDeInstrucciones(cert, 'Agro Norte SA', true)).toContain('podamos consultar tus cartas de porte por CTG')
    expect(textoDeInstrucciones(cert, 'Agro Norte SA', true)).toContain('wscpe (Carta de Porte Electrónica)')
    expect(textoDeInstrucciones(cert)).toContain('podamos emitir tus cartas de porte')
  })

  it('nombra al titular si se lo conoce', () => {
    expect(textoDeInstrucciones(cert, 'Agro Norte SA')).toContain('actuando en representación de Agro Norte SA')
  })
})
