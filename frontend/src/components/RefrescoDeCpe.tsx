/** El interruptor «Refrescar solas las cartas de porte abiertas» (ADR-051), en Configuración / ARCA.
 *
 *  Un cron del host corre cada tanto `scripts/refrescar_cartas_porte.py`, que vuelve a consultar a ARCA las cartas abiertas
 *  (sin kilos de descarga y sin estado final) hasta que informe la descarga. **Sólo consulta: no emite ni anula nada**,
 *  y por eso es un interruptor aparte del de la emisión real. Apagado por defecto y sólo para administradores.
 *
 *  Prender no alcanza si el cron no está instalado: la pantalla dice cuándo corrió por última vez, que es lo que
 *  distingue «apagado» de «prendido pero nadie lo ejecuta».
 */
import { useEffect, useState } from 'react'

import type { EstadoDeRefresco } from '@/api/cartas-porte'
import { cartasPorte, formatearInstante } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useAuth } from '@/context/AuthContext'

export function RefrescoDeCpe() {
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const [estado, setEstado] = useState<EstadoDeRefresco | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    if (!esAdmin) return
    let vigente = true
    cartasPorte.estadoDeRefresco()
      .then((r) => { if (vigente) setEstado(r) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [esAdmin])

  if (!esAdmin) return null

  async function cambiar(habilitado: boolean) {
    setError(null); setGuardando(true)
    try {
      setEstado(await cartasPorte.habilitarRefresco(habilitado))
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <section aria-label="Refresco de cartas de porte" className="grid gap-3 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="grid gap-1">
          <Label htmlFor="cpe-refresco" className="text-base font-semibold">
            Refrescar solas las cartas de porte abiertas
          </Label>
          <p className="text-muted-foreground text-sm">
            Vuelve a preguntarle a ARCA por el estado de cada carta abierta, hasta que informe la descarga. Sólo
            consulta: no emite ni anula nada.
          </p>
        </div>
        <Switch id="cpe-refresco" checked={estado?.habilitado ?? false}
                disabled={estado === null || guardando}
                onCheckedChange={(v) => { void cambiar(v) }} />
      </div>

      {estado?.es_demo && (
        <p className="text-muted-foreground text-sm">
          Esta es una instancia de demostración: no se conecta con ARCA, así que el refresco no corre.
        </p>
      )}
      {estado && !estado.es_demo && estado.ambiente === null && (
        <p className="text-muted-foreground text-sm">
          Todavía no hay un certificado de «CTG y Carta de Porte» cargado: sin él no hay nada que consultar.
        </p>
      )}
      {estado?.habilitado && !estado.es_demo && (
        <p role="status" className="text-sm">
          {estado.ultima_corrida
            ? <>Última corrida: <strong>{formatearInstante(estado.ultima_corrida)}</strong>
                {estado.resumen && ` · ${estado.resumen}`}.</>
            : 'Todavía no corrió. Si pasó más de una hora desde que lo prendiste, falta la tarea programada del servidor.'}
        </p>
      )}
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
    </section>
  )
}
