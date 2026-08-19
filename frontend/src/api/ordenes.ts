import { api } from 'libra-ui/api-client'

export type Orden = {
  id: number
  fecha: string
  cliente_id: number
  origen_id: number
  destino_id: number
  fletero_id: number | null
  chofer_id: number | null
  vehiculo_id: number | null
  tipo_carga_id: number | null
  razon_social_id: number | null
  remito: string | null
  cantidad: string | null
  unidad: string | null
  // Los importes vienen como STRING y no como number: son `Numeric` de
  // PostgreSQL y `Decimal` de Python, y pasarlos por `number` los mete en un
  // float binario -- que es exactamente el defecto del legado. Se muestran y se
  // comparan como texto; quien tenga que sumarlos, que lo haga en el servidor.
  tarifa: string
  alicuota_iva: string
  iva: string
  total: string
  comision: string
  estado: 'pendiente' | 'facturada' | 'anulada'
  comprobante_id: number | null
  observaciones: string | null
  /** Lo que el legado tenia en  cuando no era un numero
   *  ("140 bultos", "varios"): se conserva tal cual, sin interpretarlo. */
  cantidad_legado: string | null
  /** El id de la fila en el sistema viejo. Sirve para rastrear una orden
   *  migrada hasta su origen cuando el cliente pregunta por una. */
  origen_legado: string | null
}

/** Los doce filtros del listado. `undefined` es "sin filtrar", y para
 *  `facturada` eso es distinto de `false`. */
export type Filtros = {
  desde?: string
  hasta?: string
  cliente_id?: number
  fletero_id?: number
  chofer_id?: number
  vehiculo_id?: number
  origen_id?: number
  destino_id?: number
  tipo_carga_id?: number
  razon_social_id?: number
  estado?: string
  facturada?: boolean
  q?: string
  /** Paginación. La grilla no la usa —muestra la primera página— pero la hoja
   *  impresa sí: pide de a mil hasta traer el listado entero. */
  limite?: number
  desplazamiento?: number
}

export function consulta(filtros: Filtros): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(filtros)) {
    // `!= null` a propósito: descarta null y undefined, pero **conserva
    // `false` y `0`**. Con un `if (v)` el filtro `facturada=false` --el que en
    // el legado era la pantalla de facturar pendientes-- se perderia entero.
    if (v != null && v !== '') p.set(k, String(v))
  }
  return p.toString()
}

export const ordenes = {
  listar: (filtros: Filtros = {}) => {
    const qs = consulta(filtros)
    return api.get<Orden[]>(`/api/ordenes${qs ? `?${qs}` : ''}`)
  },
  crear: (datos: unknown) => api.post<Orden>('/api/ordenes', datos),
  editar: (id: number, datos: unknown) => api.put<Orden>(`/api/ordenes/${id}`, datos),
  anular: (id: number) => api.del<Orden>(`/api/ordenes/${id}`),
}

export type Opcion = { id: number; etiqueta: string }

/** Las listas para los selects del formulario y de los filtros.
 *  Se piden **sólo los activos**: un maestro dado de baja no tiene que poder
 *  elegirse en una orden nueva, aunque siga existiendo en las viejas. */
export async function cargarOpciones() {
  const [terceros, localidades, choferes, vehiculos, tipos, razones] = await Promise.all([
    api.get<Record<string, unknown>[]>('/api/terceros?activo=true'),
    api.get<Record<string, unknown>[]>('/api/localidades?activo=true'),
    api.get<Record<string, unknown>[]>('/api/choferes?activo=true'),
    api.get<Record<string, unknown>[]>('/api/vehiculos?activo=true'),
    api.get<Record<string, unknown>[]>('/api/tipos-carga?activo=true'),
    api.get<Record<string, unknown>[]>('/api/razones-sociales?activo=true'),
  ])
  const mapear = (filas: Record<string, unknown>[], campo: string): Opcion[] =>
    filas.map((f) => ({ id: f.id as number, etiqueta: String(f[campo] ?? '') }))
  return {
    clientes: mapear(terceros.filter((t) => t.es_cliente), 'razon_social'),
    fleteros: mapear(terceros.filter((t) => t.es_fletero), 'razon_social'),
    localidades: mapear(localidades, 'nombre'),
    choferes: mapear(choferes, 'nombre'),
    vehiculos: mapear(vehiculos, 'patente_chasis'),
    tipos: mapear(tipos, 'nombre'),
    razones: mapear(razones, 'nombre'),
  }
}

export type Opciones = Awaited<ReturnType<typeof cargarOpciones>>
