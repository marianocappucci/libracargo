/** Mandarle la carta de porte al chofer: un enlace firmado al PDF (vence a los 7 días) por WhatsApp o copiado.
 *
 *  🔑 **El chofer no tiene usuario**: por eso el PDF no se manda como `/api/cartas-porte/:id/pdf` (pide sesión) sino
 *  como el enlace público firmado que devuelve `GET /:id/enlace`.
 *
 *  🔑 **La ventana de WhatsApp se abre ANTES de pedir el enlace**, en el mismo gesto del clic, y recién después se la
 *  manda a `wa.me`. Abrirla después del `await` es lo que bloquean los navegadores de celular —que es desde donde se
 *  usa esto— como ventana emergente. Si igual la bloquean, queda el enlace a mano.
 */
import { Copy, MessageCircle } from 'lucide-react'
import { useState } from 'react'

import type { CartaPorte, Enlace } from '@/api/cartas-porte'
import {
  cartasPorte, enlaceDeWhatsApp, formatearDiaDelInstante, nombreOCuit, textoParaCompartir,
} from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Button } from '@/components/ui/button'

export function CompartirCartaDePorte({ carta, origen, destino }: {
  carta: CartaPorte
  /** Cómo se llama el lugar de carga y de descarga en el mensaje; por omisión, el nombre o CUIT que informa ARCA. */
  origen?: string
  destino?: string
}) {
  const [enlace, setEnlace] = useState<Enlace | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [paraAbrir, setParaAbrir] = useState<string | null>(null)

  if (carta.id === null || !carta.tiene_pdf) return null
  const id = carta.id

  const pedir = async (): Promise<Enlace> => {
    const e = enlace ?? await cartasPorte.enlace(id)
    setEnlace(e)
    return e
  }

  async function compartir() {
    setError(null); setAviso(null); setParaAbrir(null); setOcupado(true)
    const ventana = window.open('', '_blank')
    if (ventana) ventana.opener = null
    try {
      const e = await pedir()
      const texto = textoParaCompartir(
        carta, origen ?? nombreOCuit(carta.origen), destino ?? nombreOCuit(carta.destino), e.url)
      const wa = enlaceDeWhatsApp(texto)
      if (ventana) ventana.location.href = wa
      else setParaAbrir(wa)
    } catch (err) {
      ventana?.close()
      setError(mensajeDeError(err))
    } finally {
      setOcupado(false)
    }
  }

  async function copiar() {
    setError(null); setAviso(null); setParaAbrir(null); setOcupado(true)
    try {
      const e = await pedir()
      try {
        await navigator.clipboard.writeText(e.url)
        setAviso('Enlace copiado.')
      } catch {
        // Sin permiso del portapapeles: el enlace queda a la vista, abajo, para copiarlo a mano.
        setAviso('No se pudo copiar solo: copialo de acá abajo.')
      }
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={compartir} disabled={ocupado}>
          <MessageCircle className="size-4" /> Compartir por WhatsApp
        </Button>
        <Button type="button" variant="outline" onClick={copiar} disabled={ocupado}>
          <Copy className="size-4" /> Copiar enlace
        </Button>
      </div>
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      {aviso && <p role="status" className="text-sm">{aviso}</p>}
      {paraAbrir && (
        <p role="status" className="text-sm">
          El navegador no dejó abrir WhatsApp.{' '}
          <a href={paraAbrir} target="_blank" rel="noreferrer" className="underline">Abrir WhatsApp</a>
        </p>
      )}
      {enlace && (
        <div className="grid gap-1 text-xs">
          <input readOnly value={enlace.url} aria-label="Enlace al PDF" onFocus={(e) => e.currentTarget.select()}
                 className="border-input bg-background w-full rounded-md border px-2 py-1 font-mono" />
          <span className="text-muted-foreground">
            Sin usuario ni contraseña; vence el {formatearDiaDelInstante(enlace.vence)}.
          </span>
        </div>
      )}
    </div>
  )
}
