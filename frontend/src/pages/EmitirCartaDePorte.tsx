/** «Emitir carta de porte» de una orden, en su propia página (ADR-043; página y no diálogo desde el 2026-10-09).
 *
 *  Llega desde el detalle de la orden (`irA.emitirCartaDePorte`). Cuelga de «Cartas de porte» en el menú, así que el
 *  título lleva su icono. El asistente es `components/EmitirCartaDePorte`; acá sólo se trae la orden por su id (un enlace
 *  pegado o un F5 tienen que andar) y se decide a dónde se vuelve: a la orden, que es de donde se vino.
 */
import { INDICADORES } from 'libra-ui/iconos-indicador'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import type { Orden } from '@/api/ordenes'
import { ordenes } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { EmitirCartaDePorte } from '@/components/EmitirCartaDePorte'
import { Button } from '@/components/ui/button'
import { irA } from '@/navegacion'

export default function EmitirCartaDePortePagina() {
  const { ordenId } = useParams()
  const id = Number(ordenId)
  const valido = Number.isInteger(id) && id > 0
  const navigate = useNavigate()
  const [orden, setOrden] = useState<Orden | null>(null)
  const [error, setError] = useState<string | null>(valido ? null : 'La dirección no tiene un número de orden válido.')

  useEffect(() => {
    if (!valido) return
    let vigente = true
    ordenes.traer(id)
      .then((o) => { if (vigente) setOrden(o) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [id, valido])

  const numero = valido ? ` · Orden Nº ${String(id).padStart(8, '0')}` : ''
  const volver = valido ? irA.orden(id) : '/ordenes'

  let cuerpo: React.ReactNode
  if (error) {
    cuerpo = <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>
  } else if (!orden) {
    cuerpo = <p className="text-muted-foreground text-sm">Cargando la orden…</p>
  } else if (orden.estado === 'anulada') {
    // Una orden anulada no viaja: el detalle ya no ofrece el botón, y un enlace viejo no la emite.
    cuerpo = <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">
      La orden está anulada: no se le emite carta de porte.
    </p>
  } else {
    cuerpo = <EmitirCartaDePorte orden={orden} alSalir={() => navigate(volver)} />
  }

  return (
    <div className="mx-auto grid max-w-4xl gap-4">
      <TituloPantalla icono={INDICADORES.cartasDePorte}>{`Emitir carta de porte${numero}`}</TituloPantalla>
      {cuerpo}
      {(error || orden?.estado === 'anulada') && (
        <div><Button asChild variant="outline"><Link to={volver}>Volver a la orden</Link></Button></div>
      )}
    </div>
  )
}
