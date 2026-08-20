import { api } from 'libra-ui/api-client'

/** Lo que devuelven los seis ABM. Los campos propios de cada uno se agregan
 *  con una intersección en su pantalla: acá está lo que comparten. */
export type Maestro = {
  id: number
  activo: boolean
  [campo: string]: unknown
}

/** El `activo` es uniforme en la API aunque en la base dos tablas lo tengan
 *  en femenino — el mapeo vive en el backend, ver `app/schemas/maestros.py`. */
export type Recurso =
  | 'terceros'
  | 'localidades'
  | 'choferes'
  | 'vehiculos'
  | 'razones-sociales'
  | 'tipos-carga'

export function clienteDe<T extends Maestro>(recurso: Recurso) {
  const base = `/api/${recurso}`
  return {
    // Sin `?activo=`: el listado trae también las bajas, que es lo que permite
    // reactivarlas. El filtro se aplica del lado del cliente.
    listar: () => api.get<T[]>(base),
    crear: (datos: Partial<T>) => api.post<T>(base, datos),
    editar: (id: number, datos: Partial<T>) => api.put<T>(`${base}/${id}`, datos),
    darDeBaja: (id: number) => api.del<T>(`${base}/${id}`),
  }
}
