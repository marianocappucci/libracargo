// Los datos y las respuestas de la API que comparten los tests de Clientes, Proveedores y Transporte (ADR-040, ADR-045): las mismas
// entidades por rol, los mismos choferes y vehículos. Los `vi.mock` quedan en cada test —se elevan al principio del archivo—; acá sólo
// hay datos y una función que arma las respuestas de un `get` ya mockeado.
import type { Mock } from 'vitest'

export type Rol = 'cliente' | 'fletero' | 'proveedor'

export const entidad = (id: number, razon_social: string, roles: Rol[], extra: Record<string, unknown> = {}) => ({
  id, razon_social, cuit: null, condicion_iva: 'responsable_inscripto', localidad: null, contacto: null, activo: true,
  es_cliente: roles.includes('cliente'), es_fletero: roles.includes('fletero'), es_proveedor: roles.includes('proveedor'),
  ...extra,
})

export const ENTIDADES = [
  entidad(1, 'Agro Norte SA', ['cliente']),
  entidad(2, 'Transportes del Sur', ['fletero', 'proveedor'], { cuit: '30711111114' }),
  entidad(3, 'Ferretería Central', ['proveedor']),
]

export const CHOFERES = [
  { id: 11, nombre: 'Juan Pérez', dni: '20111222', cuit: '20123456786', telefono: null, fletero_id: 2, observaciones: null, activo: true },
  { id: 12, nombre: 'Ana Gómez', dni: null, cuit: null, telefono: '3415550000', fletero_id: null, observaciones: null, activo: true },
]

export const VEHICULOS = [
  { id: 21, patente_chasis: 'AB123CD', patente_acoplado: 'EF456GH', fletero_id: 2, observaciones: null, activo: true },
]

/** Las respuestas por omisión de la API para estas pantallas. */
export function responder(get: Mock) {
  get.mockImplementation((ruta: string) => {
    const porRol = ruta.match(/^\/api\/terceros\/rol\/(\w+)\?solo_activos=false$/)
    if (porRol) return Promise.resolve(ENTIDADES.filter((e) => e[`es_${porRol[1]}` as 'es_cliente']))
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({ razon_social: 'Transportes del Plata' })
    if (ruta === '/api/choferes') return Promise.resolve(CHOFERES)
    if (ruta === '/api/choferes?fletero_id=2') return Promise.resolve(CHOFERES.filter((c) => c.fletero_id === 2))
    if (ruta === '/api/vehiculos') return Promise.resolve(VEHICULOS)
    if (ruta === '/api/vehiculos?fletero_id=2') return Promise.resolve(VEHICULOS)
    return Promise.resolve([])
  })
}

/** El 409 del servidor por un CUIT que ya es de otra entidad. `ApiError` es la clase del módulo mockeado del test, que la pasa. */
export function cuitDuplicado(
  ApiError: new (status: number, detail: string, detailData?: unknown) => Error,
  existente: { id: number; razon_social: string; roles: Rol[] },
) {
  const mensaje = `El CUIT 30-71111111-4 ya es de «${existente.razon_social}». Sumale el rol en vez de cargarla de nuevo.`
  return new ApiError(409, mensaje, { mensaje, existente: { activo: true, ...existente } })
}

/** jsdom no trae `matchMedia`, que algunas piezas del kit piden. */
export function simularMatchMedia() {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}
