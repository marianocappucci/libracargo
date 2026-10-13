import { api } from 'libra-ui/api-client'

import type { Orden } from '@/api/ordenes'

export type TipoComprobante =
  | 'factura_a' | 'factura_b' | 'factura_c'
  | 'nota_credito_a' | 'nota_credito_b' | 'nota_credito_c'
  // Factura de Crédito Electrónica MiPyME, y su nota de crédito (sólo parcial: ARCA no deja
  // anularla entera si el comprador no la rechazó).
  | 'fce_a' | 'fce_b' | 'fce_c'
  | 'nota_credito_fce_a' | 'nota_credito_fce_b' | 'nota_credito_fce_c'
  // La nota de débito (ADR-048) y la de una FCE: suman plata a una factura con CAE.
  | 'nota_debito_a' | 'nota_debito_b' | 'nota_debito_c'
  | 'nota_debito_fce_a' | 'nota_debito_fce_b' | 'nota_debito_fce_c'

/** Lo que devuelve emitir un comprobante o una nota cuando el ambiente de ARCA es homologación.
 *
 *  🔴 **No es un `Comprobante` incompleto: no existe.** El backend corre el
 *  alta entera contra ARCA —número, pedido, CAE— y la revierte, porque acá un
 *  comprobante además mueve la cuenta corriente y cierra las órdenes. Por eso
 *  no tiene `id`, y por eso el `POST` contesta 200 y no 201.
 *
 *  Se distingue por `ensayo`, que sólo viene en esta forma. Guiarse por la
 *  ausencia de `id` sería frágil: cualquier respuesta a medias la cumpliría.
 */
export type Ensayo = {
  ensayo: true
  ambiente: string
  tipo: TipoComprobante
  punto_venta: number
  numero: number
  total: string
  cae: string | null
  cae_vencimiento: string | null
}

export type Comprobante = {
  id: number
  tipo: TipoComprobante
  punto_venta: number
  numero: number
  fecha: string
  cliente_id: number
  // Importes como STRING, igual que en las ordenes: son `NUMERIC` en la base y
  // `Decimal` en Python. Pasarlos por `number` los mete en un float binario,
  // que es el defecto que el producto viene a reparar.
  neto: string
  iva: string
  total: string
  anulado: boolean
  origen_legado: string | null
  // El CAE que dio ARCA. `null` en lo registrado a mano y en lo migrado del legado.
  cae?: string | null
  // Sólo una FCE los tiene; en todo lo demás vienen `null`.
  fch_vto_pago?: string | null
  fce_cbu?: string | null
  fce_transmision?: string | null
  // Sólo una nota (de crédito o de débito) los tiene: a qué comprobante se asocia y por qué.
  comprobante_asociado_id?: number | null
  motivo?: string | null
  /** No agrupa órdenes (ADR-048): una factura directa o una nota de débito. */
  sin_ordenes?: boolean
}

/** Lo que contesta `GET /api/comprobantes/fce/corresponde`. La regla es del motor (ADR-019 de LibraCore). */
export type AvisoFce = {
  /** `false` si no se pudo preguntar (sin ARCA, cliente sin CUIT, ARCA caído): se emite como siempre. */
  disponible: boolean
  corresponde?: boolean
  obligado?: boolean
  /** Desde qué total rige para ese receptor, como texto. */
  monto_desde?: string | null
  motivo?: string
  /** Si la empresa ya puede emitir FCE (emite por ARCA y cargó CBU y modalidad). */
  fce_habilitada: boolean
}

/** Una cuenta donde se cobra una FCE (libracore ADR-040): se elige por su alias o por su CBU. */
export type CuentaFce = { cbu: string; alias: string; etiqueta: string }

/** Lo que contesta `GET /api/comprobantes/fce/cuentas`: las cuentas cargadas en Configuración → ARCA. */
export type CuentasFce = {
  cuentas: CuentaFce[]
  /** El CBU que sale si no se elige otra; `''` si no hay ninguna. */
  predeterminada: string
  transmision: string
}

