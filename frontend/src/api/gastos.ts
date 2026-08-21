import { api } from 'libra-ui/api-client'

/** Gastos de proveedor: lo que el proveedor entrega y se le descuenta al fletero.
 *
 *  Es el bloque que el sistema viejo llamaba COMPROBANTES PROVEEDORES, y el
 *  nombre engañaba: de los 3.347 registros del legado, 2.799 son gastos, los
 *  2.799 estan imputados a un fletero y **ninguno tiene numero de comprobante**.
 */

export type Gasto = {
  id: number
  fecha: string
  proveedor_id: number
  fletero_id: number
  comprobante: string | null
  descripcion: string
  importe: string
  anulado: boolean
}

export type FiltrosDeGasto = {
  desde?: string
  hasta?: string
  proveedor_id?: number
  fletero_id?: number
  anulado?: boolean
  /** Los usa la impresion, que repite el pedido paginando de a 1.000. */
  desplazamiento?: number
  limite?: number
}

export const gastos = {
  listar: (filtros: FiltrosDeGasto = {}) => {
    const p = new URLSearchParams()
    // `!= null` y no `if (v)`: `anulado=false` es un filtro, no una ausencia.
    for (const [k, v] of Object.entries(filtros)) {
      if (v != null && v !== '') p.set(k, String(v))
    }
    const qs = p.toString()
    return api.get<Gasto[]>(`/api/gastos${qs ? `?${qs}` : ''}`)
  },
  traer: (id: number) => api.get<Gasto>(`/api/gastos/${id}`),
  crear: (datos: unknown) => api.post<Gasto>('/api/gastos', datos),
  editar: (id: number, datos: unknown) => api.put<Gasto>(`/api/gastos/${id}`, datos),
  anular: (id: number) => api.del<Gasto>(`/api/gastos/${id}`),
}
