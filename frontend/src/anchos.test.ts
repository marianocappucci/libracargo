import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/** El estado que rompe una tabla no es "sin anchos": es **la mezcla**.
 *
 *  El `DataTable` de libra-ui pasa a `table-fixed` en cuanto **alguna** columna
 *  declara `size`, y le pone a la tabla un `minWidth` igual a la suma de los
 *  anchos. Las que no declaran ninguno caen al default de TanStack —150 px—,
 *  así que agregar UNA columna con `size` a una tabla que no tenía ninguno
 *  puede empujar el mínimo por encima del ancho de pantalla y aparece el scroll
 *  horizontal.
 *
 *  - Todas sin `size` → `table-layout: auto`: el navegador las encoge. Sirve.
 *  - Todas con `size` → controlado. Sirve.
 *  - **Algunas sí y otras no** → es el que rompe, y rompe *después*, cuando
 *    alguien agrega una columna a una pantalla que ya andaba.
 *
 *  Pasó dos veces el mismo día: Caja —reportado por el humano— y Comprobantes
 *  de proveedores, las dos por agregarles una columna de acciones con `size`.
 *  Este guard existe para que no haya una tercera.
 *
 *  Lee el fuente y no el DOM a propósito: son nueve pantallas, y montar cada
 *  una con sus datos para contar columnas costaría más de lo que cubre.
 */

const PAGINAS = resolve(process.cwd(), 'src')
const DEFAULT_TANSTACK = 150

function fuentes(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const ruta = join(dir, e.name)
    if (e.isDirectory()) return fuentes(ruta)
    return e.name.endsWith('.tsx') && !e.name.endsWith('.test.tsx') ? [ruta] : []
  })
}

/** Los anchos declarados por cada definición de columna de un archivo. */
function anchosDe(texto: string): (number | null)[] {
  const columnas = texto.match(/\{\s*(?:id|accessorKey):\s*'[^']+'[^\n]*/g) ?? []
  return columnas.map((c) => {
    const m = c.match(/size:\s*(\d+)/)
    return m ? Number(m[1]) : null
  })
}

describe('anchos de las tablas', () => {
  const conTabla = fuentes(PAGINAS).filter((f) => readFileSync(f, 'utf8').includes('<DataTable'))

  it('el barrido encuentra las tablas, o el guard no prueba nada', () => {
    // Control: sin esto, un cambio de nombre del primitivo dejaría el test en
    // verde sobre cero archivos.
    expect(conTabla.length).toBeGreaterThanOrEqual(8)
  })

  it('🔴 ninguna tabla mezcla columnas con y sin ancho', () => {
    const mezcladas = conTabla.flatMap((archivo) => {
      const anchos = anchosDe(readFileSync(archivo, 'utf8'))
      const con = anchos.filter((a) => a !== null).length
      if (con === 0 || con === anchos.length) return []
      const minimo = anchos.reduce((t: number, a) => t + (a ?? DEFAULT_TANSTACK), 0)
      return [`${archivo.split('/src/')[1]}: ${con} de ${anchos.length} con ancho, `
              + `minimo ${minimo}px`]
    })
    expect(mezcladas).toEqual([])
  })

  it('ninguna tabla con anchos pide mas de lo que entra en un portatil', () => {
    const anchas = conTabla.flatMap((archivo) => {
      const anchos = anchosDe(readFileSync(archivo, 'utf8'))
      if (anchos.some((a) => a === null)) return []
      const minimo = anchos.reduce((t: number, a) => t + (a as number), 0)
      // 1.280 es un portátil común, y la pantalla además tiene barra lateral.
      return minimo > 1100 ? [`${archivo.split('/src/')[1]}: ${minimo}px`] : []
    })
    expect(anchas).toEqual([])
  })
})
