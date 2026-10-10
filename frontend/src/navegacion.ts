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
  /** «Clientes», una entrada propia del menú (ADR-045; era una pestaña de «Entidades»). Con `ver`, con la ficha de esa fila abierta. */
  clientes: (ver?: number) => (ver !== undefined ? `/clientes?ver=${ver}` : '/clientes'),
  /** «Proveedores», una entrada propia del menú (ADR-045; era una pestaña de «Entidades»). Con `ver`, con la ficha de esa fila abierta. */
  proveedores: (ver?: number) => (ver !== undefined ? `/proveedores?ver=${ver}` : '/proveedores'),
  /** «Transporte» (ADR-045; antes «Entidades»), en la pestaña que se pida y, con `ver`, con la ficha de esa fila abierta. Sin nada es
   *  la ruta pelada, que cae en Fleteros. */
  transporte: (pestana?: PestanaDeTransporte, ver?: number) => {
    const params = new URLSearchParams()
    if (pestana) params.set('pestana', pestana)
    if (ver !== undefined) params.set('ver', String(ver))
    const query = params.toString()
    return query ? `/transporte?${query}` : '/transporte'
  },
  /** La pantalla de una entidad según de qué tipo sea: cliente y proveedor tienen la suya; fletero y chofer, una pestaña de Transporte. Es
   *  lo que usa quien enlaza a una entidad sin saber en qué pantalla vive (la ficha del fletero, el CUIT repetido, los enlaces viejos). */
  entidad: (tipo: TipoDeEntidad, ver?: number): string => {
    if (tipo === 'clientes') return irA.clientes(ver)
    if (tipo === 'proveedores') return irA.proveedores(ver)
    return irA.transporte(tipo, ver)
  },
  /** «Cartas de porte» (ADR-036) en la pestaña «Titulares» (ADR-044) y, con `ver`, con la ficha de ese titular abierta. */
  titulares: (ver?: number) => (ver !== undefined ? `/cartas-porte?pestana=titulares&ver=${ver}` : '/cartas-porte?pestana=titulares'),
  /** «Emitir carta de porte» de una orden (ADR-043): una página propia que cuelga de «Cartas de porte». */
  emitirCartaDePorte: (ordenId: number) => `/cartas-porte/emitir/${ordenId}`,
  /** Los datos habituales para emitir a nombre de un titular (ADR-044), en su propia página. */
  plantillaDeTitular: (titularId: number) => `/cartas-porte/titulares/${titularId}/plantilla`,
  /** «Vehículos», la tercera pestaña de «Transporte» (ADR-045; antes una entrada propia del menú, y antes una sección de Configuración).
   *  Con `ver`, con la ficha de esa fila abierta. */
  vehiculos: (ver?: number): string => irA.transporte('vehiculos', ver),
}

/** Los cuatro tipos de entidad que hubo como pestañas de «Entidades» (ADR-040). Tres son roles de una misma entidad —una persona o
 *  empresa puede ser a la vez cliente, fletero y proveedor— y la cuarta, Choferes, es otra tabla: la persona que conduce. Desde
 *  ADR-045 «Entidades» ya no existe: clientes y proveedores tienen pantalla propia y fleteros y choferes son pestañas de «Transporte».
 *  El tipo sigue siendo la forma de nombrar «qué es esta fila», y `irA.entidad` dice a qué pantalla lleva cada uno. */
export const TIPOS_DE_ENTIDAD = ['clientes', 'fleteros', 'choferes', 'proveedores'] as const
export type TipoDeEntidad = (typeof TIPOS_DE_ENTIDAD)[number]

/** Las tres pestañas de la entrada «Transporte» del menú (ADR-045), en este orden: Fleteros, Choferes y Vehículos. La pestaña va en el
 *  query (`?pestana=`), como la sección de Comprobantes. */
export const PESTANAS_DE_TRANSPORTE = ['fleteros', 'choferes', 'vehiculos'] as const
export type PestanaDeTransporte = (typeof PESTANAS_DE_TRANSPORTE)[number]

