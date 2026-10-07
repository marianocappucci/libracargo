/** Los íconos de identidad de LibraCargo: el catálogo de la familia (`libra-ui/iconos-identidad`, ADR-035) con la excepción de este producto.
 *
 *  🔑 **Sólo este producto usa `iconosDe('libracargo')`**: acá el camión (`Truck`) es de los fleteros y Proveedores lleva `Store`. La
 *  excepción vive en el kit (`ICONOS_POR_PRODUCTO`), no en este archivo. Menú, títulos y pestañas toman el ícono de acá y nunca de
 *  `ICONOS.proveedores`, que es `Truck` en el resto de la familia.
 */
import { iconosDe } from 'libra-ui/iconos-identidad'

export const ICONOS_LC = iconosDe('libracargo')
