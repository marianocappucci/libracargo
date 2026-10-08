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

/** Lo que el servidor leyó del archivo, antes de guardar (ADR-039). Lo que el archivo no dice viene `null`: un CSV no
 *  trae vigencia, nombre ni valor de estadía, y un PDF raro puede no traer alguno. */
export type VistaPreviaDeTarifario = {
  /** `aaaa-mm-dd`. */
  vigencia: string | null
  nombre: string | null
  valor_estadia: string | null
  filas: number
  km_desde: number | null
  km_hasta: number | null
  /** Unos pocos km con su tarifa, para comparar a ojo contra el PDF. */
  muestra: FilaDeTarifa[]
  /** Ya hay una edición con esa vigencia: cargar la reemplaza entera. */
  reemplaza: boolean
}

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
  /** Sólo admin. Lee el PDF (o el CSV) y dice lo que cargaría, **sin guardar nada**. 422 con el `detail` si no se pudo
   *  leer con seguridad: se muestra tal cual. */
  previsualizar: (archivo: File) => {
    const cuerpo = new FormData()
    cuerpo.append('archivo', archivo)
    return api.postForm<VistaPreviaDeTarifario>('/api/tarifario/previsualizar', cuerpo)
  },
  /** Sólo admin (403 a staff). El archivo es el PDF tal como se descarga (o un CSV `km;tarifa`); `vigencia`, `nombre` y
   *  `valorEstadia` son opcionales y, si vienen, mandan sobre lo leído del PDF. Un CSV sin vigencia da 422 («indicá la
   *  vigencia»). 422 con el `detail`; si la vigencia ya existe, la reemplaza entera. */
  cargar: (datos: { archivo: File; vigencia?: string; nombre?: string; valorEstadia?: string }) => {
    const cuerpo = new FormData()
    cuerpo.append('archivo', datos.archivo)
    if (datos.vigencia?.trim()) cuerpo.append('vigencia', datos.vigencia.trim())
    if (datos.nombre?.trim()) cuerpo.append('nombre', datos.nombre.trim())
    if (datos.valorEstadia?.trim()) cuerpo.append('valor_estadia', datos.valorEstadia.trim())
    return api.postForm<Tarifario>('/api/tarifario', cuerpo)
  },
}
