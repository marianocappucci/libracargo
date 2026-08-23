// El formateo de fechas de LibraCargo, que vive en `esquema-orden.ts` junto a
// `hoyEnArgentina` para que el producto tenga un solo lugar donde se decide como
// se ve una fecha.
//
// 🔴 Los asserts miden la propiedad final ("ninguna salida visible queda en ISO
// ni trae barra"), no el patron viejo. Las fechas que este cambio cerro nunca
// pasaron por un `toLocaleDateString`: llegaban crudas de la API al papel.
import { describe, expect, it } from 'vitest'

import {
  formatearFecha,
  formatearFechaHora,
  formatearFechaHoraDeTexto,
} from './esquema-orden'

describe('formatearFecha()', () => {
  it('da vuelta el ISO que devuelve la API', () => {
    expect(formatearFecha('2026-08-22')).toBe('22-08-2026')
  })

  it('no confunde el dia con el mes', () => {
    // 🔴 El control que separa `dd-mm-aaaa` de `mm-dd-aaaa`: con `2026-01-01`
    // las dos lecturas dan el mismo texto y el test pasaria invertido.
    expect(formatearFecha('2026-03-11')).toBe('11-03-2026')
  })

  it('NO corre el dia para atras', () => {
    // 🔴 `new Date('2026-08-22')` es medianoche UTC = 21:00 del 21 en Argentina.
    // Formatear eso convirtiendo de zona muestra el dia anterior SIEMPRE. Es el
    // mismo defecto que `hoyEnArgentina` evita en la otra direccion.
    expect(formatearFecha('2026-08-22')).not.toBe('21-08-2026')
    expect(formatearFecha('2026-01-01')).toBe('01-01-2026')
  })

  it('de un timestamp se queda con la fecha', () => {
    expect(formatearFecha('2026-08-22T23:30:00')).toBe('22-08-2026')
  })

  it('ninguna salida trae barra ni queda en ISO', () => {
    for (const entrada of ['2026-08-22', '2026-08-22T14:30:00', '2026-12-31']) {
      const salida = formatearFecha(entrada)
      expect(salida).not.toContain('/')
      expect(salida).not.toMatch(/^\d{4}-\d{2}-\d{2}/)
    }
  })

  it('lo que no es una fecha vuelve como vino', () => {
    expect(formatearFecha('')).toBe('')
    expect(formatearFecha(null)).toBe('')
    expect(formatearFecha('s/f')).toBe('s/f')
  })
})

describe('formatearFechaHoraDeTexto()', () => {
  it('da `dd-mm-aaaa HH:MM` en reloj de 24 h', () => {
    expect(formatearFechaHoraDeTexto('2026-08-22T14:30:00')).toBe('22-08-2026 14:30')
    expect(formatearFechaHoraDeTexto('2026-08-22 18:45:07')).toBe('22-08-2026 18:45')
  })

  it('un valor sin hora sale solo como fecha', () => {
    expect(formatearFechaHoraDeTexto('2026-08-22')).toBe('22-08-2026')
  })
})

describe('formatearFechaHora()', () => {
  it('sigue formateando un Date en hora de Argentina', () => {
    // El sello de "emitido el" de los impresos. Se conserva la firma que ya
    // usaban `OrdenImpresa` e `impresion`.
    const salida = formatearFechaHora(new Date('2026-08-23T01:00:00Z'))
    expect(salida).toBe('22-08-2026 22:00')
  })
})
