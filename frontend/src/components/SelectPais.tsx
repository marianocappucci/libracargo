/** El desplegable de país (ADR-042): Argentina y el resto del Mercosur, de `/api/geo/paises`.
 *
 *  `<select>` nativo y no el de Radix: son seis opciones fijas y se usa dentro de diálogos, donde el de Radix monta su
 *  propio portal y pelea por el foco. Con `conTodos` suma «Todos los países» al principio (para buscar, no para cargar).
 *
 *  Si la lista no llega (o llega vacía) queda sólo Argentina: no poder elegir otro país no puede volverse no poder cargar.
 */
import { useEffect, useState } from 'react'

import { paises as traerPaises, PAIS_POR_OMISION, TODOS_LOS_PAISES, type Pais } from '@/api/geo'
import { Label } from '@/components/ui/label'

const SOLO_ARGENTINA: Pais[] = [{ id: PAIS_POR_OMISION, nombre: 'Argentina' }]

export function SelectPais({ id, etiqueta = 'País', valor, alCambiar, conTodos = false }: {
  id: string
  etiqueta?: string
  /** El código ISO elegido, o `todos` si `conTodos`. */
  valor: string
  alCambiar: (codigo: string) => void
  conTodos?: boolean
}) {
  const [lista, setLista] = useState<Pais[]>(SOLO_ARGENTINA)

  useEffect(() => {
    let vigente = true
    traerPaises()
      .then((ps) => { if (vigente && Array.isArray(ps) && ps.length > 0) setLista(ps) })
      .catch(() => { /* queda Argentina */ })
    return () => { vigente = false }
  }, [])

  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      {/* select-cerrado: los seis países del Mercosur (catálogo cerrado del sistema, no datos de la empresa): no hay nada que buscar */}
      <select
        id={id} className="h-9 rounded-md border px-3 text-sm"
        value={valor} onChange={(e) => alCambiar(e.target.value)}
      >
        {conTodos && <option value={TODOS_LOS_PAISES}>Todos los países</option>}
        {lista.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
      </select>
    </div>
  )
}
