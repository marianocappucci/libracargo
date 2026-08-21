import { api } from 'libra-ui/api-client'

export type Rol = 'cliente' | 'fletero' | 'proveedor'

export type MovimientoCuenta = {
  id: number
  fecha: string
  tercero_id: number
  rol: Rol
  concepto: string
  descripcion: string | null
  // Importes como STRING: son `NUMERIC` en la base y `Decimal` en Python.
  // Pasarlos por `number` los mete en un float binario.
  debe: string
  haber: string
  orden_id: number | null
  comprobante_id: number | null
  movimiento_caja_id: number | null
  gasto_id: number | null
}

export type FilaDeCuenta = { movimiento: MovimientoCuenta; saldo: string }

export type ResumenDeCuenta = {
  tercero_id: number
  rol: Rol
  /** Agregado por la base con un SUM. */
  saldo: string
  /** El mismo numero acumulado fila por fila. Vienen los dos a proposito: si
   *  difieren, el saldo depende de donde se hizo la cuenta. */
  saldo_recorriendo: string
  coinciden: boolean
  movimientos: FilaDeCuenta[]
}

export type MovimientoCaja = {
  id: number
  fecha: string
  tipo: 'ingreso' | 'egreso'
  concepto: string
  descripcion: string | null
  tercero_id: number | null
  importe: string
  medio_pago: 'efectivo' | 'transferencia' | 'cheque' | 'otro'
  recibo: string | null
}

export const cuentas = {
  ver: (rol: Rol, terceroId: number, hasta?: string) =>
    api.get<ResumenDeCuenta>(
      `/api/cuentas/${rol}/${terceroId}${hasta ? `?hasta=${hasta}` : ''}`,
    ),
}

export const caja = {
  listar: (filtros: Record<string, string | number | undefined> = {}) => {
    const p = new URLSearchParams()
    // `!= null` y no `if (v)`: el cero es un id valido y una cadena vacia ya
    // se descarta aparte.
    for (const [k, v] of Object.entries(filtros)) {
      if (v != null && v !== '') p.set(k, String(v))
    }
    const qs = p.toString()
    return api.get<MovimientoCaja[]>(`/api/caja${qs ? `?${qs}` : ''}`)
  },
  registrar: (datos: unknown) => api.post<MovimientoCaja>('/api/caja', datos),
}
