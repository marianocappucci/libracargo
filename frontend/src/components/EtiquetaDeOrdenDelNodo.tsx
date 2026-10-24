/** «Sin subir al central»: la etiqueta de una orden que se cargó en el nodo y todavía no tiene su id definitivo (id negativo).
 *
 *  El texto y su ayuda son los del kit (`libra-ui/reservas-del-nodo`, ADR-094), los mismos que lleva una reserva de LibraClub en
 *  la misma situación. Con una orden del central (id positivo) no dibuja nada. Azul, `curso`: está en camino, no es un problema.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'
import { AYUDA_SIN_SUBIR, ETIQUETA_SIN_SUBIR } from 'libra-ui/reservas-del-nodo'
import { CloudUpload } from 'lucide-react'

import { esOrdenProvisoria } from '@/lib/numero-de-orden'

export function EtiquetaDeOrdenDelNodo({ id, className }: { id: number; className?: string }) {
  if (!esOrdenProvisoria(id)) return null
  return (
    <BadgeEstado tono="curso" title={AYUDA_SIN_SUBIR} data-slot="etiqueta-orden-sin-subir" className={className}>
      <CloudUpload className="size-3.5" aria-hidden="true" />{ETIQUETA_SIN_SUBIR}
    </BadgeEstado>
  )
}
