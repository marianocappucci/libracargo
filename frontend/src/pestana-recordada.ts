/** La última pestaña de «Transporte» que se abrió, recordada en este navegador (ADR-045).
 *
 *  Pedido del dueño (2026-10-10): al entrar a Transporte desde el menú se abre la pestaña que se estaba usando, no siempre Fleteros. Es
 *  una preferencia de quien mira la pantalla —no del usuario ni de la instancia—, así que va en `localStorage`, como el modo
 *  claro/oscuro del kit (`libra-ui/modo`: misma forma, clave propia, valor validado y `try/catch` en lectura y escritura).
 *
 *  🔑 **Sólo vale cuando la URL no dice nada.** Un enlace, una redirección vieja o el botón de atrás traen `?pestana=` y manda la URL;
 *  esto sólo decide la ruta pelada (`/transporte`, que es lo que lleva el menú).
 *
 *  Sin almacenamiento (modo privado, bloqueado, cuota) o con un valor que ya no es una pestaña, es Fleteros: la pantalla nunca se rompe
 *  por esto.
 */
import { pestanaDeTransporte, type PestanaDeTransporte } from '@/navegacion'

/** Con el prefijo del producto: el almacenamiento es del origen, y la suite comparte dominio en algunos entornos. */
export const CLAVE_DE_PESTANA_DE_TRANSPORTE = 'libracargo.transporte.pestana'

/** La pestaña recordada, o Fleteros si no hay, no es una pestaña existente o el acceso al almacenamiento lanza. */
export function leerPestanaDeTransporte(): PestanaDeTransporte {
  try {
    return pestanaDeTransporte(window.localStorage.getItem(CLAVE_DE_PESTANA_DE_TRANSPORTE))
  } catch {
    return 'fleteros'
  }
}

/** Recuerda la pestaña. Si no se puede guardar, no pasa nada: la próxima vez abre en Fleteros. */
export function recordarPestanaDeTransporte(pestana: PestanaDeTransporte): void {
  try {
    window.localStorage.setItem(CLAVE_DE_PESTANA_DE_TRANSPORTE, pestana)
  } catch {
    // Sin almacenamiento no se recuerda; la pantalla anda igual.
  }
}