/** Cómo se muestra una cuenta para elegirla: el alias primero (es lo que se recuerda), el CBU y el nombre. */
export function etiquetaDeCuenta(c: CuentaFce): string {
  return [c.alias || 'sin alias', `CBU ${c.cbu}`, c.etiqueta].filter(Boolean).join(' · ')
}

export type SumaDeOrdenes = { cantidad: number; neto: string; iva: string; total: string }

export type ComprobanteConOrdenes = {
  comprobante: Comprobante
  ordenes: Orden[]
  suma_de_ordenes: SumaDeOrdenes
  /** Si el encabezado dice lo mismo que sus ordenes. */
  coinciden: boolean
  /** Las notas de crédito que cuelgan de este comprobante. */
  notas?: Comprobante[]
  /** Las notas de débito que cuelgan de este comprobante (ADR-048). */
  notas_debito?: Comprobante[]
  /** Lo acreditado por sus notas con CAE y lo que queda (lo cuenta el motor). `null` si no admite nota. */
  acreditado?: string | null
  saldo_acreditable?: string | null
}

/** Lo facturado en el rango, contado por los dos lados (el gate de F5). Un solo emisor: no se abre por razón social. */
export type TotalDeComprobantes = {
  cantidad_comprobantes: number
  neto_comprobantes: string
  iva_comprobantes: string
  total_comprobantes: string
  cantidad_ordenes: number
  neto_ordenes: string
  iva_ordenes: string
  total_ordenes: string
  coinciden: boolean
  /** Lo que no tiene órdenes contra las que compararse (ADR-048): facturas directas y notas de débito, netas de las notas
   *  de crédito de las facturas directas. Va aparte del gate. */
  cantidad_sin_ordenes?: number
  total_sin_ordenes?: string
}

/** Un importe `"1234.56"` a centavos enteros. */
function aCentavos(valor: string): number {
  const [entero, decimales = ''] = valor.trim().split('.')
  const signo = entero.trimStart().startsWith('-') ? -1 : 1
  return signo * (Math.abs(Number(entero)) * 100 + Number((decimales + '00').slice(0, 2)))
}

/** Suma importes **en centavos enteros**, no en punto flotante.
 *
 * `0.1 + 0.2` en JavaScript da `0.30000000000000004`: los importes se manejan
 * como texto en toda la app justamente para no pasar por ahi. Esta suma es solo
 * la **previsualizacion** de lo que se va a facturar --el importe que queda
 * guardado lo calcula el servidor con `Decimal` sobre las mismas ordenes--,
 * pero una vista previa que no coincide con el total real es peor que no
 * mostrar nada: quien la mira decide con ella.
 */
export function sumarImportes(valores: string[]): string {
  const centavos = valores.reduce((acumulado, v) => acumulado + aCentavos(v), 0)
  const signo = centavos < 0 ? '-' : ''
  const absoluto = Math.abs(centavos)
  return `${signo}${Math.floor(absoluto / 100)}.${String(absoluto % 100).padStart(2, '0')}`
}

/** `Factura A 0001-00000123`, como se lee en el papel. */
export const NOMBRE_DE_TIPO: Record<TipoComprobante, string> = {
  factura_a: 'Factura A', factura_b: 'Factura B', factura_c: 'Factura C',
  nota_credito_a: 'Nota de crédito A', nota_credito_b: 'Nota de crédito B',
  nota_credito_c: 'Nota de crédito C',
  fce_a: 'Factura de crédito electrónica A', fce_b: 'Factura de crédito electrónica B',
  fce_c: 'Factura de crédito electrónica C',
  nota_credito_fce_a: 'Nota de crédito FCE A', nota_credito_fce_b: 'Nota de crédito FCE B',
  nota_credito_fce_c: 'Nota de crédito FCE C',
  nota_debito_a: 'Nota de débito A', nota_debito_b: 'Nota de débito B', nota_debito_c: 'Nota de débito C',
  nota_debito_fce_a: 'Nota de débito FCE A', nota_debito_fce_b: 'Nota de débito FCE B',
  nota_debito_fce_c: 'Nota de débito FCE C',
}

/** Las facturas (comunes y FCE): lo único a lo que se le emite una nota. Una nota no admite otra. */
export function esFactura(tipo: TipoComprobante): boolean {
  return tipo.startsWith('factura_') || tipo.startsWith('fce_')
}

