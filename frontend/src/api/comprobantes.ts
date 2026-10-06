import { api } from 'libra-ui/api-client'

import type { Orden } from '@/api/ordenes'

export type TipoComprobante =
  | 'factura_a' | 'factura_b' | 'factura_c'
  | 'nota_credito_a' | 'nota_credito_b' | 'nota_credito_c'
  // Factura de Crédito Electrónica MiPyME, y su nota de crédito (sólo parcial: ARCA no deja
  // anularla entera si el comprador no la rechazó).
  | 'fce_a' | 'fce_b' | 'fce_c'
  | 'nota_credito_fce_a' | 'nota_credito_fce_b' | 'nota_credito_fce_c'

/** Lo que devuelve facturar una pre factura (`preFacturas.facturar`) cuando el ambiente de ARCA es homologación.
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
  razon_social_id: number
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
  // Sólo una nota de crédito los tiene: a qué comprobante acredita y por qué.
  comprobante_asociado_id?: number | null
  motivo?: string | null
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
  /** Si esta razón social ya puede emitir FCE (emite por ARCA y cargó CBU y modalidad). */
  fce_habilitada: boolean
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
  /** Lo acreditado por sus notas con CAE y lo que queda (lo cuenta el motor). `null` si no admite nota. */
  acreditado?: string | null
  saldo_acreditable?: string | null
}

export type TotalDeRazonSocial = {
  razon_social_id: number | null
  cantidad_comprobantes: number
  neto_comprobantes: string
  iva_comprobantes: string
  total_comprobantes: string
  cantidad_ordenes: number
  neto_ordenes: string
  iva_ordenes: string
  total_ordenes: string
  coinciden: boolean
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
    return api.get<TotalDeRazonSocial[]>(`/api/comprobantes/totales${qs ? `?${qs}` : ''}`)
  },
  // ¿A este comprobante le corresponde ser FCE? Lo contesta el registro de ARCA a través del motor. Es un
  // aviso: nunca falla por ARCA (`disponible: false` y el motivo).
  fceCorresponde: (p: { razon_social_id: number; cliente_id: number; total: string; fecha: string }) =>
    api.get<AvisoFce>(`/api/comprobantes/fce/corresponde?${new URLSearchParams({
      razon_social_id: String(p.razon_social_id), cliente_id: String(p.cliente_id),
      total: p.total, fecha: p.fecha,
    })}`),
  anular: (id: number) => api.del<Comprobante>(`/api/comprobantes/${id}`),
  // La nota de crédito de un comprobante con CAE: **total** sin `importe`, **parcial** con él (con IVA, como
  // texto: no pasa por un float). Sin fecha ni tipo: la nota es de hoy y de la letra del original; los decide el
  // servidor (y el motor), igual que el tope del importe. Contra homologación contesta un `Ensayo` y no guarda
  // nada, igual que `facturar`.
  notaDeCredito: (id: number, motivo: string, importe?: string) =>
    api.post<Comprobante | Ensayo>(`/api/comprobantes/${id}/nota-de-credito`,
      importe === undefined ? { motivo } : { motivo, importe }),
}
