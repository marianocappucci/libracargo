// El icono del título es el que el sidebar le da a esa misma pantalla.
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una
// pantalla se rompa —ninguna se rompe con el icono equivocado— sino que
// **vuelvan a divergir**: eso no se ve en ningún render, se ve cruzando el mapa
// de navegación contra cada pantalla, y sólo si alguien se acuerda de cruzar.
// El motor del cruce vive en `libra-ui/auditoria-de-titulos`, uno para los ocho
// productos, y tiene sus propios tests allá.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarTitulos, describirDesajustes } from 'libra-ui/auditoria-de-titulos'

const SRC = join(process.cwd(), 'src')

describe('el icono del título sale del sidebar', () => {
  it('🔴 ninguna pantalla usa un icono distinto al de su entrada del menú', () => {
    const { distinto } = auditarTitulos(SRC, 'libracargo')
    expect(describirDesajustes(distinto)).toEqual([])
  })

  it('🔴 ninguna pantalla del menú tiene el título sin icono', () => {
    const { sinIcono } = auditarTitulos(SRC, 'libracargo')
    expect(describirDesajustes(sinIcono)).toEqual([])
  })

  it('🔴 el control — el guard midió algo', () => {
    // Sin esto, los dos casos de arriba pasarían en verde si el parser dejara
    // de encontrar el Layout, el router o las pantallas: dos listas vacías
    // comparadas contra dos listas vacías. Es exactamente la forma en que este
    // guard falló mientras se escribía.
    const { rutasDelNav, pantallas, conIcono, sinTitulo } = auditarTitulos(SRC, 'libracargo')
    // Nueve: «Pre facturas» y «Comprobantes de proveedores» dejaron de ser
    // entradas del menú y pasaron a ser parte de «Comprobantes».
    expect(rutasDelNav).toBeGreaterThanOrEqual(9)
    // Once: las tres rutas de «Pre facturas» y `/gastos` ya no cuelgan de una entrada propia del
    // menú sino de «Comprobantes», que es una sola pantalla con pestañas.
    expect(pantallas).toBeGreaterThanOrEqual(11)
    expect(conIcono).toBeGreaterThan(0)
    // 🔑 `conIcono` NO es igual a `pantallas`: hay dos envoltorios de pantallas
    // que rinde `libra-ui`, y el título —con su icono— lo pone ella. Acá no hay
    // ninguno, y está bien: el que había era un duplicado.
    //
    // `/configuracion` se sumó el 2026-08-30, al pasar a `createConfiguracion`:
    // antes este producto dibujaba su propia barra de pestañas con las clases
    // de `tabs.tsx` copiadas a mano, y su propio `TituloPantalla`. Se veía casi
    // igual y era otro mecanismo.
    expect(sinTitulo.map((d) => d.ruta)).toEqual(['/configuracion', '/usuarios'])
  })
})
