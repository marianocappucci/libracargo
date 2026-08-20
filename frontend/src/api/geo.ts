import { api } from 'libra-ui/api-client'

/** El catálogo de provincias y localidades, servido por LibraCore.
 *
 *  Es de **sólo lectura**: 24 provincias y 4.027 localidades que viajan
 *  adentro del paquete, no en la base. El maestro editable de localidades
 *  —el que se usa como origen y destino de una orden— sigue siendo del
 *  producto, porque hay lugares reales que no están en ningún recurso oficial.
 */

export type Provincia = { id: string; nombre: string }
export type LocalidadDelCatalogo = {
  id: string
  nombre: string
  provincia_id: string
  provincia: string
}

let provinciasEnMemoria: Promise<Provincia[]> | null = null

/** Las 24, pedidas una sola vez por sesión.
 *
 *  Se cachea la **promesa** y no el resultado: si dos campos del mismo
 *  formulario las piden a la vez —y pasa, el alta de un tercero tiene
 *  provincia y localidad—, con el resultado cacheado saldrían dos pedidos.
 */
export function provincias(): Promise<Provincia[]> {
  provinciasEnMemoria ??= api.get<Provincia[]>('/api/geo/provincias')
  return provinciasEnMemoria
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

/** Sólo para los tests: vacía las dos cachés. */
export function _olvidarCache(): void {
  provinciasEnMemoria = null
  localidadesPorProvincia.clear()
}
