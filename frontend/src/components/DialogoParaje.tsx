/** El mini diálogo para cargar un **paraje**: un lugar real que no está en el catálogo de Argentina (ADR-041).
 *  Se dibuja sólo mientras está abierto: quien lo usa lo monta al abrirlo y lo desmonta al cerrarlo.
 *
 *  Pide dos cosas, nombre y provincia, y la provincia es obligatoria: es lo que ubica el lugar cuando no hay código censal
 *  que lo haga. Lo usan el selector de origen y destino de la orden (cargar lo que se escribió), Configuración → Localidades
 *  («Cargar paraje») y la acción «Marcar como paraje» de una fila sin vincular.
 *
 *  Sin `<form>`: este diálogo se monta, por árbol de React, adentro del formulario de la orden, y un `submit` de un
 *  formulario anidado en un portal sube por el árbol y dispararía el de la orden. Enter se atiende en el campo.
 */
import { useEffect, useState } from 'react'

import { provincias as traerProvincias, type Provincia } from '@/api/geo'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function DialogoParaje({
  alCerrar, titulo = 'Cargar paraje', nombreInicial = '', provinciaInicial = '',
  confirmar, textoConfirmar = 'Cargar paraje', nombreFijo = false,
}: {
  alCerrar: () => void
  titulo?: string
  nombreInicial?: string
  provinciaInicial?: string | null
  /** Hace lo que corresponde con el paraje. Si falla, el mensaje del servidor se muestra tal cual en el diálogo. */
  confirmar: (datos: { nombre: string; provincia: string }) => Promise<void>
  textoConfirmar?: string
  /** El nombre no se toca: sólo falta la provincia («Marcar como paraje» una que ya existe). */
  nombreFijo?: boolean
}) {
  const [nombre, setNombre] = useState(nombreInicial)
  const [provincia, setProvincia] = useState('')
  const [lista, setLista] = useState<Provincia[] | null>(null)
  const [sinCatalogo, setSinCatalogo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    let vigente = true
    traerProvincias()
      .then((ps) => { if (vigente) setLista(ps) })
      // Sin catálogo de provincias el campo cae a texto: no poder elegir no puede volverse no poder cargar.
      .catch(() => { if (vigente) setSinCatalogo(true) })
    return () => { vigente = false }
  }, [])

  // La provincia de partida sólo vale si es una del catálogo: una abreviatura cargada a mano («Bs As») dejaría el
  // desplegable mostrando una cosa y el estado guardando otra. Llega cuando llega el catálogo, y no pisa lo que la persona
  // ya eligió. El diálogo se monta al abrirse (quien lo usa lo dibuja sólo mientras está abierto), así que arranca de cero.
  useEffect(() => {
    const parte = provinciaInicial ?? ''
    if (sinCatalogo || (lista?.some((p) => p.nombre === parte) ?? false)) setProvincia((actual) => actual || parte)
  }, [provinciaInicial, lista, sinCatalogo])

  async function guardar() {
    const n = nombre.trim()
    if (!n) { setError('Escribí el nombre del lugar.'); return }
    if (!provincia.trim()) { setError('Elegí la provincia: un paraje la lleva, es lo que lo ubica.'); return }
    setError(null)
    setGuardando(true)
    try {
      await confirmar({ nombre: n, provincia: provincia.trim() })
    } catch (e) {
      // El 409 («ya existe…») y el 422 se muestran como los dice el servidor.
      setError(mensajeDeError(e))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v) alCerrar() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{titulo}</DialogTitle>
          <DialogDescription>
            Un paraje es un lugar que no está en el catálogo de Argentina (un campo, una planta, un paraje).
            Lleva provincia para poder ubicarlo.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1">
            <Label htmlFor="paraje-nombre">Nombre del paraje</Label>
            <Input
              id="paraje-nombre" value={nombre} autoComplete="off" readOnly={nombreFijo}
              onChange={(e) => setNombre(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void guardar() } }}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="paraje-provincia">Provincia</Label>
            {sinCatalogo ? (
              <Input id="paraje-provincia" value={provincia} onChange={(e) => setProvincia(e.target.value)} />
            ) : (
              // `<select>` nativo: son 24 opciones fijas dentro de un diálogo, y el de Radix pelea ahí por el foco.
              <select
                id="paraje-provincia" className="h-9 rounded-md border px-3 text-sm" required
                value={provincia} onChange={(e) => setProvincia(e.target.value)}
              >
                <option value="">Elegí la provincia…</option>
                {(lista ?? []).map((p) => <option key={p.id} value={p.nombre}>{p.nombre}</option>)}
              </select>
            )}
          </div>
          {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={alCerrar}>Cancelar</Button>
          <Button type="button" onClick={() => void guardar()} disabled={guardando}>{textoConfirmar}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
