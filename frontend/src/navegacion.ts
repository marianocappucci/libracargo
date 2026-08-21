/** A dónde lleva cada cosa. El contrato de los enlaces profundos, en un lugar.
 *
 *  Pedido del humano (2026-08-20): *"debo poder hacer click en una fila y que me
 *  mande a la orden de carga o a la factura o al detalle, pero tiene que ser
 *  todo clickeable"*. Antes de esto había **nueve tablas y cero `onRowClick`**:
 *  para ver el detalle de una orden había que encontrar el botón de la columna
 *  de acciones, y desde un movimiento de cuenta corriente no se llegaba a la
 *  orden que lo originó de ninguna forma.
 *
 *  ## Por qué `?ver=` y no una ruta propia
 *
 *  El detalle de una orden es un diálogo sobre el listado, no una pantalla: al
 *  cerrarlo hay que quedar en la lista, con sus filtros puestos. Una ruta
 *  `/ordenes/123` obligaría a montar el listado dos veces o a perder los
 *  filtros. El parámetro abre el diálogo y desaparece al cerrarlo, así el botón
 *  de atrás del navegador hace lo que se espera.
 */
import type { FilaDeCuenta } from '@/api/cuentas'

export const irA = {
  orden: (id: number) => `/ordenes?ver=${id}`,
  comprobante: (id: number) => `/comprobantes?ver=${id}`,
  caja: (id: number) => `/caja?ver=${id}`,
  cuenta: (rol: string, terceroId: number) => `/cuentas?rol=${rol}&tercero=${terceroId}`,
  /** Sin rol: la pantalla elige el primero que el tercero tenga. Es todo lo que
   *  se puede saber desde caja, donde el movimiento guarda el tercero y no la
   *  cuenta a la que fue la contrapartida. */
  cuentaDe: (terceroId: number) => `/cuentas?tercero=${terceroId}`,
}

/** El origen de un asiento de cuenta corriente, o `null` si no tiene.
 *
 *  El orden importa: un asiento puede apuntar a la orden **y** al comprobante
 *  que la facturó. Se prefiere el comprobante porque es el documento que
 *  explica el importe de esa línea — la orden se llega desde ahí, que además
 *  lista todas las que agrupa.
 */
export function origenDelMovimiento(fila: FilaDeCuenta): string | null {
  const m = fila.movimiento
  if (m.comprobante_id) return irA.comprobante(m.comprobante_id)
  if (m.orden_id) return irA.orden(m.orden_id)
  if (m.movimiento_caja_id) return irA.caja(m.movimiento_caja_id)
  return null
}

/** Los seis maestros. El `prefijo` del ABM del backend **es** la ruta del
 *  frontend y **es** el nombre con el que se audita: `app/routers/maestros.py`
 *  registra con `prefijo`, por eso en el log aparecen en plural
 *  (`localidades`, no `localidad`). Que sean la misma cadena no es casualidad,
 *  pero tampoco está garantizado por nada — hay un test que lo ata. */
const MAESTROS = [
  'terceros', 'localidades', 'choferes', 'vehiculos', 'razones-sociales', 'tipos-carga',
] as const

/** Qué pantalla corresponde a cada entidad del log de actividad.
 *
 *  Las claves son las que escribe el backend. Una entidad que no esté acá
 *  simplemente no es clickeable: es preferible a mandar a una pantalla que no
 *  muestra lo que se fue a buscar.
 */
export function destinoDelLog(entidad: string, entidadId: number | null): string | null {
  if (entidadId !== null) {
    if (entidad === 'orden_carga') return irA.orden(entidadId)
    if (entidad === 'comprobante') return irA.comprobante(entidadId)
    if (entidad === 'movimiento_caja') return irA.caja(entidadId)
  }
  if (entidad === 'configuracion') return '/configuracion'
  // Los maestros no tienen enlace profundo a una fila: la pantalla es un ABM
  // con buscador, y abrir el formulario de edición de algo que quizás ya se
  // borró seria peor que dejar al usuario en la lista.
  if ((MAESTROS as readonly string[]).includes(entidad)) return `/${entidad}`
  return null
}

/** A dónde lleva una fila de un reporte, que depende de cuál reporte sea.
 *
 *  Los que agrupan por tercero llevan a su cuenta corriente. Los que son
 *  agregados puros —caja por medio de pago, rutas más transitadas— **no llevan
 *  a ningún lado, a propósito**: la fila no es una cosa, es una suma, y mandar
 *  a una pantalla arbitraria es peor que no hacer nada. La tabla no le pone
 *  cursor de mano a lo que no es clickeable, así que no parece roto.
 */
export function destinoDeFilaDeReporte(
  slug: string,
  fila: Record<string, string | number | null>,
): string | null {
  const numero = (clave: string) => {
    const valor = fila[clave]
    return typeof valor === 'number' ? valor : null
  }
  if (slug === 'saldos') {
    const id = numero('tercero_id')
    const rol = fila.rol
    return id && typeof rol === 'string' ? irA.cuenta(rol, id) : null
  }
  if (slug === 'por-cliente') {
    const id = numero('tercero_id')
    return id ? irA.cuenta('cliente', id) : null
  }
  if (slug === 'por-fletero') {
    const id = numero('tercero_id')
    return id ? irA.cuenta('fletero', id) : null
  }
  if (slug === 'pendientes-de-facturar') {
    const id = numero('cliente_id')
    return id ? irA.cuenta('cliente', id) : null
  }
  if (slug === 'por-razon-social') return '/comprobantes'
  return null
}

export const MAESTROS_AUDITADOS = MAESTROS
