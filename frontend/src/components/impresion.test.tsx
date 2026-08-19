import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('libra-ui/api-client', () => ({
  ApiError: class extends Error {},
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { BotonImprimir, traerTodo, TOPE } = await import('./impresion')

type Fila = { id: number; total: string }

const COLUMNAS = [
  { encabezado: 'Id', valor: (f: Fila) => f.id },
  { encabezado: 'Total', valor: (f: Fila) => f.total, numerica: true },
]

function filas(desde: number, cantidad: number): Fila[] {
  return Array.from({ length: cantidad }, (_, i) => ({
    id: desde + i, total: String(desde + i),
  }))
}

describe('traerTodo', () => {
  it('pide de a mil hasta que la tanda viene corta', async () => {
    const pagina = vi.fn(async (desplazamiento: number) =>
      desplazamiento < 2000 ? filas(desplazamiento, 1000) : filas(2000, 137))
    const { filas: todas, truncado } = await traerTodo(pagina)
    expect(todas.length).toBe(2137)
    expect(truncado).toBe(false)
    expect(pagina).toHaveBeenCalledTimes(3)
  })

  it('🔴 avisa cuando corta en el tope, en vez de imprimir la mitad en silencio', async () => {
    // Un papel que dice "Ordenes de carga" y trae la mitad, sin decirlo, es peor
    // que uno que no se imprimio.
    const pagina = vi.fn(async (d: number) => filas(d, 1000))
    const { filas: todas, truncado } = await traerTodo(pagina)
    expect(todas.length).toBe(TOPE)
    expect(truncado).toBe(true)
  })
})

describe('BotonImprimir', () => {
  beforeEach(() => { window.print = vi.fn() })

  it('la hoja trae TODAS las filas, no las que estan en pantalla', async () => {
    // La grilla muestra una pagina; el papel tiene que traer el listado.
    render(
      <BotonImprimir
        titulo="Órdenes de carga" filtros="cliente: 3"
        columnas={COLUMNAS}
        traer={async () => ({ filas: filas(1, 1200), truncado: false })}
        totales={(f) => [{ etiqueta: 'Órdenes', valor: String(f.length) }]}
      />,
    )
    fireEvent.click(screen.getByText('Imprimir'))

    const hoja = await waitFor(() => {
      const h = document.getElementById('hoja-impresa')
      expect(h).not.toBeNull()
      return h!
    })
    expect(hoja.querySelectorAll('tbody tr').length).toBe(1200)
    expect(hoja.textContent).toContain('1200 registros')
    // El encabezado dice sobre que esta calculada la hoja: sin eso, dos papeles
    // del mismo listado con filtros distintos son indistinguibles.
    expect(hoja.textContent).toContain('cliente: 3')
    expect(hoja.textContent).toContain('Órdenes de carga')
    expect(hoja.textContent).toContain('Órdenes:')
  })

  it('el aviso de corte aparece sólo cuando se cortó', async () => {
    // El texto se captura DENTRO del waitFor: la hoja se desmonta apenas se
    // llama a print(), asi que leerla despues encuentra `null` -- y un test que
    // busca en `null` falla por el motivo equivocado.
    async function textoDeLaHoja(truncado: boolean) {
      const { unmount } = render(
        <BotonImprimir titulo="Listado" columnas={COLUMNAS}
                       traer={async () => ({ filas: filas(1, 3), truncado })} />,
      )
      fireEvent.click(screen.getByText('Imprimir'))
      const texto = await waitFor(() => {
        const hoja = document.getElementById('hoja-impresa')
        expect(hoja).not.toBeNull()
        return hoja!.textContent ?? ''
      })
      unmount()
      return texto
    }

    expect(await textoDeLaHoja(true)).toContain('corta en los primeros')
    // El control: sin corte, el aviso NO aparece. Sin esta mitad, una hoja que
    // avisara siempre pasaria igual.
    expect(await textoDeLaHoja(false)).not.toContain('corta en los primeros')
  })
})
