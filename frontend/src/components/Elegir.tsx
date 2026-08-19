/** Un campo para elegir de una lista, con buscador cuando hace falta.
 *
 * 🔑 **Un solo lugar decide cuándo hay buscador.** Antes cada pantalla armaba su
 * propio `<select>` con la misma clase copiada, y agregar el buscador significó
 * tocarlas de a una — y quedaron dos sin tocar. Acá la regla es una: si la lista
 * pasa de `DESDE_CUANTAS`, se busca por teclado.
 *
 * El corte no es arbitrario: con menos de una docena el desplegable nativo del
 * navegador es más rápido —se abre y se ve entera— y un buscador para cuatro
 * opciones es un paso de más. Con 186 fleteros o 195 choferes, encontrar uno sin
 * filtro es recorrer la lista a ojo.
 */
import { SelectBuscable } from 'libra-ui/SelectBuscable'

import { Label } from '@/components/ui/label'

export type Opcion = { id: number | string; etiqueta: string }

/** A partir de acá, con buscador. Medido contra las listas reales de Suitrans:
 *  roles (3), medios de pago (4) y acciones (3) quedan como `<select>`;
 *  terceros (276), choferes (195), localidades (121) y vehículos (180), no. */
export const DESDE_CUANTAS = 12

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
  const conBuscador = opciones.length >= DESDE_CUANTAS
  const todas = [{ value: '', label: vacio },
                 ...opciones.map((o) => ({ value: String(o.id), label: o.etiqueta }))]

  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      {conBuscador ? (
        <SelectBuscable
          id={id} value={valor} onChange={alCambiar} opciones={todas}
          placeholder={vacio} emptyMessage="No hay ninguno con ese nombre."
          ariaLabel={etiqueta} disabled={deshabilitado} className="w-full min-w-0"
        />
      ) : (
        // `w-full min-w-0`: un `<select>` mide lo que mide su opción más larga y
        // un ítem de grid tiene `min-width: auto`, así que sin esto la celda se
        // estira y se monta sobre la de al lado.
        <select
          id={id} className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
          value={valor} disabled={deshabilitado}
          onChange={(e) => alCambiar(e.target.value)}
        >
          {todas.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )}
    </div>
  )
}
