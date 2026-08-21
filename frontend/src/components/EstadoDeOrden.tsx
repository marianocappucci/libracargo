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
import { Badge } from '@/components/ui/badge'

/** `anulada` es la que hay que poder saltear de un vistazo — una orden anulada
 *  sigue en el listado (no se borra, ver ADR) y confundirla con una viva es el
 *  error caro. Las otras dos son estados normales del circuito. */
export function EstadoDeOrden({ estado }: { estado: string }) {
  return (
    <Badge variant={estado === 'anulada' ? 'destructive' : 'secondary'}>
      {estado}
    </Badge>
  )
}
