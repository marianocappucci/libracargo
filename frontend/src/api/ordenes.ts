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
  // Por id y no buscando en la grilla: el enlace profundo tiene que abrir
  // la orden aunque los filtros puestos no la incluyan.
  traer: (id: number) => api.get<Orden>(`/api/ordenes/${id}`),
  crear: (datos: unknown) => api.post<Orden>('/api/ordenes', datos),
  editar: (id: number, datos: unknown) => api.put<Orden>(`/api/ordenes/${id}`, datos),
  anular: (id: number) => api.del<Orden>(`/api/ordenes/${id}`),
}

export type Opcion = { id: number; etiqueta: string }

/** Trae **todas** las filas de un maestro, paginando.
 *
 *  🔴 El listado de la API tiene tope: 200 por omisión y 1.000 como máximo. Un
 *  solo pedido devolvía las primeras 200 y nadie se enteraba — sobre la
 *  instancia del cliente, con **276 terceros activos**, eso dejaba 76 afuera de
 *  todos los selects del sistema. Un select al que le falta un cliente no falla:
 *  simplemente no lo encontrás, y parece que el cliente no existe.
 *
 *  Se pagina y no se sube el número: cualquier tope elegido a mano se vuelve a
 *  cruzar, y la próxima vez tampoco va a avisar.
 */
async function traerTodo(recurso: string): Promise<Record<string, unknown>[]> {
  const PAGINA = 1000  // el máximo que acepta la API
  const filas: Record<string, unknown>[] = []
  for (let desplazamiento = 0; ; desplazamiento += PAGINA) {
    const pagina = await api.get<Record<string, unknown>[]>(
      `/api/${recurso}?activo=true&limite=${PAGINA}&desplazamiento=${desplazamiento}`,
    )
    filas.push(...pagina)
    // Una página corta es la última. Si vino completa puede haber más, aunque
    // el total sea múltiplo exacto: ahí la vuelta de más devuelve vacío.
    if (pagina.length < PAGINA) return filas
  }
}

/** Las listas para los selects del formulario y de los filtros.
 *  Se piden **sólo los activos**: un maestro dado de baja no tiene que poder
 *  elegirse en una orden nueva, aunque siga existiendo en las viejas. */
export async function cargarOpciones() {
  const [terceros, localidades, choferes, vehiculos, tipos, razones] = await Promise.all([
    traerTodo('terceros'),
    traerTodo('localidades'),
    traerTodo('choferes'),
    traerTodo('vehiculos'),
    traerTodo('tipos-carga'),
    traerTodo('razones-sociales'),
  ])
  const mapear = (filas: Record<string, unknown>[], campo: string): Opcion[] =>
    filas.map((f) => ({ id: f.id as number, etiqueta: String(f[campo] ?? '') }))
  return {
    clientes: mapear(terceros.filter((t) => t.es_cliente), 'razon_social'),
    fleteros: mapear(terceros.filter((t) => t.es_fletero), 'razon_social'),
    // 🔴 Faltaba, y con ella la cuenta corriente de proveedores era
    // inalcanzable: la pantalla ofrecía el rol "Proveedor" y mostraba la lista
    // de CLIENTES. Los 15 proveedores de la instancia del cliente son
    // proveedor-puro, así que ninguno se podía elegir.
    proveedores: mapear(terceros.filter((t) => t.es_proveedor), 'razon_social'),
    // Todos, sin repetir. Un tercero con dos roles aparecía dos veces en los
    // lugares que concatenaban las listas —caja y el filtro de los reportes—,
    // y elegir cualquiera de las dos filas hacía lo mismo.
    terceros: mapear(terceros, 'razon_social'),
    localidades: mapear(localidades, 'nombre'),
    choferes: mapear(choferes, 'nombre'),
    vehiculos: mapear(vehiculos, 'patente_chasis'),
    tipos: mapear(tipos, 'nombre'),
    razones: mapear(razones, 'nombre'),
  }
}

export type Opciones = Awaited<ReturnType<typeof cargarOpciones>>
