// Atajos para los tests de los selectores con búsqueda (`libra-ui/SelectBuscable`, ADR-039 del kit).
//
// El selector es un `<input role="combobox">`: sus opciones sólo existen en el DOM mientras la lista está abierta, así que un test que
// antes hacía `fireEvent.change(select, …)` o leía los `<option>` pasa por acá. Misma idea que `elegirEnBuscable` / `opcionesDe` de
// `libra-ui/test/helpers-pantallas`, pero con `fireEvent`: este producto no usa `@testing-library/user-event`.
import { fireEvent, screen, within } from '@testing-library/react'

/** Abre la lista (un solo click) y elige la opción. Espera a que la opción exista: sirve cuando las opciones llegan de la red. */
export async function elegirEnBuscable(combobox: HTMLElement, texto: string | RegExp) {
  fireEvent.click(combobox)
  fireEvent.click(await screen.findByRole('option', { name: texto }))
}

/** Las etiquetas de la lista: abre, lee y cierra con Escape. */
export function opcionesDe(combobox: HTMLElement): string[] {
  fireEvent.click(combobox)
  const textos = within(screen.getByRole('listbox')).queryAllByRole('option').map((o) => o.textContent ?? '')
  fireEvent.keyDown(combobox, { key: 'Escape' })
  return textos
}
