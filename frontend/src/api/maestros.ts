import { api } from 'libra-ui/api-client'

/** Lo que devuelven los cinco ABM. Los campos propios de cada uno se agregan
 *  con una intersección en su pantalla: acá está lo que comparten. */
export type Maestro = {
  id: number
  activo: boolean
  [campo: string]: unknown
}

/** El `activo` es uniforme en la API aunque en la base una tabla lo tenga
 *  en femenino — el mapeo vive en el backend, ver `app/schemas/maestros.py`. */
export type Recurso =
  | 'terceros'
  | 'localidades'
  | 'choferes'
  | 'vehiculos'
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

/** Los tres roles de una entidad (ADR-040): una misma persona o empresa puede tener uno o más. */
export type RolDeEntidad = 'cliente' | 'fletero' | 'proveedor'

/** Lo que contesta el servidor cuando el CUIT de un alta (o una edición) ya es de otra entidad: un 409 cuyo
 *  `detail` es un **objeto** y no un texto. `existente.roles` son los roles que ya tiene. */
export type CuitRepetido = {
  mensaje: string
  existente: { id: number; razon_social: string; roles: RolDeEntidad[]; activo: boolean }
}

/** El conflicto de CUIT repetido, o `null` si el error es otra cosa.
 *
 *  `libra-ui` deja el objeto en `detailData` y aplana `detail` a su `mensaje`; se lee `detail` también por si el
 *  error llega con el objeto directo (un doble de test, o una versión del kit que no lo aplane). */
export function cuitRepetido(e: unknown): CuitRepetido | null {
  if (!e || typeof e !== 'object' || (e as { status?: unknown }).status !== 409) return null
  const { detailData, detail } = e as { detailData?: unknown; detail?: unknown }
  const d = (detailData ?? detail) as Partial<CuitRepetido> | null | undefined
  if (!d || typeof d !== 'object' || typeof d.mensaje !== 'string') return null
  const ex = d.existente
  if (!ex || typeof ex.id !== 'number') return null
  return {
    mensaje: d.mensaje,
    existente: {
      id: ex.id,
      razon_social: String(ex.razon_social ?? ''),
      roles: Array.isArray(ex.roles) ? ex.roles : [],
      activo: ex.activo !== false,
    },
  }
}

/** Le suma un rol a una entidad que ya existe (y la reactiva si estaba de baja). */
export const sumarRol = (id: number, rol: RolDeEntidad) =>
  api.post<Maestro>(`/api/terceros/${id}/roles/${rol}`)

/** Las entidades con un rol, bajas incluidas: es el listado de Clientes, Proveedores y la pestaña Fleteros de Transporte. Sin tope, a
 *  diferencia del listado genérico (`/api/terceros`, 200 por página). */
export const listarPorRol = <T extends Maestro>(rol: RolDeEntidad) =>
  api.get<T[]>(`/api/terceros/rol/${rol}?solo_activos=false`)

/** Los choferes y los vehículos de un fletero, para su ficha. */
export const choferesDe = (fleteroId: number) => api.get<Maestro[]>(`/api/choferes?fletero_id=${fleteroId}`)
export const vehiculosDe = (fleteroId: number) => api.get<Maestro[]>(`/api/vehiculos?fletero_id=${fleteroId}`)
