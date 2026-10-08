import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('libra-ui/api-client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { Elegir } = await import('./Elegir')

function lista(cuantas: number) {
  return Array.from({ length: cuantas }, (_, i) => ({ id: i + 1, etiqueta: `Opción ${i + 1}` }))
}

describe('Elegir', () => {
  it.each([3, 11, 12, 200])('con %i opciones se busca escribiendo, no es un <select> del navegador', (cuantas) => {
    // ADR-039 del kit: el criterio es el origen de las opciones, no su cantidad. Antes
    // la lista corta (menos de 12) era un <select> nativo y la larga un buscador: el
    // mismo campo se comportaba distinto según los datos de cada cliente.
    render(<Elegir id="e" etiqueta="Cliente" valor="" opciones={lista(cuantas)}
                   alCambiar={() => {}} />)
    const campo = screen.getByLabelText('Cliente')
    expect(campo.tagName).toBe('INPUT')
    expect(campo).toHaveAttribute('role', 'combobox')
  })

  it('escribir filtra la lista, aunque tenga pocas opciones', () => {
    render(<Elegir id="e" etiqueta="Medio" valor="" opciones={[
      { id: 1, etiqueta: 'Efectivo' }, { id: 2, etiqueta: 'Transferencia' }, { id: 3, etiqueta: 'Cheque' },
    ]} alCambiar={() => {}} />)
    fireEvent.change(screen.getByLabelText('Medio'), { target: { value: 'trans' } })
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Transferencia'])
  })

  it('la opción vacía se puede nombrar: no siempre dice "Todos"', () => {
    render(<Elegir id="e" etiqueta="Tercero" valor="" opciones={lista(3)}
                   vacio="Ninguno (gasto general)" alCambiar={() => {}} />)
    expect(screen.getByLabelText('Tercero')).toHaveAttribute('placeholder', 'Ninguno (gasto general)')
  })

  it('elegir avisa con el id como texto', () => {
    // Los ids viajan como string porque asi los toma la URL y el formulario;
    // devolver un number obligaria a convertir en cada pantalla.
    const alCambiar = vi.fn()
    render(<Elegir id="e" etiqueta="Cuenta" valor="" opciones={lista(3)}
                   alCambiar={alCambiar} />)
    fireEvent.click(screen.getByLabelText('Cuenta'))
    fireEvent.click(screen.getByRole('option', { name: 'Opción 2' }))
    expect(alCambiar).toHaveBeenCalledWith('2')
  })

  it('elegir "Todos" devuelve la cadena vacía', () => {
    const alCambiar = vi.fn()
    render(<Elegir id="e" etiqueta="Cuenta" valor="2" opciones={lista(3)} alCambiar={alCambiar} />)
    fireEvent.click(screen.getByLabelText('Cuenta'))
    fireEvent.click(screen.getByRole('option', { name: 'Todos' }))
    expect(alCambiar).toHaveBeenCalledWith('')
  })
})
