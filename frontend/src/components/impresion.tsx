/** Impresión de listados: una hoja, para todas las pantallas.
 *
 * 🔑 **No se imprime lo que está en pantalla: se pide de nuevo.** La grilla
 * muestra una página —200 filas por omisión— y quien manda a imprimir un listado
 * filtrado espera el listado, no la página. `BotonImprimir` vuelve a pedir los
 * datos con los mismos filtros y arma la hoja con todo lo que traiga.
 *
 * 🔑 **Y si no entró todo, lo dice.** La API corta en 1.000 por pedido; el
 * botón pagina hasta `TOPE` y, si aun así queda afuera, la hoja lo escribe en el
 * encabezado. Un papel que dice "Órdenes de carga" y trae la mitad, sin avisar,
 * es peor que uno que no se imprimió.
 */
import { Printer } from 'lucide-react'
import { useState } from 'react'
import { createPortal } from 'react-dom'

import { Button } from '@/components/ui/button'
import { formatearFechaHora, formatearImporte } from '@/components/esquema-orden'

/** Tope de filas que se piden para una hoja. Con 4.337 órdenes, imprimir todo
 *  sin filtrar son ~90 páginas: el tope está para que el navegador no se
 *  cuelgue, y se avisa cuando actúa. */
export const TOPE = 5000
const POR_PEDIDO = 1000

export type Columna<T> = {
  encabezado: string
  valor: (fila: T) => string | number | null | undefined
  /** Los números van a la derecha, como en cualquier planilla. */
  numerica?: boolean
  /** Además, es plata: se imprime `$1.234,56`. No todas las columnas numéricas
   *  lo son —una cantidad de órdenes o de toneladas no lleva signo pesos—, así
   *  que la marca es explícita. */
  moneda?: boolean
}

export type Total = { etiqueta: string; valor: string }

/** Pide de a `POR_PEDIDO` hasta que no venga más, o hasta el tope. */
export async function traerTodo<T>(
  pagina: (desplazamiento: number, limite: number) => Promise<T[]>,
): Promise<{ filas: T[]; truncado: boolean }> {
  const filas: T[] = []
  for (let desplazamiento = 0; desplazamiento < TOPE; desplazamiento += POR_PEDIDO) {
    const tanda = await pagina(desplazamiento, POR_PEDIDO)
    filas.push(...tanda)
    if (tanda.length < POR_PEDIDO) return { filas, truncado: false }
  }
  return { filas, truncado: true }
}

export function HojaImpresa<T>({ titulo, filtros, columnas, filas, totales, truncado }: {
  titulo: string
  filtros?: string
  columnas: Columna<T>[]
  filas: T[]
  totales?: Total[]
  truncado?: boolean
}) {
  return (
    <div id="hoja-impresa" className="hoja-impresa">
      <header>
        <h1>{titulo}</h1>
        <p>
          LibraCargo · emitido el {formatearFechaHora(new Date())} · {filas.length} registro
          {filas.length === 1 ? '' : 's'}
        </p>
        {filtros && <p>Filtros: {filtros}</p>}
        {truncado && (
          <p className="aviso">
            ⚠️ La hoja corta en los primeros {TOPE} registros. Acotá el filtro para
            imprimir el resto.
          </p>
        )}
      </header>
      <table>
        <thead>
          <tr>
            {columnas.map((c) => (
              <th key={c.encabezado} className={c.numerica ? 'derecha' : undefined}>
                {c.encabezado}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((fila, i) => (
            <tr key={i}>
              {columnas.map((c) => (
                <td key={c.encabezado} className={c.numerica ? 'derecha' : undefined}>
                  {c.moneda ? formatearImporte(c.valor(fila)) : (c.valor(fila) ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {totales && totales.length > 0 && (
        <footer>
          {totales.map((t) => (
            <p key={t.etiqueta}><strong>{t.etiqueta}:</strong> {t.valor}</p>
          ))}
        </footer>
      )}
    </div>
  )
}

export function BotonImprimir<T>({ titulo, filtros, columnas, traer, totales, etiqueta }: {
  titulo: string
  filtros?: string
  columnas: Columna<T>[]
  traer: () => Promise<{ filas: T[]; truncado: boolean }>
  totales?: (filas: T[]) => Total[]
  etiqueta?: string
}) {
  const [hoja, setHoja] = useState<{ filas: T[]; truncado: boolean } | null>(null)
  const [cargando, setCargando] = useState(false)

  async function imprimir() {
    setCargando(true)
    try {
      const datos = await traer()
      setHoja(datos)
      // Se espera un frame para que la hoja esté en el DOM antes de abrir el
      // diálogo del navegador: `window.print()` fotografía lo que hay, y si se
      // llama en el mismo tick imprime la página sin la hoja.
      requestAnimationFrame(() => requestAnimationFrame(() => {
        window.print()
        setHoja(null)
      }))
    } finally {
      setCargando(false)
    }
  }

  return (
    <>
      <Button variant="outline" onClick={imprimir} disabled={cargando} className="no-imprimir">
        <Printer className="size-4" /> {cargando ? 'Preparando…' : (etiqueta ?? 'Imprimir')}
      </Button>
      {hoja && createPortal(
        <HojaImpresa
          titulo={titulo} filtros={filtros} columnas={columnas}
          filas={hoja.filas} truncado={hoja.truncado}
          totales={totales?.(hoja.filas)}
        />,
        document.body,
      )}
    </>
  )
}
