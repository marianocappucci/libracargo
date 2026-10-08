import { api } from 'libra-ui/api-client'

/** El catálogo de provincias y localidades, servido por LibraCore.
 *
 *  Es de **sólo lectura**: las 24 provincias y 4.027 localidades de Argentina, más el resto del Mercosur (Brasil, Chile,
 *  Paraguay, Bolivia y Uruguay, de GeoNames; ADR-042), que viajan adentro del paquete, no en la base. El maestro editable
 *  de localidades —el que se usa como origen y destino de una orden— sigue siendo del producto, porque hay lugares reales
 *  que no están en ningún recurso oficial.
 */

export type Pais = { id: string; nombre: string }
export type Provincia = { id: string; nombre: string; pais?: string }
export type LocalidadDelCatalogo = {
  id: string
  nombre: string
  provincia_id: string
  provincia: string
  /** ISO de dos letras. Si el servidor no lo trae, es Argentina. */
  pais?: string
}

/** El país por omisión: lo que se asume cuando no se dice (y lo que el servidor asume sin `pais`). */
export const PAIS_POR_OMISION = 'AR'

/** Los nombres de los países que se ven en las etiquetas («Nueva Palmira — Colonia (Uruguay)»). Está acá y no sólo en
 *  `/api/geo/paises` porque una etiqueta se arma de forma sincrónica; un código que no esté se muestra tal cual. */
const NOMBRES_DE_PAIS: Record<string, string> = {
  AR: 'Argentina', BR: 'Brasil', CL: 'Chile', PY: 'Paraguay', BO: 'Bolivia', UY: 'Uruguay',
}

/** El valor de `?pais=` que busca en todos los países a la vez. */
export const TODOS_LOS_PAISES = 'todos'

export const nombreDePais = (codigo: string): string => NOMBRES_DE_PAIS[codigo] ?? codigo

let paisesEnMemoria: Promise<Pais[]> | null = null

/** Los países del catálogo, pedidos una sola vez por sesión (la promesa, no el resultado: ver `provincias`). */
export function paises(): Promise<Pais[]> {
  paisesEnMemoria ??= api.get<Pais[]>('/api/geo/paises')
  return paisesEnMemoria
}

const provinciasEnMemoria = new Map<string, Promise<Provincia[]>>()

/** Las divisiones de un país (por omisión, las 24 provincias de Argentina), pedidas una sola vez por sesión.
 *
 *  Se cachea la **promesa** y no el resultado: si dos campos del mismo
 *  formulario las piden a la vez —y pasa, el alta de un tercero tiene
 *  provincia y localidad—, con el resultado cacheado saldrían dos pedidos.
 *  Para Argentina el pedido es el de siempre, sin `pais`.
 */
export function provincias(pais: string = PAIS_POR_OMISION): Promise<Provincia[]> {
  let pedido = provinciasEnMemoria.get(pais)
  if (!pedido) {
    pedido = api.get<Provincia[]>(
      pais === PAIS_POR_OMISION ? '/api/geo/provincias' : `/api/geo/provincias?pais=${encodeURIComponent(pais)}`,
    )
    provinciasEnMemoria.set(pais, pedido)
  }
  return pedido
}

const localidadesPorProvincia = new Map<string, Promise<LocalidadDelCatalogo[]>>()

/** Las localidades de una provincia, completas y cacheadas.
 *
 *  Se traen todas las de la provincia en un pedido en vez de consultar por
 *  cada tecla: la más grande es Buenos Aires y el filtrado por teclado lo hace
 *  `SelectBuscable` en memoria. Un pedido por pulsación haría que el
 *  desplegable dependa de la latencia para algo que ya está resuelto del lado
 *  del navegador.
 */
export function localidadesDe(provinciaId: string): Promise<LocalidadDelCatalogo[]> {
  if (!provinciaId) return Promise.resolve([])
  let pedido = localidadesPorProvincia.get(provinciaId)
  if (!pedido) {
    pedido = api.get<LocalidadDelCatalogo[]>(
      `/api/geo/localidades?provincia_id=${encodeURIComponent(provinciaId)}&limite=5000`,
    )
    localidadesPorProvincia.set(provinciaId, pedido)
  }
  return pedido
}

/** Sólo para los tests: vacía las cachés. */
export function _olvidarCache(): void {
  paisesEnMemoria = null
  provinciasEnMemoria.clear()
  localidadesPorProvincia.clear()
}

/** Busca en el catálogo por nombre (sin tildes ni mayúsculas, lo resuelve el servidor). Es lo que usan «Vincular al
 *  catálogo» y «Agregar del catálogo» de Configuración → Localidades: ahí se busca escribiendo, no se baja una provincia
 *  entera. Sin caché: cada consulta es distinta. `pais` es un código ISO o `todos` (Argentina y el resto del Mercosur). */
export function buscarEnElCatalogo(q: string, limite = 20, pais: string = TODOS_LOS_PAISES): Promise<LocalidadDelCatalogo[]> {
  return api.get<LocalidadDelCatalogo[]>(
    `/api/geo/localidades?q=${encodeURIComponent(q)}&limite=${limite}&pais=${encodeURIComponent(pais)}`,
  )
}
