import { api } from 'libra-ui/api-client'

import type { Comprobante, CuentaFce, Ensayo, TipoComprobante } from '@/api/comprobantes'

/** Los cinco estados de una pre factura, como los guarda el motor (ADR-030 de LibraCore). */
export type EstadoPreFactura = 'pendiente' | 'enviado' | 'aceptado' | 'facturado' | 'descartado'

/** Cómo se leen en pantalla. El motor los guarda en masculino (`enviado`, `descartado`); acá se dicen como
 *  el operador los dice: una pre factura **Enviada**, **Aceptada**, **Facturada**, **Anulada**. */
export const NOMBRE_DE_ESTADO: Record<EstadoPreFactura, string> = {
  pendiente: 'Pendiente', enviado: 'Enviada', aceptado: 'Aceptada',
  facturado: 'Facturada', descartado: 'Anulada',
}

/** El tono de la pastilla de cada estado (los cinco de `libra-ui/badge-estado`). */
export const TONO_DE_ESTADO: Record<EstadoPreFactura, 'neutro' | 'curso' | 'atencion' | 'ok' | 'negativo'> = {
  pendiente: 'neutro', enviado: 'curso', aceptado: 'atencion', facturado: 'ok', descartado: 'negativo',
}

/** Abiertas: las que todavía se pueden editar, enviar, aceptar, anular y facturar. */
export const ESTADOS_ABIERTOS: EstadoPreFactura[] = ['pendiente', 'enviado', 'aceptado']

/** El código de ARCA con que el motor guarda el tipo, al nombre que usa este producto. */
export const TIPO_DE_CODIGO: Record<number, TipoComprobante> = {
  1: 'factura_a', 6: 'factura_b', 11: 'factura_c', 201: 'fce_a', 206: 'fce_b', 211: 'fce_c',
}

export type ItemPreFactura = {
  description: string
  detalle: string
  qty: number
  unit_price: number
  /** Una fracción (`0.21`), no un porcentaje. */
  iva_rate: number
  orden_id: number | null
}

export type PreFactura = {
  id: number
  /** `PF-0001`: el número interno, que no es fiscal. */
  numero_interno: string
  estado: EstadoPreFactura
  cliente_id: number | null
  cliente_razon: string
  cliente_cuit: string
  tipo_comprobante: number | null
  fecha_sugerida: string
  fecha_vencimiento_pago: string | null
  /** Sólo una FCE: el CBU de la cuenta elegida, o `null` si va la predeterminada. */
  fce_cbu?: string | null
  /** Sólo una FCE: dónde se cobra (la elegida o la predeterminada), o `null`. */
  fce_cuenta?: CuentaFce | null
  observaciones: string
  items: ItemPreFactura[]
  orden_ids: number[]
  /** Con dos decimales y como texto en lo que arma este producto; el motor puede devolverlo como número. */
  total: string | number
  enviado_at: string | null
  enviado_a: string | null
  aceptado_at: string | null
  aceptado_por: string | null
  /** La factura que la cubrió, si está facturada. */
  factura_id: number | null
  motivo_descarte: string | null
  resuelto_por: string | null
  resuelto_at: string | null
  created_at: string
}

export type ListadoPreFacturas = {
  items: PreFactura[]
  counts: Record<EstadoPreFactura, number>
}

/** Lo que elige el operador. Los ítems y los importes **no viajan**: salen de las órdenes. Y tampoco el
 *  punto de venta ni el número: la pre factura tiene el suyo y el de la factura lo pone ARCA. */
export type DatosDePreFactura = {
  tipo: string
  fecha: string
  fecha_vencimiento_pago?: string
  /** Sólo una FCE: el CBU o el alias de la cuenta; `''` es la predeterminada. */
  fce_cbu?: string
  orden_ids: number[]
}

export const tipoDe = (p: PreFactura): TipoComprobante | null =>
  p.tipo_comprobante == null ? null : (TIPO_DE_CODIGO[p.tipo_comprobante] ?? null)

export const preFacturas = {
  listar: (filtros: { estado?: string; cliente?: string } = {}) => {
    const p = new URLSearchParams()
    for (const [k, v] of Object.entries(filtros)) if (v) p.set(k, v)
    const qs = p.toString()
    return api.get<ListadoPreFacturas>(`/api/pre-facturas${qs ? `?${qs}` : ''}`)
  },
  ver: (id: number) => api.get<PreFactura>(`/api/pre-facturas/${id}`),
  crear: (datos: DatosDePreFactura & { cliente_id: number }) =>
    api.post<PreFactura>('/api/pre-facturas', datos),
  editar: (id: number, datos: DatosDePreFactura) =>
    api.put<PreFactura>(`/api/pre-facturas/${id}`, datos),
  /** Lo marca el operador cuando el cliente contesta que está de acuerdo. */
  aceptar: (id: number) => api.post<PreFactura>(`/api/pre-facturas/${id}/aceptar`, {}),
  anular: (id: number, motivo: string) =>
    api.post<PreFactura>(`/api/pre-facturas/${id}/anular`, { motivo }),
  enviarPorCorreo: (id: number, email: string) =>
    api.post<PreFactura>(`/api/pre-facturas/${id}/enviar-email`, { email }),
  // 🔑 La unión no es cosmética (igual que antes en `comprobantes.facturar`): contra homologación el backend
  // corre todo y revierte, y contesta un `Ensayo` que **no tiene `id`**. Obliga a quien llame a decidir
  // cuál de los dos recibió antes de tocar `.id`.
  facturar: (id: number, fecha?: string) =>
    api.post<Comprobante | Ensayo>(`/api/pre-facturas/${id}/facturar`, fecha ? { fecha } : {}),
  /** El PDF se abre y se baja por un enlace común: la sesión viaja en la cookie. */
  urlDelPdf: (id: number) => `/api/pre-facturas/${id}/pdf`,
}
