/** En la ficha de un cliente (Entidades → Clientes): si es titular de cartas de porte, una línea que lo dice y lleva a él
 *  (ADR-044): «Carta de porte: delegó a nosotros ✓ / emite él · consulta habilitada ✓ / pendiente».
 *
 *  Es un agregado y no el contenido de la ficha: si el pedido falla, o el cliente no es titular, no se dibuja nada. El
 *  estado de la delegación lo lee el servidor de ARCA (ticket cacheado); vale para todo titular, emita quien
 *  emita: la delegación sirve para consultar y para emitir.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BadgeEstado } from 'libra-ui/badge-estado'

import type { TitularDeEntidad } from '@/api/cartas-porte'
import { cartasPorte, etiquetaDeDelegacion, lineaDeCartaDePorte, tonoDeDelegacion } from '@/api/cartas-porte'
import { irA } from '@/navegacion'

/** El servidor contesta `null` si no es titular; cualquier otra cosa que no tenga la forma de un titular se ignora. */
const esTitular = (t: unknown): t is TitularDeEntidad =>
  typeof t === 'object' && t !== null && 'delegacion' in t && 'id' in t

export function LineaDeCartaDePorte({ terceroId }: { terceroId: number }) {
  const [titular, setTitular] = useState<TitularDeEntidad | null>(null)

  useEffect(() => {
    let vigente = true
    setTitular(null)
    cartasPorte.titularDeEntidad(terceroId)
      .then((t) => { if (vigente && esTitular(t)) setTitular(t) })
      .catch(() => {})
    return () => { vigente = false }
  }, [terceroId])

  if (!titular) return null
  return (
    <p className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm">
      <BadgeEstado tono={tonoDeDelegacion(titular.delegacion)}>
        {etiquetaDeDelegacion(titular.delegacion, titular.emite)}
      </BadgeEstado>
      <span>Carta de porte: {lineaDeCartaDePorte(titular)}</span>
      <Link to={irA.titulares(titular.id)} className="underline underline-offset-2">Ver titular</Link>
    </p>
  )
}