/** La pestaña que pide un query; cualquier cosa que no sea una conocida cae en Fleteros. */
export function pestanaDeTransporte(valor: string | null): PestanaDeTransporte {
  return PESTANAS_DE_TRANSPORTE.find((p) => p === valor) ?? 'fleteros'
}

/** A dónde lleva un enlace viejo a `/entidades` (ADR-040): la pantalla nueva de esa pestaña, con la ficha (`ver`) si traía una
 *  válida. Sin pestaña, o con una desconocida, es Clientes, como era. Cualquier otro parámetro se descarta, que era lo que hacía
 *  cambiar de pestaña. */
export function destinoDeEntidadesViejo(search: string): string {
  const params = new URLSearchParams(search)
  const tipo = TIPOS_DE_ENTIDAD.find((t) => t === params.get('pestana')) ?? 'clientes'
  return irA.entidad(tipo, verValido(params.get('ver')))
}

/** A dónde lleva un enlace viejo a `/vehiculos` (cuando era una entrada del menú, ADR-045): la pestaña Vehículos de Transporte, con
 *  **todo** el query que traía (`ver` u otro) detrás. Si el enlace traía una `pestana` propia se descarta: la que manda es Vehículos. */
export function destinoDeVehiculosViejo(search: string): string {
  const params = new URLSearchParams({ pestana: 'vehiculos' })
  new URLSearchParams(search).forEach((valor, clave) => {
    if (clave !== 'pestana') params.append(clave, valor)
  })
  return `/transporte?${params}`
}

/** El `?ver=` como número, o `undefined` si falta o no es un id. */
export function verValido(valor: string | null): number | undefined {
  const ver = Number(valor)
  return valor && Number.isInteger(ver) && ver > 0 ? ver : undefined
}

/** Las dos pestañas de «Cartas de porte»: el listado de las cartas y los titulares a cuyo nombre se emiten (ADR-044). La
 *  del listado es la de la ruta pelada, así que `/cartas-porte` y los enlaces de siempre caen ahí; sólo la otra lleva
 *  parámetro (`?pestana=titulares`). */
export const PESTANAS_DE_CARTAS_DE_PORTE = ['cartas', 'titulares'] as const
export type PestanaDeCartasDePorte = (typeof PESTANAS_DE_CARTAS_DE_PORTE)[number]

/** La pestaña que pide un query; cualquier cosa que no sea una conocida cae en el listado. */
export function pestanaDeCartasDePorte(valor: string | null): PestanaDeCartasDePorte {
  return PESTANAS_DE_CARTAS_DE_PORTE.find((p) => p === valor) ?? 'cartas'
}

/** Las secciones de Configuración que se mudaron (primero a Entidades, ADR-040; hoy a Clientes y a Transporte, ADR-045), y de qué tipo
 *  de entidad es cada una. Un enlace viejo (`/configuracion?seccion=terceros`) se redirige con esto, directo a la pantalla de hoy. */
export const SECCIONES_MUDADAS_DE_CONFIGURACION: Readonly<Record<string, TipoDeEntidad>> = {
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
    // El titular de cartas de porte lleva a su ficha, y su plantilla a la página de la plantilla (el id de la plantilla
    // es el del titular).
    if (entidad === 'titular_cpe') return irA.titulares(entidadId)
    if (entidad === 'plantilla_cpe') return irA.plantillaDeTitular(entidadId)
  }
  if (entidad === 'configuracion') return '/configuracion'
  // Terceros y choferes ya no son pantallas sueltas ni secciones de Configuración. Un tercero no dice en el log de qué rol era, así
  // que se lo lleva a Clientes y no a una pantalla que quizás no lo tenga; el chofer, a la pestaña Choferes de Transporte.
  if (entidad === 'terceros') return irA.clientes()
  if (entidad === 'choferes') return irA.transporte('choferes')
  if (entidad === 'vehiculos') return irA.vehiculos()
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
