import { api } from 'libra-ui/api-client'
import type { TonoEstado } from 'libra-ui/badge-estado'

/** Por dónde va el viaje (ADR-037). **No es el estado de facturación**: una orden facturada sigue teniendo etapa. */
export const VALORES_DE_ETAPA = ['asignada', 'cargada', 'en_viaje', 'descargada', 'cerrada'] as const
export type Etapa = (typeof VALORES_DE_ETAPA)[number]

/** En el orden del viaje: «Siguiente etapa» es la que sigue en esta lista. */
export const ETAPAS: { valor: Etapa; etiqueta: string }[] = [
  { valor: 'asignada', etiqueta: 'Asignada' },
  { valor: 'cargada', etiqueta: 'Cargada' },
  { valor: 'en_viaje', etiqueta: 'En viaje' },
  { valor: 'descargada', etiqueta: 'Descargada' },
  { valor: 'cerrada', etiqueta: 'Cerrada' },
]

/** La etapa siguiente en el viaje, o `null` si ya es la última. */
export function etapaSiguiente(etapa: Etapa): Etapa | null {
  const i = VALORES_DE_ETAPA.indexOf(etapa)
  return VALORES_DE_ETAPA[i + 1] ?? null
}

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
  etapa: Etapa
  /** Kilos enteros de la pesada al cargar y del ticket al descargar; `null` mientras no se saben. */
  kg_bruto_carga: number | null
  kg_tara_carga: number | null
  kg_neto_carga: number | null
  kg_bruto_descarga: number | null
  kg_tara_descarga: number | null
  kg_neto_descarga: number | null
  comprobante_id: number | null
  observaciones: string | null
  /** Lo que el legado tenia en  cuando no era un numero
   *  ("140 bultos", "varios"): se conserva tal cual, sin interpretarlo. */
  cantidad_legado: string | null
  /** El id de la fila en el sistema viejo. Sirve para rastrear una orden
   *  migrada hasta su origen cuando el cliente pregunta por una. */
  origen_legado: string | null
}

/** Los filtros del listado. `undefined` es "sin filtrar", y para
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
  estado?: string
  etapa?: Etapa
  facturada?: boolean
  /** Reservada en una pre factura abierta. `false` son las que se pueden incluir en una pre factura nueva. */
  reservada?: boolean
  /** Sólo las reservadas en esa pre factura. */
  pre_factura_id?: number
  q?: string
  /** Paginación. La grilla no la usa —muestra la primera página— pero la hoja
   *  impresa sí: pide de a mil hasta traer el listado entero. */
  limite?: number
  desplazamiento?: number
}

/** Lo que se muestra como etapa de una orden: la anulada y la facturada mandan sobre la etapa del viaje.
 *
 *  «Liquidada» es «facturada» (decisión del humano, ADR-037): el estado de facturación no cambia, sólo cómo se lee. */
export function etapaMostrada(o: Pick<Orden, 'estado' | 'etapa'>): { clave: string; etiqueta: string; tono: TonoEstado } {
  if (o.estado === 'anulada') return { clave: 'anulada', etiqueta: 'Anulada', tono: 'negativo' }
  if (o.estado === 'facturada') return { clave: 'liquidada', etiqueta: 'Liquidada', tono: 'ok' }
  const tono: Record<Etapa, TonoEstado> = {
    asignada: 'neutro', cargada: 'curso', en_viaje: 'curso', descargada: 'atencion', cerrada: 'ok',
  }
  return {
    clave: o.etapa, tono: tono[o.etapa],
    etiqueta: ETAPAS.find((e) => e.valor === o.etapa)?.etiqueta ?? o.etapa,
  }
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
  /** Vale también para una orden facturada (la etapa es operativa); 409 si está anulada. */
  cambiarEtapa: (id: number, etapa: Etapa) => api.put<Orden>(`/api/ordenes/${id}/etapa`, { etapa }),
}

/** Un archivo adjunto a la orden (la foto del ticket de descarga, un remito escaneado), sin su contenido. */
export type Adjunto = {
  id: number
  orden_id: number
  nombre: string
  tipo_contenido: string
  tamanio: number
  created_at: string
}

export const adjuntosDeOrden = {
  listar: (ordenId: number) => api.get<Adjunto[]>(`/api/ordenes/${ordenId}/adjuntos`),
  /** 422 si está vacío, pasa de 10 MB o no es JPG/PNG/WEBP/HEIC/PDF (lo decide el servidor por el contenido);
   *  409 si la orden está anulada. Vale también para una facturada. */
  subir: (ordenId: number, archivo: File) => {
    const cuerpo = new FormData()
    cuerpo.append('archivo', archivo)
    return api.postForm<Adjunto>(`/api/ordenes/${ordenId}/adjuntos`, cuerpo)
  },
  borrar: (ordenId: number, id: number) => api.del<void>(`/api/ordenes/${ordenId}/adjuntos/${id}`),
  /** El archivo: se abre en otra pestaña, la sesión viaja en la cookie. */
  url: (ordenId: number, id: number) => `/api/ordenes/${ordenId}/adjuntos/${id}`,
}

/** `detalle` es un texto secundario (el CUIT de un tercero): `Elegir` muestra sólo la etiqueta; los campos que buscan
 *  escribiendo (Cuenta corriente) lo ven atenuado al lado del nombre, y también entra en la búsqueda. */
export type Opcion = { id: number; etiqueta: string; detalle?: string }

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
  const [terceros, localidades, choferes, vehiculos, tipos] = await Promise.all([
    traerTodo('terceros'),
    traerTodo('localidades'),
    traerTodo('choferes'),
    traerTodo('vehiculos'),
    traerTodo('tipos-carga'),
  ])
  const mapear = (filas: Record<string, unknown>[], campo: string, detalle?: string): Opcion[] =>
    filas.map((f) => {
      const extra = detalle ? f[detalle] : undefined
      return {
        id: f.id as number, etiqueta: String(f[campo] ?? ''),
        // Sólo si lo hay: un tercero sin CUIT no lleva `detalle: ''`.
        ...(extra ? { detalle: String(extra) } : {}),
      }
    })
  // De los terceros, el CUIT va como `detalle`: la cuenta corriente busca por nombre o por CUIT.
  return {
    clientes: mapear(terceros.filter((t) => t.es_cliente), 'razon_social', 'cuit'),
    fleteros: mapear(terceros.filter((t) => t.es_fletero), 'razon_social', 'cuit'),
    // 🔴 Faltaba, y con ella la cuenta corriente de proveedores era
    // inalcanzable: la pantalla ofrecía el rol "Proveedor" y mostraba la lista
    // de CLIENTES. Los 15 proveedores de la instancia del cliente son
    // proveedor-puro, así que ninguno se podía elegir.
    proveedores: mapear(terceros.filter((t) => t.es_proveedor), 'razon_social', 'cuit'),
    // Todos, sin repetir. Un tercero con dos roles aparecía dos veces en los
    // lugares que concatenaban las listas —caja y el filtro de los reportes—,
    // y elegir cualquiera de las dos filas hacía lo mismo.
    terceros: mapear(terceros, 'razon_social', 'cuit'),
    localidades: mapear(localidades, 'nombre'),
    choferes: mapear(choferes, 'nombre'),
    vehiculos: mapear(vehiculos, 'patente_chasis'),
    tipos: mapear(tipos, 'nombre'),
  }
}

export type Opciones = Awaited<ReturnType<typeof cargarOpciones>>
