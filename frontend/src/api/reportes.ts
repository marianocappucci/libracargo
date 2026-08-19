import { api } from 'libra-ui/api-client'

/** Los importes viajan como STRING: son `NUMERIC` en la base y `Decimal` en
 *  Python. Pasarlos por `number` los mete en un float binario. */
export type Resumen = {
  desde: string | null
  hasta: string | null
  ordenes: number
  ordenes_anuladas: number
  ordenes_pendientes: number
  tarifa: string
  iva: string
  total: string
  comision: string
  comprobantes: number
  facturado: string
  movimientos_caja: number
  cobrado: string
  pagado: string
}

export type FilaDeTercero = {
  tercero_id: number
  tercero: string
  ordenes: number
  facturado: string
  comision: string
  /** NO acotado al rango: lo facturado en el período y lo que el tercero debe
   *  son dos preguntas distintas. */
  saldo: string
}

export type FilaDeSaldo = {
  tercero_id: number
  rol: 'cliente' | 'fletero' | 'proveedor'
  tercero: string
  movimientos: number
  ultimo_movimiento: string | null
  saldo: string
}

export type FilaDeCaja = {
  tipo: 'ingreso' | 'egreso'
  medio_pago: string
  movimientos: number
  importe: string
}

export type FilaDeRazonSocial = {
  razon_social_id: number
  razon_social: string
  comprobantes: number
  neto: string
  iva: string
  total: string
}

export type FilaDeRuta = {
  origen: string
  destino: string
  ordenes: number
  total: string
  comision: string
  cantidad: string
}

function consulta(filtros: Record<string, string | number | boolean | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(filtros)) {
    if (v != null && v !== '') p.set(k, String(v))
  }
  const qs = p.toString()
  return qs ? `?${qs}` : ''
}

type Rango = { desde?: string; hasta?: string }

export const reportes = {
  resumen: (r: Rango = {}) => api.get<Resumen>(`/api/reportes/resumen${consulta(r)}`),
  porCliente: (r: Rango = {}) =>
    api.get<FilaDeTercero[]>(`/api/reportes/por-cliente${consulta(r)}`),
  porFletero: (r: Rango = {}) =>
    api.get<FilaDeTercero[]>(`/api/reportes/por-fletero${consulta(r)}`),
  saldos: (rol?: string, incluirEnCero = false) =>
    api.get<FilaDeSaldo[]>(
      `/api/reportes/saldos${consulta({ rol, incluir_en_cero: incluirEnCero || undefined })}`),
  caja: (r: Rango = {}) => api.get<FilaDeCaja[]>(`/api/reportes/caja${consulta(r)}`),
  porRazonSocial: (r: Rango = {}) =>
    api.get<FilaDeRazonSocial[]>(`/api/reportes/por-razon-social${consulta(r)}`),
  porRuta: (r: Rango = {}) => api.get<FilaDeRuta[]>(`/api/reportes/por-ruta${consulta(r)}`),
}
