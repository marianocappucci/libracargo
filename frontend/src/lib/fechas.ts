/** El adaptador que `libra-ui` pide en `@/lib/fechas`.
 *
 *  🔴 **No es un formateador nuevo: re-exporta el del producto.** La regla del
 *  ecosistema es un helper único por producto, y el de LibraCargo vive en
 *  `components/esquema-orden.ts`, al lado de `hoyEnArgentina` y de todo lo que
 *  arma la orden impresa. Escribir una segunda implementación acá sería
 *  exactamente lo que esa regla prohíbe.
 *
 *  Lo pide `libra-ui/Configuracion` (v0.47.0+) para mostrar la fecha de cada
 *  copia de backup en `dd-mm-aaaa HH:MM`. El `mtime` que devuelve el motor es
 *  un `aaaa-mm-dd HH:MM:SS` **sin zona** —reloj de pared del servidor—, así que
 *  la versión que corresponde es la que **reordena el texto**, no la que
 *  construye un `Date`: pasarlo por `Date` lo re-interpretaría como hora del
 *  navegador.
 */
export {
  formatearFecha as fecha,
  formatearFechaHoraDeTexto as fechaHora,
} from '@/components/esquema-orden'
