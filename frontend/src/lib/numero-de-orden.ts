/** Cómo se muestra el id de una orden de carga, en un equipo con nodo o sin él (ADR-056 del backend, libraedge ADR-021).
 *
 *  🔑 **Una orden que se carga en el nodo sin conexión nace con un id NEGATIVO** (`-3`) y lo conserva hasta que el central le da el
 *  suyo. Mostrarlo tal cual lo dibujaba como si fuera un número real: «Orden Nº 000000-3» en el título, «#-3» en la lista de
 *  órdenes de un comprobante, «Nº 000000-3» en la hoja impresa. Una orden provisoria **no tiene** número definitivo: se dice así
 *  («provisoria») y se la distingue con una `P-` y el valor absoluto, que no se confunde con la orden 3 del central.
 *
 *  La regla «id negativo = todavía no subió» es la del kit (`esReservaProvisoria`, ADR-094): se reusa y no se reescribe. Su etiqueta
 *  («Sin subir al central») es `EtiquetaDeOrdenDelNodo`. Con ids positivos nada cambia: todo se muestra como siempre.
 */
import { esReservaProvisoria } from 'libra-ui/reservas-del-nodo'

/** ¿Es una orden dada en el nodo que todavía no tiene su id definitivo? */
export const esOrdenProvisoria = (id: number | string | null | undefined): boolean => esReservaProvisoria(id)

/** `00000041`, o `P-3` si es provisoria. */
export function numeroDeOrden(id: number): string {
  return esOrdenProvisoria(id) ? `P-${Math.abs(id)}` : String(id).padStart(8, '0')
}

/** El número sin ceros, para una lista o una referencia corta: `41`, o `P-3` si es provisoria. */
export function numeroCorto(id: number): string {
  return esOrdenProvisoria(id) ? `P-${Math.abs(id)}` : String(id)
}

/** El título de una orden: «Orden Nº 00000041», o «Orden provisoria P-3». */
export function tituloDeOrden(id: number): string {
  return esOrdenProvisoria(id) ? `Orden provisoria ${numeroCorto(id)}` : `Orden Nº ${numeroDeOrden(id)}`
}

/** Lo que va impreso en la hoja de la orden: «Nº 00000041», o «Provisoria P-3». */
export function numeroImpreso(id: number): string {
  return esOrdenProvisoria(id) ? `Provisoria ${numeroCorto(id)}` : `Nº ${numeroDeOrden(id)}`
}
