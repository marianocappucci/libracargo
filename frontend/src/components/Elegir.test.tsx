import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('libra-ui/api-client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { DESDE_CUANTAS, Elegir } = await import('./Elegir')

function lista(cuantas: number) {
  return Array.from({ length: cuantas }, (_, i) => ({ id: i + 1, etiqueta: `Opción ${i + 1}` }))
}

describe('Elegir', () => {
  it('con pocas opciones usa el desplegable del navegador', () => {
    // Con cuatro opciones el nativo se abre y se ve entero: un buscador ahí es
    // un paso de más.
    render(<Elegir id="e" etiqueta="Medio" valor="" opciones={lista(4)}
                   alCambiar={() => {}} />)
    expect(screen.getByLabelText('Medio').tagName).toBe('SELECT')
  })

  it('con muchas opciones aparece el buscador', () => {
    // El control con buscador no es un <select>: es un botón que abre un panel
    // con un campo de texto. Distinguirlos por el tag es lo que hace que este
    // test signifique algo.
    render(<Elegir id="e" etiqueta="Cliente" valor="" opciones={lista(DESDE_CUANTAS)}
                   alCambiar={() => {}} />)
    expect(screen.getByLabelText('Cliente').tagName).not.toBe('SELECT')
  })

  it('el umbral es el que dice la constante, no uno inventado', () => {
    // El control del test de arriba: una opción menos y vuelve al nativo. Sin
    // esto, "muchas opciones" podría ser cualquier número.
    render(<Elegir id="e" etiqueta="Justo abajo" valor=""
                   opciones={lista(DESDE_CUANTAS - 1)} alCambiar={() => {}} />)
    expect(screen.getByLabelText('Justo abajo').tagName).toBe('SELECT')
  })

  it('la opción vacía se puede nombrar: no siempre dice "Todos"', () => {
    render(<Elegir id="e" etiqueta="Tercero" valor="" opciones={lista(3)}
                   vacio="Ninguno (gasto general)" alCambiar={() => {}} />)
    expect(screen.getByText('Ninguno (gasto general)')).toBeInTheDocument()
  })

  it('elegir avisa con el id como texto', () => {
    // Los ids viajan como string porque asi los toma la URL y el formulario;
    // devolver un number obligaria a convertir en cada pantalla.
    const alCambiar = vi.fn()
    render(<Elegir id="e" etiqueta="Cuenta" valor="" opciones={lista(3)}
                   alCambiar={alCambiar} />)
    fireEvent.change(screen.getByLabelText('Cuenta'), { target: { value: '2' } })
    expect(alCambiar).toHaveBeenCalledWith('2')
  })
})
