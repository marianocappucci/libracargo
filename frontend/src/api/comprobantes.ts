import { api } from 'libra-ui/api-client'

import type { Orden } from '@/api/ordenes'

export type TipoComprobante =
  | 'factura_a' | 'factura_b' | 'factura_c'
  | 'nota_credito_a' | 'nota_credito_b' | 'nota_credito_c'

/** Lo que devuelve facturar cuando el ambiente de ARCA es homologación.
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
}

export type SumaDeOrdenes = { cantidad: number; neto: string; iva: string; total: string }

export type ComprobanteConOrdenes = {
  comprobante: Comprobante
  ordenes: Orden[]
  suma_de_ordenes: SumaDeOrdenes
  /** Si el encabezado dice lo mismo que sus ordenes. */
  coinciden: boolean
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
  // 🔑 La unión no es cosmética: obliga a quien llame a **decidir cuál de
  // los dos recibió** antes de tocar `.id`. Con `Comprobante` a secas,
  // TypeScript deja leer el id de un ensayo —que no lo tiene— y el error
  // aparece recién en pantalla, como una navegación a la nada.
  facturar: (datos: unknown) =>
    api.post<Comprobante | Ensayo>('/api/comprobantes', datos),
  anular: (id: number) => api.del<Comprobante>(`/api/comprobantes/${id}`),
}
