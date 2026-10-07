import { api } from 'libra-ui/api-client'

import { formatearFechaHora, formatearFechaHoraDeTexto } from '@/components/esquema-orden'

/** Cartas de Porte Electrónicas (CPE) que ARCA informa al transportista: se traen por su CTG, se guardan y se
 *  vinculan a una orden de carga (ADR-036). El prefijo es `/api/cartas-porte` y exige sesión de staff. */

/** Un CUIT de la CPE con el nombre del tercero cargado, si lo hay. */
export type Parte = { cuit: string | null; nombre: string | null }

export type CartaPorte = {
  /** `null` en la vista previa: todavía no está guardada. */
  id: number | null
  nro_ctg: number
  /** `00001-00072413`: sucursal y número de orden de la CPE. */
  numero: string
  /** El código de ARCA (`AC`, `CN`…) y cómo se lee (`Activa`, `Confirmada`…). */
  estado: string
  estado_descripcion: string
  fecha_emision: string | null
  fecha_vencimiento: string | null
  fecha_partida: string | null
  cuit_representada: string
  ambiente: Ambiente
  transportista: Parte
  pagador_flete: Parte
  chofer: Parte
  origen: Parte
  destino: Parte
  destinatario: Parte
  dominios: string[]
  cod_grano: number | null
  cosecha: number | null
  /** Kilos, enteros. `null` mientras ARCA no los informa (los de descarga, hasta que el camión descarga). */
  peso_bruto: number | null
  peso_tara: number | null
  peso_neto: number | null
  peso_bruto_descarga: number | null
  peso_tara_descarga: number | null
  peso_neto_descarga: number | null
  cod_provincia_origen: number | null
  cod_localidad_origen: number | null
  cod_provincia_destino: number | null
  cod_localidad_destino: number | null
  planta_destino: number | null
  km: number | null
  /** Decimal como texto, como todo importe de este producto. */
  tarifa: string | null
  tiene_pdf: boolean
  tiene_descarga: boolean
  consultada_en: string | null
  orden_carga_id: number | null
  /** En la vista previa: el `id` con que ya está guardada, si lo está. */
  guardada_id: number | null
}

export type Ambiente = 'produccion' | 'homologacion'

export type Representado = { cuit: string; nombre: string | null }
export type Representados = { ambiente: Ambiente; cuits: Representado[] }

/** Lo que pasó con cada CTG al traerlos: o quedó guardado (`id`) o dice por qué no (`error`). */
export type ResultadoDeTraer = { ctg: number; id: number | null; error: string | null }

export type ResumenDeActualizar = { actualizadas: number; errores: { ctg: number; error: string }[] }

/** El tope de CTG por pedido, el mismo del backend. */
export const MAX_CTGS = 50

export const cartasPorte = {
  /** 409 si no hay certificado cargado; 502 si ARCA no da acceso. El `detail` dice qué hacer. */
  representados: () => api.get<Representados>('/api/cartas-porte/representados'),
  /** La vista previa: no guarda nada. 404 si ARCA no la tiene, 409 si el CUIT no tiene delegación. */
  consultar: (ctg: number, cuitRepresentada: string) =>
    api.post<CartaPorte>('/api/cartas-porte/consultar', { ctg, cuit_representada: cuitRepresentada }),
  /** Guarda de a uno cada CTG y informa el error de cada uno que no se pudo. `orden_carga_id` sólo con un único CTG. */
  traer: (ctgs: number[], cuitRepresentada: string, ordenCargaId?: number | null) =>
    api.post<ResultadoDeTraer[]>('/api/cartas-porte', {
      ctgs,
      cuit_representada: cuitRepresentada,
      ...(ordenCargaId != null ? { orden_carga_id: ordenCargaId } : {}),
    }),
  listar: (filtros: { abiertas?: boolean } = {}) =>
    api.get<CartaPorte[]>(`/api/cartas-porte${filtros.abiertas ? '?abiertas=true' : ''}`),
  ver: (id: number) => api.get<CartaPorte>(`/api/cartas-porte/${id}`),
  /** Vuelve a consultar ARCA con el mismo CUIT y ambiente con que se trajo. */
  actualizar: (id: number) => api.post<CartaPorte>(`/api/cartas-porte/${id}/actualizar`, {}),
  actualizarAbiertas: () => api.post<ResumenDeActualizar>('/api/cartas-porte/actualizar-abiertas', {}),
  /** `null` desvincula. 404 si la orden no existe. */
  vincular: (id: number, ordenCargaId: number | null) =>
    api.put<CartaPorte>(`/api/cartas-porte/${id}/orden`, { orden_carga_id: ordenCargaId }),
  /** El PDF que devolvió ARCA: se abre en otra pestaña, la sesión viaja en la cookie. */
  urlDelPdf: (id: number) => `/api/cartas-porte/${id}/pdf`,
}

