/** Los archivos adjuntos de una orden: sobre todo la foto del ticket de descarga (ADR-037).
 *
 *  🔑 **También para una orden facturada**: el ticket llega después de facturar. Sólo una anulada no admite archivos.
 *  El servidor decide qué vale (JPG, PNG, WEBP, HEIC o PDF de hasta 10 MB, por el contenido y no por el nombre) y su
 *  422 se muestra tal cual; acá no se repite esa regla.
 */
import { CampoArchivo } from 'libra-ui/CampoArchivo'
import { ExternalLink, Paperclip, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { Adjunto, Orden } from '@/api/ordenes'
import { adjuntosDeOrden } from '@/api/ordenes'
import { formatearInstante } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { formatearTamanio } from '@/components/esquema-orden'
import { Label } from '@/components/ui/label'

export function AdjuntosDeOrden({ orden }: { orden: Orden }) {
  const [lista, setLista] = useState<Adjunto[]>([])
  const [cargando, setCargando] = useState(true)
  const [subiendo, setSubiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aBorrar, setABorrar] = useState<Adjunto | null>(null)
  const anulada = orden.estado === 'anulada'

  useEffect(() => {
    let vigente = true
    setCargando(true); setError(null)
    adjuntosDeOrden.listar(orden.id)
      .then((r) => { if (vigente) setLista(r) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [orden.id])

  async function subir(archivo: File | null) {
    if (!archivo) return
    setError(null); setSubiendo(true)
    try {
      const nuevo = await adjuntosDeOrden.subir(orden.id, archivo)
      setLista((actual) => [...actual, nuevo])
    } catch (e) {
      // 422: vacío, más de 10 MB o un tipo que no es imagen ni PDF. 409: la orden está anulada.
      setError(mensajeDeError(e))
    } finally {
      setSubiendo(false)
    }
  }

  async function borrar(adjunto: Adjunto) {
    setError(null)
    try {
      await adjuntosDeOrden.borrar(orden.id, adjunto.id)
      setLista((actual) => actual.filter((a) => a.id !== adjunto.id))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <section aria-label="Adjuntos" className="col-span-2 grid gap-2">
      <p className="text-muted-foreground text-xs">Adjuntos</p>

      {lista.length > 0 ? (
        <ul className="grid gap-1">
          {lista.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 rounded border px-2 py-1">
              <a href={adjuntosDeOrden.url(orden.id, a.id)} target="_blank" rel="noreferrer"
                 className="flex min-w-0 items-center gap-2 underline" title="Abrir en otra pestaña">
                <ExternalLink className="size-4 shrink-0" />
                <span className="truncate">{a.nombre}</span>
              </a>
              <span className="text-muted-foreground shrink-0 text-xs">
                {formatearTamanio(a.tamanio)} · {formatearInstante(a.created_at)}
              </span>
              <button type="button" aria-label={`Borrar ${a.nombre}`} title="Borrar"
                      className="hover:bg-accent shrink-0 rounded p-1" onClick={() => setABorrar(a)}>
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm">{cargando ? 'Cargando…' : 'Todavía no tiene archivos.'}</p>
      )}

      {anulada ? (
        <p className="text-muted-foreground text-xs">Una orden anulada no admite archivos nuevos.</p>
      ) : (
        <div className="grid gap-1">
          <Label htmlFor="adjunto-nuevo" className="flex items-center gap-1 text-xs">
            <Paperclip className="size-3" /> {subiendo ? 'Subiendo…' : 'Adjuntar archivo'}
          </Label>
          {/* `image/*` hace que el celular ofrezca sacar la foto en el momento, además de la galería y los archivos;
              sin `capture` a propósito: con él no se podría elegir un PDF. */}
          <CampoArchivo id="adjunto-nuevo" archivo={null} accept="image/*,application/pdf"
                        placeholder="Foto o PDF" disabled={subiendo} onChange={(f) => void subir(f)} />
        </div>
      )}

      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}

      <ConfirmDialog open={aBorrar !== null} onOpenChange={(v) => { if (!v) setABorrar(null) }}
                     title="Borrar el archivo" confirmLabel="Borrar"
                     description={aBorrar ? `Se borra «${aBorrar.nombre}» de la orden. No se puede deshacer.` : undefined}
                     onConfirm={() => { if (aBorrar) borrar(aBorrar) }} />
    </section>
  )
}