/** Lo que se manda para facturar las órdenes de un cliente (`POST /api/comprobantes/desde-ordenes`, ADR-048). Los ítems y los
 *  importes no viajan: salen de las órdenes. */
export type FacturarOrdenes = {
  cliente_id: number
  tipo: TipoComprobante
  fecha: string
  /** Sólo la FCE. */
  fecha_vencimiento_pago?: string
  /** Sólo la FCE: el CBU o el alias de la cuenta; `''` es la predeterminada. */
  fce_cbu?: string
  orden_ids: number[]
  observaciones?: string
}

/** Un renglón de la factura directa. Los importes son texto: no pasan por un float. */
export type Concepto = {
  descripcion: string
  cantidad: string
  precio_unitario: string
  /** `'0'`, `'10.5'`, `'21'` o `'27'`: las que recibe ARCA. */
  alicuota_iva: string
}

/** Las alícuotas que se pueden facturar (las del WSFE del motor). */
export const ALICUOTAS_DE_IVA = ['21', '10.5', '27', '0'] as const

/** Lo que se manda para la «Nueva factura» (`POST /api/comprobantes/directa`, ADR-048): los importes los calcula el servidor. */
export type FacturaDirecta = {
  cliente_id: number
  tipo: TipoComprobante
  fecha: string
  fecha_vencimiento_pago?: string
  fce_cbu?: string
  conceptos: Concepto[]
  observaciones?: string
}

/** Qué clases puede emitir la empresa (`GET /api/comprobantes/tipos`): la lista de la pantalla «Nueva factura». */
export type OpcionesDeTipo = {
  tipos: TipoComprobante[]
  /** La factura común que le corresponde cuando hay una sola; `null` si no se sabe. */
  sugerido: TipoComprobante | null
  /** Si la empresa ya puede emitir FCE y el cliente es una empresa con CUIT. */
  fce_habilitada: boolean
  /** Por qué no se puede emitir ninguna, o `null`. */
  problema: string | null
}

/** El IVA de un renglón no se calcula acá: el servidor lo hace sobre el neto. Esto es la **vista previa** de la factura
 *  directa, en centavos enteros (como `sumarImportes`), con la misma regla: el IVA una vez sobre el neto, redondeado
 *  hacia arriba desde la mitad. Una clase C no discrimina IVA: el precio es el total. */
export function previsualizarFactura(conceptos: Concepto[], esClaseC: boolean): {
  neto: string; iva: string; total: string; alicuotas: string[]
} {
  let netoCentavos = 0
  for (const c of conceptos) {
    const cantidad = aMilesimas(c.cantidad)
    const precio = aCentavos(c.precio_unitario || '0')
    if (cantidad === null || Number.isNaN(precio)) continue
    // cantidad (milésimas) × precio (centavos) → centavos, mitad hacia arriba.
    netoCentavos += Math.floor((cantidad * precio + 500) / 1000)
  }
  const alicuotas = [...new Set(conceptos.map((c) => c.alicuota_iva))]
  const alicuota = esClaseC || alicuotas.length !== 1 ? 0 : Number(alicuotas[0])
  // alícuota en décimas de punto (10.5 → 105) para no multiplicar por un float.
  const decimas = Math.round(alicuota * 10)
  const ivaCentavos = Math.floor((netoCentavos * decimas + 500) / 1000)
  const texto = (n: number) => `${Math.floor(n / 100)}.${String(n % 100).padStart(2, '0')}`
  return {
    neto: texto(netoCentavos), iva: texto(ivaCentavos), total: texto(netoCentavos + ivaCentavos),
    alicuotas: esClaseC ? [] : alicuotas,
  }
}

/** `"1.5"` a milésimas enteras (`1500`), o `null` si no es una cantidad de hasta tres decimales. */
function aMilesimas(texto: string): number | null {
  const limpio = texto.trim().replace(',', '.')
  if (!/^\d+(\.\d{1,3})?$/.test(limpio)) return null
  const [entero, dec = ''] = limpio.split('.')
  return Number(entero) * 1000 + Number((dec + '000').slice(0, 3))
}

