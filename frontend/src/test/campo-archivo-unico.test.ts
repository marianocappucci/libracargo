// Guard: todo campo de archivo del producto es el `CampoArchivo` de libra-ui
// (ADR-037 del kit), igual que el guard del propio kit.
//
// 🔴 La regla es la propiedad final —«no hay un `<input type="file">` propio en
// `src/`»—, no el nombre de las pantallas que lo tenían (los documentos del paciente):
// la próxima que suba un archivo va a ser otra. Un campo nativo vuelve a dibujar el
// botón y el texto del navegador, en su idioma y distinto en cada uno.
//
// Lee el FUENTE en vez de renderizar, como `sin-hoy-en-utc`. Se saltea `src/test/`:
// los tests buscan el input nativo que `CampoArchivo` deja adentro
// (`input[type="file"]`), y eso es un selector, no un campo.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { cwd } from 'node:process'

import { describe, expect, it } from 'vitest'

const RAIZ = cwd()
const SRC = join(RAIZ, 'src')
const TESTS = join(SRC, 'test')
/** Si el barrido ve menos que esto, la ruta está mal y el cero no vale. */
const MINIMO_DE_ARCHIVOS = 20

const CAMPO_NATIVO = /\btype\s*(?:=\s*\{?\s*|:\s*)(['"`])file\1/

export function camposNativosEn(texto: string): number[] {
  const lineas: number[] = []
  texto.split('\n').forEach((linea, i) => {
    // Un comentario que EXPLICA el patrón no es un uso.
    if (/^\s*(?:\/\/|\/\*|\*)/.test(linea)) return
    if (CAMPO_NATIVO.test(linea)) lineas.push(i + 1)
  })
  return lineas
}

function fuentes(dir: string): string[] {
  if (dir === TESTS) return []
  return readdirSync(dir).flatMap((nombre) => {
    const ruta = join(dir, nombre)
    if (statSync(ruta).isDirectory()) return fuentes(ruta)
    return /\.tsx?$/.test(nombre) ? [ruta] : []
  })
}

describe('un solo campo de archivo: el del kit', () => {
  const archivos = fuentes(SRC)

  it('el barrido vio los fuentes', () => {
    expect(archivos.length).toBeGreaterThanOrEqual(MINIMO_DE_ARCHIVOS)
  })

  it('🔴 ningún `type="file"` propio en src/: se usa `libra-ui/CampoArchivo`', () => {
    const fugas = archivos.flatMap((a) =>
      camposNativosEn(readFileSync(a, 'utf8')).map((n) => `${relative(RAIZ, a)}:${n}`),
    )
    expect(fugas).toEqual([])
  })

  it.each([
    '<input type="file" />',
    "<Input type='file' accept='.zip' />",
    '<input type={"file"} />',
    "React.createElement('input', { type: 'file' })",
  ])('reconoce %j', (texto) => {
    expect(camposNativosEn(texto).length).toBeGreaterThan(0)
  })

  it.each([
    '<input type="text" />',
    '// el <input type="file"> nativo',
    '<input type="filename" />',
  ])('no marca %j', (texto) => {
    expect(camposNativosEn(texto)).toEqual([])
  })
})
