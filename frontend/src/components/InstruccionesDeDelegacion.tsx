/** Cómo delegarnos `wscpe`, para mandárselo al titular (ADR-044).
 *
 *  🔑 **Nada está escrito a mano.** El CUIT del representante y el alias del computador fiscal salen del certificado de
 *  «CTG y Carta de Porte» cargado (`GET /titulares/instrucciones`): en producción el alias no es el de homologación (el
 *  que termina en «homo»), y el CUIT es el de quien firma el certificado, que cambia de una instancia a otra. Sin
 *  certificado no hay instrucciones: se dice dónde cargarlo y no se inventa un texto con datos que no son.
 */
import { Copy, MessageCircle } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { InstruccionesDeDelegacion as Instrucciones } from '@/api/cartas-porte'
import { cartasPorte, enlaceDeWhatsApp, formatearCuit, textoDeInstrucciones } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Button } from '@/components/ui/button'

export function InstruccionesDeDelegacion({ titular }: {
  /** Si se pasa, el texto dice «en representación de …»; si no, «del titular». */
  titular?: string
}) {
  const [datos, setDatos] = useState<Instrucciones | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    cartasPorte.instruccionesDeDelegacion()
      .then((r) => { if (vigente) setDatos(r) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [])

  const texto = datos?.disponible ? textoDeInstrucciones(datos, titular) : null

  async function copiar() {
    if (!texto) return
    setAviso(null)
    try {
      await navigator.clipboard.writeText(texto)
      setAviso('Instrucciones copiadas.')
    } catch {
      // Sin permiso del portapapeles: el texto queda a la vista, arriba, para copiarlo a mano.
      setAviso('No se pudo copiar solo: copialo del recuadro.')
    }
  }

  function compartir() {
    if (!texto) return
    setAviso(null)
    // Sin `await` antes: es el mismo gesto del clic, así que el navegador no lo toma por una ventana emergente.
    window.open(enlaceDeWhatsApp(texto), '_blank', 'noopener')
  }

  return (
    <section aria-label="Instrucciones de delegación" className="grid gap-2 rounded-md border p-4">
      <div>
        <h2 className="text-sm font-semibold">Cómo delegarnos la emisión</h2>
        <p className="text-muted-foreground text-xs">
          Para mandárselas al cliente que quiere que emitamos sus cartas de porte. Él las hace con su clave fiscal.
        </p>
      </div>
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      {datos === null && !error && <p className="text-muted-foreground text-sm">Leyendo el certificado…</p>}
      {datos && !datos.disponible && (
        <p role="status" className="text-muted-foreground text-sm">{datos.motivo}</p>
      )}
      {datos?.disponible && texto && (
        <>
          {datos.ambiente === 'homologacion' && (
            <p role="status" className="rounded-md border border-amber-600/50 bg-amber-500/10 p-3 text-sm font-medium">
              Es el certificado de homologación (de prueba). Para delegar en producción hace falta cargar el
              certificado de producción en Configuración / ARCA.
            </p>
          )}
          <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground text-xs">CUIT del representante</dt>
              <dd className="font-medium tabular-nums">{formatearCuit(datos.cuit_representante)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Alias del computador fiscal</dt>
              <dd className="font-mono font-medium">{datos.alias}</dd>
            </div>
          </dl>
          <pre aria-label="Texto de las instrucciones"
               className="bg-muted/40 overflow-x-auto rounded-md border p-3 text-sm whitespace-pre-wrap">{texto}</pre>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={copiar}>
              <Copy className="size-4" /> Copiar
            </Button>
            <Button type="button" variant="outline" onClick={compartir}>
              <MessageCircle className="size-4" /> Compartir por WhatsApp
            </Button>
          </div>
          {aviso && <p role="status" className="text-sm">{aviso}</p>}
        </>
      )}
    </section>
  )
}
