/** La píldora del estado de una orden, en un solo lugar.
 *
 * 🔑 **Estaba escrita en `Ordenes` y faltaba en el dashboard**, que mostraba el
 * estado como texto pelado — el único de las siete tablas de la aplicación que
 * no usaba `Badge`. Copiar el ternario a la segunda pantalla las dejaba libres
 * de divergir otra vez; esto es el mismo componente en las dos.
 *
 * Los tres estados salen de `EstadoOrden` del backend: `pendiente`,
 * `facturada` y `anulada`.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'

import type { Orden } from '@/api/ordenes'
import { etapaMostrada } from '@/api/ordenes'

/** `anulada` es la que hay que poder saltear de un vistazo — una orden anulada
 *  sigue en el listado (no se borra, ver ADR) y confundirla con una viva es el
 *  error caro. Las otras dos son estados normales del circuito. */
export function EstadoDeOrden({ estado }: { estado: string }) {
  return (
    <BadgeEstado tono={estado === 'anulada' ? 'negativo' : 'neutro'}>
      {estado}
    </BadgeEstado>
  )
}

/** La etapa del viaje de una orden. Una facturada se lee «Liquidada» y una anulada «Anulada»: el estado de
 *  facturación sigue siendo otro dato (`EstadoDeOrden`), esto es cómo se muestra el viaje. */
export function EtapaDeOrden({ orden }: { orden: Pick<Orden, 'estado' | 'etapa'> }) {
  const { clave, etiqueta, tono } = etapaMostrada(orden)
  return <BadgeEstado tono={tono} data-etapa={clave}>{etiqueta}</BadgeEstado>
}
