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
  /** La pre factura es una pantalla y no un diálogo: tiene sus acciones (enviar, aceptar, facturar). */
  preFactura: (id: number) => `/pre-facturas/${id}`,
  caja: (id: number) => `/caja?ver=${id}`,
  cuenta: (rol: string, terceroId: number) => `/cuentas?rol=${rol}&tercero=${terceroId}`,
  /** Sin rol: la pantalla elige el primero que el tercero tenga. Es todo lo que
   *  se puede saber desde caja, donde el movimiento guarda el tercero y no la
   *  cuenta a la que fue la contrapartida. */
  cuentaDe: (terceroId: number) => `/cuentas?tercero=${terceroId}`,
  /** El comprobante de proveedor es la sección «Proveedores» de Comprobantes. `/gastos?ver=` (el enlace
   *  de antes) sigue andando: `App.tsx` lo redirige acá. */
  gasto: (id: number) => `/comprobantes?seccion=proveedores&ver=${id}`,
  /** La pantalla de facturar, con el cliente ya elegido si se sabe cual. */
  facturarPendientes: (clienteId?: number) =>
    clienteId ? `/comprobantes/facturar?cliente=${clienteId}` : '/comprobantes/facturar',
  /** «Entidades» (ADR-040), en la pestaña que se pida y, con `ver`, con la ficha de esa fila abierta. Sin nada es la
   *  ruta pelada, que cae en Clientes. */
  entidades: (pestana?: PestanaDeEntidades, ver?: number) => {
    const params = new URLSearchParams()
    if (pestana) params.set('pestana', pestana)
    if (ver !== undefined) params.set('ver', String(ver))
    const query = params.toString()
    return query ? `/entidades?${query}` : '/entidades'
  },
  /** «Vehículos», una entrada propia del menú (antes una sección de Configuración). Con `ver`, con la ficha de esa fila abierta. */
  vehiculos: (ver?: number) => (ver !== undefined ? `/vehiculos?ver=${ver}` : '/vehiculos'),
}

/** Las cuatro pestañas de la entrada «Entidades» del menú (ADR-040). Tres son roles de una misma entidad —una
 *  persona o empresa puede ser a la vez cliente, fletero y proveedor— y la cuarta, Choferes, es otra tabla: la
 *  persona que conduce. La pestaña va en el query (`?pestana=`), como la sección de Comprobantes. */
export const PESTANAS_DE_ENTIDADES = ['clientes', 'fleteros', 'choferes', 'proveedores'] as const
export type PestanaDeEntidades = (typeof PESTANAS_DE_ENTIDADES)[number]

/** La pestaña que pide un query; cualquier cosa que no sea una conocida cae en Clientes. */
export function pestanaDeEntidades(valor: string | null): PestanaDeEntidades {
  return PESTANAS_DE_ENTIDADES.find((p) => p === valor) ?? 'clientes'
}

/** Las secciones de Configuración que se mudaron a Entidades, y a qué pestaña. Un enlace viejo
 *  (`/configuracion?seccion=terceros`) se redirige con esto. */
export const SECCIONES_MUDADAS_A_ENTIDADES: Readonly<Record<string, PestanaDeEntidades>> = {
  terceros: 'clientes',
  choferes: 'choferes',
}

/** Las dos secciones de la entrada «Comprobantes» del menú. La sección va en el query (`?seccion=`), como la de
 *  Configuración de la familia: la clientes es la de la ruta pelada, así que `/comprobantes` y los enlaces de
 *  siempre caen ahí, y sólo la otra lleva parámetro. El `?ver=` es de la sección que lo abre. */
export const SECCIONES_DE_COMPROBANTES = ['clientes', 'proveedores'] as const
export type SeccionDeComprobantes = (typeof SECCIONES_DE_COMPROBANTES)[number]

/** La sección que pide un query; cualquier cosa que no sea una conocida cae en Clientes. */
export function seccionDe(valor: string | null): SeccionDeComprobantes {
  return valor === 'proveedores' ? 'proveedores' : 'clientes'
}

/** Las rutas que pertenecen a «Comprobantes», para que el menú marque esa entrada en todas
 *  (`activoEn` de libra-ui 0.119.0: cada una cubre también lo que cuelga de ella).
 *
 *  «Comprobantes» abarca más que `/comprobantes`: facturar pendientes (`/comprobantes/facturar`),
 *  las pre facturas (lista, detalle, edición) y el enlace viejo `/gastos`.
 */
export const RUTAS_DE_COMPROBANTES = ['/comprobantes', '/pre-facturas', '/gastos']

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
  if (m.gasto_id) return irA.gasto(m.gasto_id)
  return null
}

/** Los cinco maestros. El `prefijo` del ABM del backend **es** la ruta del
 *  frontend y **es** el nombre con el que se audita: `app/routers/maestros.py`
 *  registra con `prefijo`, por eso en el log aparecen en plural
 *  (`localidades`, no `localidad`). Que sean la misma cadena no es casualidad,
 *  pero tampoco está garantizado por nada — hay un test que lo ata. */
const MAESTROS = [
  'terceros', 'localidades', 'choferes', 'vehiculos', 'tipos-carga',
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
    if (entidad === 'pre_factura') return irA.preFactura(entidadId)
    if (entidad === 'movimiento_caja') return irA.caja(entidadId)
    if (entidad === 'gasto_de_proveedor') return irA.gasto(entidadId)
  }
  if (entidad === 'configuracion') return '/configuracion'
  // Terceros y choferes ya no son pantallas sueltas ni secciones de Configuración: viven en «Entidades». Un tercero no dice
  // en el log de qué rol era, así que se lo lleva a la entrada y no a una pestaña.
  if (entidad === 'terceros') return irA.entidades()
  if (entidad === 'choferes') return irA.entidades('choferes')
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
