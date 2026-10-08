/** El mini diálogo para cargar un **paraje**: un lugar real que no está en el catálogo de Argentina ni del Mercosur (ADR-041).
 *  Se dibuja sólo mientras está abierto: quien lo usa lo monta al abrirlo y lo desmonta al cerrarlo.
 *
 *  Pide nombre, país (Argentina por omisión) y provincia, y la provincia es obligatoria: es lo que ubica el lugar cuando no
 *  hay código censal que lo haga. La provincia se elige entre las del país elegido (ADR-042). Lo usan el selector de origen y destino de la orden (cargar lo que se escribió), Configuración → Localidades
 *  («Cargar paraje») y la acción «Marcar como paraje» de una fila sin vincular.
 *
 *  Sin `<form>`: este diálogo se monta, por árbol de React, adentro del formulario de la orden, y un `submit` de un
 *  formulario anidado en un portal sube por el árbol y dispararía el de la orden. Enter se atiende en el campo.
 */
import { useEffect, useState } from 'react'
import { SelectBuscable } from 'libra-ui/SelectBuscable'

import { PAIS_POR_OMISION, provincias as traerProvincias, type Provincia } from '@/api/geo'
import { mensajeDeError } from '@/components/AbmMaestro'
import { SelectPais } from '@/components/SelectPais'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function DialogoParaje({
  alCerrar, titulo = 'Cargar paraje', nombreInicial = '', provinciaInicial = '', paisInicial = PAIS_POR_OMISION,
  confirmar, textoConfirmar = 'Cargar paraje', nombreFijo = false,
}: {
  alCerrar: () => void
  titulo?: string
  nombreInicial?: string
  provinciaInicial?: string | null
  /** El país de partida (ISO). Por omisión, Argentina. */
  paisInicial?: string
  /** Hace lo que corresponde con el paraje. Si falla, el mensaje del servidor se muestra tal cual en el diálogo. */
  confirmar: (datos: { nombre: string; provincia: string; pais: string }) => Promise<void>
  textoConfirmar?: string
  /** El nombre no se toca: sólo falta la provincia («Marcar como paraje» una que ya existe). */
  nombreFijo?: boolean
}) {
  const [nombre, setNombre] = useState(nombreInicial)
  const [pais, setPais] = useState(paisInicial)
  const [provincia, setProvincia] = useState('')
  const [lista, setLista] = useState<Provincia[] | null>(null)
  const [sinCatalogo, setSinCatalogo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  // Las provincias son las del país elegido: al cambiarlo se vuelven a pedir (cacheadas por país).
  useEffect(() => {
    let vigente = true
    setLista(null)
    setSinCatalogo(false)
    traerProvincias(pais)
      .then((ps) => { if (vigente) setLista(ps) })
      // Sin catálogo de provincias el campo cae a texto: no poder elegir no puede volverse no poder cargar.
      .catch(() => { if (vigente) setSinCatalogo(true) })
    return () => { vigente = false }
  }, [pais])

  // La provincia de partida sólo vale si es una del catálogo: una abreviatura cargada a mano («Bs As») dejaría el
  // desplegable mostrando una cosa y el estado guardando otra. Llega cuando llega el catálogo, y no pisa lo que la persona
  // ya eligió. El diálogo se monta al abrirse (quien lo usa lo dibuja sólo mientras está abierto), así que arranca de cero.
  // Sólo vale para el país de partida: si se cambia de país, la provincia de partida ya no corresponde.
  useEffect(() => {
    if (pais !== paisInicial) return
    const parte = provinciaInicial ?? ''
    if (sinCatalogo || (lista?.some((p) => p.nombre === parte) ?? false)) setProvincia((actual) => actual || parte)
  }, [provinciaInicial, paisInicial, pais, lista, sinCatalogo])

  function cambiarPais(nuevo: string) {
    setPais(nuevo)
    // La provincia elegida era de otro país.
    setProvincia('')
  }

  async function guardar() {
    const n = nombre.trim()
    if (!n) { setError('Escribí el nombre del lugar.'); return }
    if (!provincia.trim()) { setError('Elegí la provincia: un paraje la lleva, es lo que lo ubica.'); return }
    setError(null)
    setGuardando(true)
    try {
      await confirmar({ nombre: n, provincia: provincia.trim(), pais })
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
            Un paraje es un lugar que no está en el catálogo de Argentina ni del Mercosur (un campo, una planta, un paraje).
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
          <SelectPais id="paraje-pais" valor={pais} alCambiar={cambiarPais} />
          <div className="grid gap-1">
            <Label htmlFor="paraje-provincia">Provincia</Label>
            {sinCatalogo ? (
              <Input id="paraje-provincia" value={provincia} onChange={(e) => setProvincia(e.target.value)} />
            ) : (
              // Se busca escribiendo (ADR-039 del kit): 24 provincias argentinas. El selector del kit no es el de Radix, así que no
              // pelea por el foco dentro del diálogo.
              <SelectBuscable
                id="paraje-provincia" required ariaLabel="Provincia" placeholder="Elegí la provincia…"
                emptyMessage="No hay ninguna provincia con ese nombre."
                value={provincia} onChange={setProvincia}
                opciones={(lista ?? []).map((p) => ({ value: p.nombre, label: p.nombre }))}
              />
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
