/** Las cuentas de la tarifa por tonelada (ADR-038): referencia × porcentaje, y su inversa.
 *
 *  🔴 **Sobre el texto, con enteros, nunca con `Number`.** Los importes de este producto son `NUMERIC` en la base y
 *  `Decimal` en Python; pasarlos por un float binario es el defecto del legado que el producto vino a reparar (ver
 *  `formatearImporte`). Acá todo se lleva en centésimas (`bigint`): `23205.57` es `2320557n`, `85.00 %` es `8500n`.
 *  El redondeo es al centavo, hacia arriba en la mitad, que es lo que hace el servidor con `ROUND_HALF_UP`.
 */

/** `19.724,73`, `19724,73`, `19724.73` → `19724.73`. Con coma, el punto es de miles; con sólo punto, es decimal (como
 *  los demás importes del formulario). Hasta dos decimales; lo demás (letras, tres decimales, vacío) es `null`. */
export function aDecimal(texto: string | null | undefined): string | null {
  const t = (texto ?? '').trim().replace(/[$\s]/g, '')
  const n = t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t
  return /^\d+(\.\d{0,2})?$/.test(n) ? n : null
}

/** `19724.7` → `19724.70`, `19724` → `19724.00`: dos decimales siempre, como los manda la API. */
export function conDosDecimales(decimal: string): string {
  const [entero, decimales = ''] = decimal.split('.')
  return `${entero}.${(decimales + '00').slice(0, 2)}`
}

function aCentesimas(texto: string | null | undefined): bigint | null {
  const decimal = aDecimal(texto)
  return decimal === null ? null : BigInt(conDosDecimales(decimal).replace('.', ''))
}

function deCentesimas(n: bigint): string {
  return `${n / 100n}.${(n % 100n).toString().padStart(2, '0')}`
}

/** `numerador / divisor` redondeado a entero, hacia arriba en la mitad. Sólo para no negativos. */
function dividir(numerador: bigint, divisor: bigint): bigint {
  return (numerador * 2n + divisor) / (divisor * 2n)
}

/** La tarifa por tonelada que resulta de pactar `porcentaje` sobre la `referencia`: `23205.57` × `85` → `19724.73`.
 *  `null` si alguno de los dos no es un número. */
export function tarifaDesdePorcentaje(referencia: string, porcentaje: string): string | null {
  const r = aCentesimas(referencia)
  const p = aCentesimas(porcentaje)
  if (r === null || p === null) return null
  return deCentesimas(dividir(r * p, 10000n))
}

/** El porcentaje de la `referencia` que es la `tarifa`, con dos decimales: `19724.73` sobre `23205.57` → `85.00`.
 *  `null` si falta alguno o la referencia es cero (no hay sobre qué calcular). */
export function porcentajeDesdeTarifa(referencia: string, tarifa: string): string | null {
  const r = aCentesimas(referencia)
  const t = aCentesimas(tarifa)
  if (r === null || t === null || r === 0n) return null
  return deCentesimas(dividir(t * 10000n, r))
}

/** `85.00` → `85`, `82.50` → `82,5`: el porcentaje como se dice, sin ceros de más. */
export function formatearPorcentaje(valor: string): string {
  const [entero, decimales = ''] = valor.split('.')
  const sinCeros = decimales.replace(/0+$/, '')
  return sinCeros ? `${entero},${sinCeros}` : entero
}
