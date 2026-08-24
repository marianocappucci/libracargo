// Guard: ninguna pantalla ni impreso de LibraCargo muestra una fecha en ISO.
//
// 🔴 Busca la propiedad final --"ningun campo de fecha llega al texto
// renderizado sin pasar por el helper"-- y no el patron viejo. La orden de carga
// que viaja con el camion llevaba la fecha en ISO teniendo el formateador en el
// mismo repo, y ningun grep de `%d/%m` lo iba a encontrar.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const RAIZ = new URL('..', import.meta.url).pathname

const CAMPO = String.raw`(?:fecha|fecha_[a-z_]+|date|[a-z_]+_at|valid_until|vencimiento|periodo|ts)`
const HELPERS = String.raw`(?:formatearFecha|formatearFechaHora|formatearFechaHoraDeTexto|fechaCorta|hoyEnArgentina)`

const INTERPOLADO = new RegExp(String.raw`\{\s*[A-Za-z_][\w.]*\.${CAMPO}\s*(?:\?\?[^}]*|\|\|[^}]*)?\}`)
// El `(?:\?\?\s*''\s*)?` cubre `(x ?? '').slice(0, 10)`, que es una de las
// formas reales que tomaron estas fugas.
const RECORTADO = new RegExp(String.raw`\.${CAMPO}[\w.]*\s*(?:\?\?\s*''\s*)?\)?\s*\.(?:slice|substring)\(0,\s*(?:10|16|19)\)`)
// Una columna IMPRESA (`valor:`) se ve tal cual. Una de tabla (`accessorFn`) es
// la clave de ORDEN y tiene que seguir en ISO -- esa se mira aparte.
const COLUMNA_IMPRESA = new RegExp(String.raw`\bvalor:\s*\([^)]*\)\s*=>\s*[^,]*\.${CAMPO}\b(?!\s*\()`)
const USA_HELPER = new RegExp(String.raw`\b${HELPERS}\s*\(`)

const EXCLUIDO = [
  /type="date"/, /tipo="date"/, /type="datetime-local"/, /\bkey=\{/,
  /^\s*(?:\/\/|\/\*|\*)/, /\bz\.(?:string|date|coerce)/,
  /\baria-label=|\btitle=/, /\bapi\.(?:get|post|put|del|patch)\(/,
]

export function fugasEn(texto: string): number[] {
  const fugas: number[] = []
  const lineas = texto.split('\n')
  lineas.forEach((linea, i) => {
    if (EXCLUIDO.some((r) => r.test(linea))) return
    const recortado = RECORTADO.test(linea)
    if (!INTERPOLADO.test(linea) && !recortado && !COLUMNA_IMPRESA.test(linea)) return
    if (USA_HELPER.test(linea) && !recortado) return
    if (!recortado && /[A-Za-z_-]+=\{[^{}]*\}\s*$/.test(linea.trim())) return
    fugas.push(i + 1)
  })
  return fugas
}

function archivos(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivos(p)
    return /\.tsx?$/.test(n) && !/\.test\./.test(n) ? [p] : []
  })
}

describe('ninguna fecha visible queda en ISO', () => {
  it('el detector encuentra una fuga cuando la hay', () => {
    // 🔴 Control POSITIVO. Sin el, un detector con un regex roto daria
    // exactamente el mismo verde que un codigo limpio: el cero de abajo solo
    // significa algo si este test pasa.
    expect(fugasEn('<p className="fecha">{orden.fecha}</p>')).toEqual([1])
    expect(fugasEn("{ encabezado: 'Fecha', valor: (f) => f.fecha },")).toEqual([1])
    expect(fugasEn("{(v.confirmed_at ?? '').slice(0, 10)}")).toEqual([1])
  })

  it('el detector NO marca lo que la regla excluye', () => {
    expect(fugasEn('<Campo tipo="date" valor={borrador.fecha} />')).toEqual([])
    expect(fugasEn('<p>{formatearFecha(orden.fecha)}</p>')).toEqual([])
    // El accessor de una tabla queda en ISO a proposito: es la clave de orden.
    expect(fugasEn('accessorFn: (g: Gasto) => g.fecha,')).toEqual([])
  })

  it('no queda ninguna en pages/ ni components/', () => {
    const sitios: string[] = []
    for (const dir of ['pages', 'components']) {
      let lista: string[]
      try {
        lista = archivos(join(RAIZ, dir))
      } catch {
        continue
      }
      for (const f of lista) {
        for (const linea of fugasEn(readFileSync(f, 'utf8'))) {
          sitios.push(`${f.replace(RAIZ, '')}:${linea}`)
        }
      }
    }
    expect(sitios).toEqual([])
  })
})
