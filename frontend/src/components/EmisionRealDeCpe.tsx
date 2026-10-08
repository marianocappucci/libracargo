/** El interruptor «Emitir Cartas de Porte reales» (ADR-043): lo prende un administrador, en Configuración / ARCA.
 *
 *  🔑 **Apagado por defecto y sólo para administradores.** Emitir una carta de porte en producción es un acto fiscal
 *  que no se deshace (sólo se anula), así que la puerta la abre una persona con rol de administración y queda en la
 *  auditoría. En homologación no hace falta: es de prueba y se puede emitir siempre.
 *
 *  Prender pide una confirmación; apagar no: apagar es siempre el lado seguro.
 */
import { useEffect, useState } from 'react'

import type { EstadoDeEmision } from '@/api/cartas-porte'
import { cartasPorte } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useAuth } from '@/context/AuthContext'

export function EmisionRealDeCpe() {
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const [estado, setEstado] = useState<EstadoDeEmision | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [porPrender, setPorPrender] = useState(false)

  useEffect(() => {
    if (!esAdmin) return
    let vigente = true
    cartasPorte.estadoDeEmision()
      .then((r) => { if (vigente) setEstado(r) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [esAdmin])

  if (!esAdmin) return null

  async function cambiar(habilitada: boolean) {
    setError(null); setGuardando(true)
    try {
      setEstado(await cartasPorte.habilitarEmision(habilitada))
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <section aria-label="Emisión de cartas de porte" className="grid gap-3 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="grid gap-1">
          <Label htmlFor="cpe-emision-real" className="text-base font-semibold">Emitir Cartas de Porte reales</Label>
          <p className="text-muted-foreground text-sm">
            Cartas de Porte Electrónicas (CPE) emitidas desde la orden de carga, a nombre de quien le delegó la
            emisión a este certificado en ARCA.
          </p>
        </div>
        <Switch id="cpe-emision-real" checked={estado?.habilitada ?? false}
                disabled={estado === null || guardando}
                onCheckedChange={(v) => { if (v) setPorPrender(true); else void cambiar(false) }} />
      </div>

      <p role="note" className="rounded border border-amber-600/50 bg-amber-500/10 p-3 text-sm">
        <strong>Con esto prendido, el sistema emite Cartas de Porte REALES ante ARCA.</strong> Son documentos fiscales y
        de circulación: quedan registradas a nombre del titular y sólo se pueden anular. Apagado, nadie puede emitir
        en producción.
      </p>

      {estado?.ambiente === 'homologacion' && (
        <p className="text-muted-foreground text-sm">
          El certificado cargado es de <strong>homologación</strong>: se puede emitir de prueba (sin efecto fiscal)
          aunque este interruptor esté apagado.
        </p>
      )}
      {estado?.ambiente === null && (
        <p className="text-muted-foreground text-sm">
          Todavía no hay un certificado de «CTG y Carta de Porte» cargado: sin él no se puede emitir.
        </p>
      )}
      {estado?.ambiente === 'produccion' && (
        <p role="status" className="text-sm font-medium">
          {estado.habilitada ? 'La emisión real está prendida.' : 'La emisión real está apagada.'}
        </p>
      )}
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}

      <ConfirmDialog
        open={porPrender} onOpenChange={setPorPrender}
        title="¿Prender la emisión de Cartas de Porte reales?"
        description="A partir de ahora cualquier usuario del sistema puede emitir Cartas de Porte reales ante ARCA, a nombre de los titulares que delegaron. Quedan registradas y sólo se pueden anular."
        confirmLabel="Prender"
        onConfirm={() => { setPorPrender(false); void cambiar(true) }} />
    </section>
  )
}
