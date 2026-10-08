/** Un campo para elegir de una lista, que siempre se busca escribiendo.
 *
 * 🔑 **Un solo lugar decide cómo se elige.** Antes cada pantalla armaba su propio
 * `<select>` con la misma clase copiada; después este campo decidió por la
 * cantidad (≥12 opciones, buscador; menos, el nativo). Se descartó ese criterio
 * (ADR-039 del kit): el mismo campo se comportaba distinto según los datos de cada
 * cliente —con 5 choferes no buscaba, con 195 sí— y el dueño pidió que todo
 * desplegable donde se elige información («clientes, fleteros, choferes,
 * localidades») se pueda buscar por letras, sea cual sea el largo de la lista.
 *
 * Con pocas opciones se comporta como un select común: se abre con un click y se
 * elige con otro; escribir es opcional.
 */
import { SelectBuscable } from 'libra-ui/SelectBuscable'

import { Label } from '@/components/ui/label'

export type Opcion = { id: number | string; etiqueta: string }

export function Elegir({ id, etiqueta, valor, opciones, alCambiar, vacio = 'Todos',
                        deshabilitado }: {
  id: string
  etiqueta: string
  valor: string
  opciones: Opcion[]
  alCambiar: (v: string) => void
  vacio?: string
  deshabilitado?: boolean
}) {
  const todas = [{ value: '', label: vacio },
                 ...opciones.map((o) => ({ value: String(o.id), label: o.etiqueta }))]

  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <SelectBuscable
        id={id} value={valor} onChange={alCambiar} opciones={todas}
        placeholder={vacio} emptyMessage="No hay ninguno con ese nombre."
        ariaLabel={etiqueta} disabled={deshabilitado} className="w-full min-w-0"
      />
    </div>
  )
}
