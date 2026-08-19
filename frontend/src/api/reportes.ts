import { api } from 'libra-ui/api-client'

/** Una entrada del catálogo, tal como la devuelve el backend.
 *
 * 🔑 **El catálogo lo manda el servidor**, no una lista repetida acá. Si los dos
 * se separan, la pantalla ofrece un filtro que el reporte ya no acepta —o
 * esconde uno que sí—. */
export type Reporte = {
  slug: string
  titulo: string
  descripcion: string
  parametros: Parametro[]
}

export type Parametro =
  | 'rango' | 'cliente' | 'fletero' | 'tercero' | 'razon_social'
  | 'origen' | 'destino' | 'medio_pago' | 'tipo_caja' | 'rol'
  | 'incluir_en_cero' | 'limite'

/** Los importes viajan como STRING: son `NUMERIC` en la base y `Decimal` en
 *  Python. Pasarlos por `number` los mete en un float binario. */
export type Resumen = {
  desde: string | null
  hasta: string | null
  cliente_id: number | null
  fletero_id: number | null
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
  tercero_id: number; tercero: string; ordenes: number
  facturado: string; comision: string
  /** NO acotado al rango: el saldo no tiene período. */
  saldo: string
}

export type FilaDeSaldo = {
  tercero_id: number; rol: string; tercero: string
  movimientos: number; ultimo_movimiento: string | null; saldo: string
}

export type FilaDeCaja = {
  tipo: string; medio_pago: string; movimientos: number; importe: string
}

export type FilaDeRazonSocial = {
  razon_social_id: number; razon_social: string
  comprobantes: number; neto: string; iva: string; total: string
}

export type FilaDeRuta = {
  origen: string; destino: string; ordenes: number
  total: string; comision: string; cantidad: string
}

export type FilaDePendiente = {
  cliente_id: number; cliente: string; ordenes: number
  desde: string | null; hasta: string | null; total: string
}

export type ValoresDeFiltro = Record<string, string | number | boolean | undefined>

export function consulta(filtros: ValoresDeFiltro): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(filtros)) {
    // `!= null` a propósito: conserva `false` y `0`. Con un `if (v)` el filtro
    // `incluir_en_cero=false` se perdería, que es distinto de no filtrar.
    if (v != null && v !== '') p.set(k, String(v))
  }
  const qs = p.toString()
  return qs ? `?${qs}` : ''
}

export const reportes = {
  catalogo: () => api.get<Reporte[]>('/api/reportes'),
  /** Un reporte cualquiera, por slug. Devuelve lo que devuelva: la pantalla sabe
   *  qué columnas mostrar, y el backend qué calcular. */
  correr: <T>(slug: string, filtros: ValoresDeFiltro = {}) =>
    api.get<T>(`/api/reportes/${slug}${consulta(filtros)}`),
  resumen: (filtros: ValoresDeFiltro = {}) =>
    api.get<Resumen>(`/api/reportes/resumen${consulta(filtros)}`),
  saldos: (filtros: ValoresDeFiltro = {}) =>
    api.get<FilaDeSaldo[]>(`/api/reportes/saldos${consulta(filtros)}`),
}
