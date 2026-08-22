import { api } from 'libra-ui/api-client'

export type Registro = {
  id: number
  ts: string
  usuario_id: number | null
  usuario_nombre: string | null
  entidad: string
  entidad_id: number | null
  accion: 'alta' | 'modificacion' | 'baja'
  /** El diff, no la fila entera: sólo las columnas que cambiaron. Los importes
   *  vienen como STRING — un log de auditoría donde el importe pasó por `float`
   *  no sirve de prueba. */
  datos_antes: Record<string, unknown> | null
  datos_despues: Record<string, unknown> | null
}

export type PaginaDeLog = {
  /** El total SIN paginar: sin esto la pantalla no puede decir "1 a 50 de
   *  15.884", y un listado que no dice cuánto hay se lee como si fuera todo. */
  total: number
  registros: Registro[]
}

export type FiltrosDeLog = {
  entidad?: string
  entidad_id?: number
  usuario?: string
  accion?: string
  desde?: string
  hasta?: string
  limite?: number
  desplazamiento?: number
}

function consulta(filtros: FiltrosDeLog): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(filtros)) {
    if (v != null && v !== '') p.set(k, String(v))
  }
  const qs = p.toString()
  return qs ? `?${qs}` : ''
}

/** Un evento de acceso. **La misma forma que el `AccesoLog` de `libra-ui`**,
 *  que es la que rinde la pantalla compartida en los otros cinco productos: si
 *  esto divergiera, la pestaña de acá se vería distinta sin que nadie lo
 *  hubiera decidido. */
export type Acceso = {
  id: number
  ts: string
  evento: 'login' | 'logout' | 'login_fallido' | string
  username: string
  ip: string
  detalle: string
}

export const auditoria = {
  listar: (filtros: FiltrosDeLog = {}) =>
    api.get<PaginaDeLog>(`/api/auditoria${consulta(filtros)}`),
  entidades: () => api.get<string[]>('/api/auditoria/entidades'),
  usuarios: () => api.get<string[]>('/api/auditoria/usuarios'),
  //  Los accesos no se paginan ni se filtran: son la segunda mitad de la
  //  pantalla y llegan enteros, igual que en el router del motor.
  accesos: () => api.get<Acceso[]>('/api/auditoria/accesos'),
}

/** El diff en una línea legible: `tarifa: 1000.00 → 1200.00`.
 *
 * Se arma sobre la unión de las dos partes, no sobre `datos_despues`: en una
 * baja hay campos que existen antes y no después, y mirar un solo lado los
 * perdería. */
export function describirCambio(r: Registro): string {
  const antes = r.datos_antes ?? {}
  const despues = r.datos_despues ?? {}
  const claves = [...new Set([...Object.keys(antes), ...Object.keys(despues)])].sort()
  if (claves.length === 0) return ''
  return claves
    .map((k) => {
      const a = antes[k]
      const d = despues[k]
      if (r.accion === 'alta') return `${k}: ${d ?? ''}`
      if (a === undefined) return `${k}: → ${d ?? ''}`
      if (d === undefined) return `${k}: ${a ?? ''} →`
      return `${k}: ${a ?? ''} → ${d ?? ''}`
    })
    .join(' · ')
}