// ── Estado ────────────────────────────────────────────────────────────────

/** Los estados en que una CPE ya no cambia (los mismos que `ESTADOS_CERRADOS` del backend). */
const ESTADOS_FINALES = ['AN', 'RE', 'DE']

/** El tono de la pastilla de cada estado de ARCA (los cinco de `libra-ui/badge-estado`). Un código que no se
 *  conoce queda neutro: el texto de la pastilla es la descripción que manda el backend. */
export function tonoDeEstado(estado: string): 'neutro' | 'curso' | 'atencion' | 'ok' | 'negativo' {
  if (ESTADOS_FINALES.includes(estado)) return 'negativo'
  if (estado === 'DD') return 'ok'
  if (estado === 'CO') return 'atencion'
  if (estado === 'AC' || estado === 'CF' || estado === 'CN') return 'curso'
  return 'neutro'
}

export const esEstadoFinal = (estado: string) => ESTADOS_FINALES.includes(estado)

// ── CUIT y CTG ────────────────────────────────────────────────────────────

/** `30222222223` → `30-22222222-3`. Lo que no son once dígitos vuelve tal cual: inventar guiones en otra cosa sería peor. */
export function formatearCuit(cuit: string | null | undefined): string {
  const digitos = (cuit ?? '').replace(/\D/g, '')
  return digitos.length === 11 ? `${digitos.slice(0, 2)}-${digitos.slice(2, 10)}-${digitos.slice(10)}` : (cuit ?? '')
}

/** Máscara de un CUIT mientras se escribe: deja sólo dígitos (hasta once) y pone los guiones donde van.
 *  `2012345678` → `20-12345678`; `20123456786` → `20-12345678-6`. */
export function enmascararCuit(texto: string): string {
  const d = texto.replace(/\D/g, '').slice(0, 11)
  if (d.length <= 2) return d
  if (d.length <= 10) return `${d.slice(0, 2)}-${d.slice(2)}`
  return `${d.slice(0, 2)}-${d.slice(2, 10)}-${d.slice(10)}`
}

/** El nombre del tercero, o su CUIT formateado, o `—`. */
export function nombreOCuit(parte: Parte | null | undefined): string {
  if (!parte) return '—'
  return parte.nombre?.trim() || formatearCuit(parte.cuit) || '—'
}

export type CtgsLeidos = {
  /** Los de once dígitos, sin repetir y en el orden en que se escribieron. */
  validos: number[]
  /** Lo escrito que no es un CTG (no son once dígitos). */
  invalidos: string[]
  /** Cuántos estaban repetidos y se quitaron. */
  repetidos: number
  /** Más de {@link MAX_CTGS}. */
  excede: boolean
}

/** Lee el campo «CTG»: uno o varios, separados por espacio, coma, punto y coma o renglón. */
export function leerCtgs(texto: string): CtgsLeidos {
  const validos: number[] = []
  const invalidos: string[] = []
  let repetidos = 0
  for (const palabra of texto.split(/[\s,;]+/).filter(Boolean)) {
    if (!/^\d{11}$/.test(palabra)) {
      if (!invalidos.includes(palabra)) invalidos.push(palabra)
      continue
    }
    const ctg = Number(palabra)
    if (validos.includes(ctg)) repetidos += 1
    else validos.push(ctg)
  }
  return { validos, invalidos, repetidos, excede: validos.length > MAX_CTGS }
}

// ── Kilos y fechas ────────────────────────────────────────────────────────

/** `24500` → `24.500`. Sobre el texto, como `formatearImporte`: son enteros y no hay nada que redondear. */
export function formatearKilos(kilos: number | null | undefined): string {
  return kilos == null ? '—' : String(kilos).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

/** Un instante con zona (`2026-10-05T14:30:00-03:00`, `…Z`) se pasa a la hora de Argentina; uno sin zona es reloj de
 *  pared y se reordena como texto, sin pasarlo por `Date` (que lo reinterpretaría en la zona del navegador). */
export function formatearInstante(valor: string | null | undefined): string {
  if (!valor) return '—'
  if (/T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(valor)) {
    const instante = new Date(valor)
    if (!Number.isNaN(instante.getTime())) return formatearFechaHora(instante)
  }
  return formatearFechaHoraDeTexto(valor)
}

/** Sólo el día de {@link formatearInstante}: `dd-mm-aaaa`. */
export function formatearDiaDelInstante(valor: string | null | undefined): string {
  return valor ? formatearInstante(valor).slice(0, 10) : '—'
}
