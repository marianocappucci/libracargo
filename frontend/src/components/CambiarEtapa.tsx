/** Cambiar la etapa de una orden sin abrir el formulario de edición.
 *
 *  🔑 **Usa `PUT /etapa` y no el `PUT` de la orden**, porque la etapa es operativa y también vale para una
 *  facturada: el formulario de edición, en cambio, da 409 si la orden ya está facturada. Y el ticket de
 *  descarga suele llegar después de facturar.
 */
import { useState } from 'react'

import type { Etapa, Orden } from '@/api/ordenes'
import { ETAPAS, etapaSiguiente, ordenes } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { EtapaDeOrden } from '@/components/EstadoDeOrden'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

export function CambiarEtapa({ orden, alCambiar }: {
  orden: Orden
  /** Se llama con la orden que devolvió el servidor. */
  alCambiar: (orden: Orden) => void
}) {
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const siguiente = etapaSiguiente(orden.etapa)
  const anulada = orden.estado === 'anulada'

  async function mover(etapa: Etapa) {
    if (etapa === orden.etapa) return
    setError(null); setGuardando(true)
    try {
      alCambiar(await ordenes.cambiarEtapa(orden.id, etapa))
    } catch (e) {
      // El 409 de «la orden está anulada» llega con su motivo.
      setError(mensajeDeError(e))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <section aria-label="Etapa" className="col-span-2 grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-xs">Etapa</span>
        <EtapaDeOrden orden={orden} />
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="grid gap-1">
          <Label htmlFor="cambiar-etapa" className="text-xs">Etapa del viaje</Label>
          <select id="cambiar-etapa" className="h-9 rounded-md border px-2 text-sm"
                  value={orden.etapa} disabled={anulada || guardando}
                  onChange={(e) => mover(e.target.value as Etapa)}>
            {ETAPAS.map((e) => <option key={e.valor} value={e.valor}>{e.etiqueta}</option>)}
          </select>
        </div>
        <Button type="button" variant="outline" disabled={anulada || guardando || siguiente === null}
                onClick={() => siguiente && mover(siguiente)}>
          Siguiente etapa
          {siguiente && ` · ${ETAPAS.find((e) => e.valor === siguiente)?.etiqueta}`}
        </Button>
      </div>
      {anulada && <p className="text-muted-foreground text-xs">Una orden anulada no cambia de etapa.</p>}
      {orden.estado === 'facturada' && (
        <p className="text-muted-foreground text-xs">
          Está liquidada (facturada): la etapa del viaje se puede seguir moviendo.
        </p>
      )}
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
    </section>
  )
}