export function numeroDe(c: Comprobante): string {
  return `${String(c.punto_venta).padStart(4, '0')}-${String(c.numero).padStart(8, '0')}`
}

export const comprobantes = {
  listar: (filtros: Record<string, string | number | boolean | undefined> = {}) => {
    const p = new URLSearchParams()
    // `!= null` y no `if (v)`: `anulado=false` es un filtro y no una ausencia.
    for (const [k, v] of Object.entries(filtros)) {
      if (v != null && v !== '') p.set(k, String(v))
    }
    const qs = p.toString()
    return api.get<Comprobante[]>(`/api/comprobantes${qs ? `?${qs}` : ''}`)
  },
  ver: (id: number) => api.get<ComprobanteConOrdenes>(`/api/comprobantes/${id}`),
  totales: (desde?: string, hasta?: string) => {
    const p = new URLSearchParams()
    if (desde) p.set('desde', desde)
    if (hasta) p.set('hasta', hasta)
    const qs = p.toString()
    return api.get<TotalDeComprobantes>(`/api/comprobantes/totales${qs ? `?${qs}` : ''}`)
  },
  // ¿A este comprobante le corresponde ser FCE? Lo contesta el registro de ARCA a través del motor. Es un
  // aviso: nunca falla por ARCA (`disponible: false` y el motivo).
  fceCuentas: () => api.get<CuentasFce>('/api/comprobantes/fce/cuentas'),
  fceCorresponde: (p: { cliente_id: number; total: string; fecha: string }) =>
    api.get<AvisoFce>(`/api/comprobantes/fce/corresponde?${new URLSearchParams({
      cliente_id: String(p.cliente_id), total: p.total, fecha: p.fecha,
    })}`),
  /** El PDF del comprobante (ADR-034): se abre y se baja por un enlace común, la sesión viaja en la cookie.
   *  Sólo existe para un comprobante con CAE: sin CAE el servidor contesta 404. */
  urlDelPdf: (id: number) => `/api/comprobantes/${id}/pdf`,
  /** Manda ese mismo PDF por correo. El servidor contesta `{ ok: true }`, o dice dónde falta configurar el SMTP. */
  enviarPorCorreo: (id: number, email: string) =>
    api.post<{ ok: boolean }>(`/api/comprobantes/${id}/enviar-email`, { email }),
  anular: (id: number) => api.del<Comprobante>(`/api/comprobantes/${id}`),
  // La nota de crédito de un comprobante con CAE: **total** sin `importe`, **parcial** con él (con IVA, como
  // texto: no pasa por un float). Sin fecha ni tipo: la nota es de hoy y de la letra del original; los decide el
  // servidor (y el motor), igual que el tope del importe. Contra homologación contesta un `Ensayo` y no guarda
  // nada, igual que `facturar`.
  notaDeCredito: (id: number, motivo: string, importe?: string) =>
    api.post<Comprobante | Ensayo>(`/api/comprobantes/${id}/nota-de-credito`,
      importe === undefined ? { motivo } : { motivo, importe }),
  // La nota de débito (ADR-048): **siempre por un importe** (con IVA, como texto) y sin tope. Sin fecha ni tipo: es de hoy y
  // de la letra de la factura. Contra homologación contesta un `Ensayo` y no guarda nada.
  notaDeDebito: (id: number, motivo: string, importe: string) =>
    api.post<Comprobante | Ensayo>(`/api/comprobantes/${id}/nota-de-debito`, { motivo, importe }),
  // Facturar directo por ARCA, sin pre factura (ADR-048): las órdenes de un cliente, o conceptos libres.
  // Contra homologación contestan un `Ensayo` (200) y no guardan nada.
  facturarOrdenes: (datos: FacturarOrdenes) =>
    api.post<Comprobante | Ensayo>('/api/comprobantes/desde-ordenes', datos),
  facturarDirecta: (datos: FacturaDirecta) =>
    api.post<Comprobante | Ensayo>('/api/comprobantes/directa', datos),
  tipos: (clienteId?: number) =>
    api.get<OpcionesDeTipo>(`/api/comprobantes/tipos${clienteId ? `?cliente_id=${clienteId}` : ''}`),
}
