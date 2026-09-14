import '@testing-library/jest-dom/vitest'

/**
 * jsdom trae `document.createRange()` pero su `Range` NO implementa
 * `getBoundingClientRect`. `libra-ui/data-table` lo usa para medir el ancho
 * del título "Acciones" -- el texto va alineado a la derecha y `scrollWidth`
 * no mide ese lado --, así que cualquier tabla CON columna de acciones revienta
 * con `rango.getBoundingClientRect is not a function`.
 *
 * No había aparecido antes porque ningún test de este repo montaba una tabla
 * con columna de acciones del kit compartido. Apareció al sumar el primer test
 * de `Usuarios` (adopción del router de `libraauth`, ADR-018) -- el mismo
 * hallazgo que documenta `libra-ui/test/setup.ts`.
 *
 * 🟡 Devuelve ceros (no hay layout que medir en jsdom) y el componente ya
 * trata el 0 como "no medí nada": lo que queda invisible acá es que una
 * columna se corte de verdad, y eso se mide en un navegador.
 */
if (typeof Range !== 'undefined' && !Range.prototype.getBoundingClientRect) {
  const vacio = {
    x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0,
    toJSON: () => ({}),
  } as DOMRect
  Range.prototype.getBoundingClientRect = () => vacio
  Range.prototype.getClientRects = () => ({
    length: 0,
    item: () => null,
    [Symbol.iterator]: function* () {},
  }) as unknown as DOMRectList
}
