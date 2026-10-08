import { api } from 'libra-ui/api-client'

/** El tarifario de referencia (ADR-038): una tarifa en pesos por tonelada para cada kilómetro, por edición.
 *
 *  Los importes viajan como TEXTO (`"23205.57"`), por la misma razón que en `ordenes.ts`. */

/** Una edición cargada: la vigente es la más nueva cuya `vigencia` no pasa de la fecha del viaje. */
export type Tarifario = {
  id: number
  /** `aaaa-mm-dd`. */
  vigencia: string
  nombre: string
  valor_estadia: string | null
  filas: number
  km_desde: number | null
  km_hasta: number | null
}

export type FilaDeTarifa = { km: number; tarifa: string }

/** La referencia para unos km. `tarifa` es `null` si el tarifario no tiene ese km: no se extrapola. */
export type Referencia = {
  tarifario_id: number
  vigencia: string
  nombre: string
  km: number
  tarifa: string | null
  valor_estadia: string | null
}

/** El porcentaje sobre la referencia del último viaje de un cliente. */
export type Sugerencia = {
  porcentaje: string
  orden_id: number
  fecha: string
  km: number
  tarifa_tonelada: string
  tarifa_referencia: string
}

/** Un 404 no es un error acá sino una respuesta: «no hay tarifario para esa fecha» o «ese cliente no tiene viaje con
 *  tarifa». Se mira el `status` y no `instanceof ApiError` para no depender de qué clase trae el cliente. */
const noHay = (e: unknown) => (e as { status?: number } | null)?.status === 404

async function opcional<T>(pedido: Promise<T>): Promise<T | null> {
  try {
    return await pedido
  } catch (e) {
    if (noHay(e)) return null
    throw e
  }
}

export const tarifario = {
  /** Las ediciones, la más nueva primero. */
  listar: () => api.get<Tarifario[]>('/api/tarifario'),
  filas: (id: number) => api.get<FilaDeTarifa[]>(`/api/tarifario/${id}/filas`),
  /** `null` si no hay tarifario para esa fecha (404). Sin `fecha`, rige el de hoy. */
  referencia: (km: number, fecha?: string) =>
    opcional(api.get<Referencia>(`/api/tarifario/referencia?km=${km}${fecha ? `&fecha=${fecha}` : ''}`)),
  /** `null` si ese cliente todavía no tiene un viaje con km y tarifa por tonelada (404). */
  sugerencia: (clienteId: number) =>
    opcional(api.get<Sugerencia>(`/api/tarifario/sugerencia?cliente_id=${clienteId}`)),
  /** Sólo admin (403 a staff). 422 con el `detail` que dice la línea del CSV; si la vigencia ya existe, la reemplaza. */
  cargar: (datos: { archivo: File; vigencia: string; nombre: string; valorEstadia?: string }) => {
    const cuerpo = new FormData()
    cuerpo.append('archivo', datos.archivo)
    cuerpo.append('vigencia', datos.vigencia)
    cuerpo.append('nombre', datos.nombre)
    if (datos.valorEstadia?.trim()) cuerpo.append('valor_estadia', datos.valorEstadia.trim())
    return api.postForm<Tarifario>('/api/tarifario', cuerpo)
  },
}
