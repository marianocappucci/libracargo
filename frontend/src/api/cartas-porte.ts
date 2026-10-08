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
  /** Desde cuándo está en ese estado (ISO con zona), o `null` si no se sabe. El PDF que guardó ARCA es el de la
   *  emisión: una carta «Anulada» después sigue teniendo ese PDF, y la pantalla tiene que decir desde cuándo es anulada. */
  fecha_inicio_estado: string | null
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
  /** `true` si la emitió este sistema (ADR-043) y no sólo la trajo de ARCA: sólo esas se anulan desde acá. Si el
   *  backend no lo manda, queda `undefined` y la pantalla no ofrece anular. */
  emitida?: boolean
}

export type Ambiente = 'produccion' | 'homologacion'

export type Representado = { cuit: string; nombre: string | null }
export type Representados = { ambiente: Ambiente; cuits: Representado[] }

/** Lo que pasó con cada CTG al traerlos: o quedó guardado (`id`) o dice por qué no (`error`). */
export type ResultadoDeTraer = { ctg: number; id: number | null; error: string | null }

export type ResumenDeActualizar = { actualizadas: number; errores: { ctg: number; error: string }[] }

// ── Emitir desde la orden (ADR-043) ──────────────────────────────────────

export type EstadoDeEmision = {
  /** `null` si no hay certificado de «CTG y Carta de Porte» cargado. */
  ambiente: Ambiente | null
  habilitada: boolean
  puede_emitir: boolean
}

export type OpcionDeArca = { codigo: number; nombre: string }
export type Planta = { numero: number; cod_provincia: number; cod_localidad: number }

export type OrigenPropuesto = {
  tipo: 'campo' | 'planta'
  cod_provincia?: number | null
  cod_localidad?: number | null
  planta?: number | null
  renspa?: string | null
}

export type DestinoPropuesto = {
  cuit?: string | null
  cod_provincia?: number | null
  cod_localidad?: number | null
  planta?: number | null
  es_campo?: boolean
}

export type TransportePropuesto = {
  cuit_transportista: string | null
  dominios: string[]
  /** ISO con zona (`…-03:00`); la propuesta lo manda vacío porque la partida la decide quien emite. */
  fecha_hora_partida: string | null
  km: number | null
  cuit_chofer: string | null
  cuit_pagador_flete: string | null
  /** Decimal como texto, por tonelada. */
  tarifa: string | null
  mercaderia_fumigada: boolean
  cuit_intermediario_flete?: string | null
}

export type Propuesta = {
  orden_id: number
  cuit_titular: string
  sucursal: number
  origen: OrigenPropuesto
  cod_grano: number | null
  cosecha: number | null
  peso_bruto: number | null
  peso_tara: number | null
  destino: DestinoPropuesto
  cuit_destinatario: string | null
  intervinientes: Record<string, string | null>
  cuit_remitente_comercial_productor: string | null
  transporte: TransportePropuesto
  observaciones: string | null
  /** Se completó con lo último emitido para ese titular. */
  de_plantilla: boolean
  /** Lo que no se pudo completar y hay que cargar, ya dicho en castellano. */
  faltantes: string[]
}

/** Lo que se manda a emitir: la propuesta, editada. Sin `orden_id`, `faltantes` ni `de_plantilla`, que no son datos. */
export type DatosDeEmision = Omit<Propuesta, 'orden_id' | 'faltantes' | 'de_plantilla'>

export type Enlace = { url: string; vence: string }

// ── Titulares (ADR-044) ──────────────────────────────────────────────────

/** Quién emite la carta de porte de un titular: este sistema (por la delegación del titular en ARCA) o él. */
export type QuienEmite = 'nosotros' | 'titular'

/** Lo que ARCA dice de la delegación de un titular, leído del ticket de `wscpe` y nunca tildado a mano:
 *  `delegado` (está en el ticket), `pendiente` (cargado y ARCA todavía no lo trae), `sin_verificar` (no hay certificado
 *  o ARCA no contestó) y `no_aplica` (emite él: no hay delegación que mirar). */
export type Delegacion = 'delegado' | 'pendiente' | 'sin_verificar' | 'no_aplica'

export type EntidadVinculada = { id: number; razon_social: string }

export type Titular = {
  id: number
  /** Once dígitos, sin guiones. */
  cuit: string
  razon_social: string
  emite: QuienEmite
  activo: boolean
  notas: string | null
  delegacion: Delegacion
  /** La entidad de Entidades con que se vincula (la elegida o la que tiene su CUIT), o `null`. */
  tercero: EntidadVinculada | null
  tiene_plantilla: boolean
}

/** Un CUIT que el ticket de ARCA trae y no está cargado: «Delegado sin cargar». */
export type TitularSinCargar = { cuit: string; tercero: EntidadVinculada | null }

export type ListadoDeTitulares = {
  /** `null` si no hay certificado de `wscpe` cargado. */
  ambiente: Ambiente | null
  /** `false`: no se pudo leer el ticket de ARCA; `motivo` dice por qué y los estados vienen `sin_verificar`. */
  verificado: boolean
  motivo: string | null
  /** Un CUIT por el que el ticket deja operar: los catálogos de ARCA se piden con él cuando el titular no está delegado. */
  cuit_para_catalogos: string | null
  titulares: Titular[]
  sin_cargar: TitularSinCargar[]
}

export type DatosDeTitular = {
  cuit: string
  razon_social?: string | null
  tercero_id?: number | null
  emite: QuienEmite
  activo: boolean
  notas?: string | null
}

export type EdicionDeTitular = Omit<DatosDeTitular, 'cuit' | 'razon_social'> & { razon_social: string }

/** Lo que `propuesta()` lee de la plantilla del titular; mismas claves que `DatosDeEmision`. Todo es opcional. */
export type DatosDePlantilla = {
  sucursal?: number
  origen?: OrigenPropuesto
  cod_grano?: number
  cosecha?: number
  destino?: DestinoPropuesto
  cuit_destinatario?: string
  intervinientes?: Record<string, string | null>
  cuit_remitente_comercial_productor?: string
  mercaderia_fumigada?: boolean
  km?: number
  observaciones?: string
}

export type PlantillaGuardada = { datos: DatosDePlantilla; existe: boolean; actualizada: string | null }

/** El titular de una entidad con el estado de su delegación, o `null` si no es titular. `motivo`: por qué no se verificó. */
export type TitularDeEntidad = Titular & { motivo: string | null }

/** Del certificado de `wscpe` cargado: lo que el titular necesita para delegarnos. */
export type InstruccionesDeDelegacion = {
  disponible: boolean
  ambiente: Ambiente | null
  /** Nombre del computador fiscal (el CN del certificado). */
  alias: string | null
  /** CUIT del representante (el del certificado), once dígitos. */
  cuit_representante: string | null
  motivo: string | null
}

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

  // ── Emitir (ADR-043) ──
  /** En qué ambiente se emitiría y si la emisión real está habilitada. */
  estadoDeEmision: () => api.get<EstadoDeEmision>('/api/cartas-porte/emision/estado'),
  /** Sólo un administrador. */
  habilitarEmision: (habilitada: boolean) =>
    api.put<EstadoDeEmision>('/api/cartas-porte/emision/habilitada', { habilitada }),
  propuesta: (ordenId: number, cuitTitular: string) =>
    api.get<Propuesta>(`/api/cartas-porte/emision/propuesta?orden_id=${ordenId}&cuit_titular=${cuitTitular}`),
  /** 🔴 Emite una Carta de Porte en ARCA. No se reintenta sola ni desde la pantalla ante un 502/500: ver el asistente. */
  emitir: (ordenId: number, confirmo: boolean, datos: DatosDeEmision) =>
    api.post<CartaPorte>('/api/cartas-porte/emision/emitir', { orden_id: ordenId, confirmo, datos }),
  /** Los catálogos de ARCA se piden en nombre del titular. */
  granos: (cuitTitular: string) =>
    api.get<OpcionDeArca[]>(`/api/cartas-porte/catalogos/granos?cuit_titular=${cuitTitular}`),
  provincias: (cuitTitular: string) =>
    api.get<OpcionDeArca[]>(`/api/cartas-porte/catalogos/provincias?cuit_titular=${cuitTitular}`),
  localidades: (cuitTitular: string, provincia: number) =>
    api.get<OpcionDeArca[]>(`/api/cartas-porte/catalogos/localidades?cuit_titular=${cuitTitular}&provincia=${provincia}`),
  /** Las plantas inscriptas de ese CUIT (el del destino). */
  plantas: (cuitTitular: string, cuit: string) =>
    api.get<Planta[]>(`/api/cartas-porte/catalogos/plantas?cuit_titular=${cuitTitular}&cuit=${cuit}`),
  /** Sólo un administrador, y sólo las emitidas desde acá. */
  anular: (id: number, observaciones?: string) =>
    api.post<CartaPorte>(`/api/cartas-porte/${id}/anular`, observaciones ? { observaciones } : {}),
  /** Un enlace firmado al PDF, que vence a los 7 días: para mandárselo al chofer, que no tiene usuario. */
  enlace: (id: number) => api.get<Enlace>(`/api/cartas-porte/${id}/enlace`),

  // ── Titulares (ADR-044) ──
  /** Siempre 200: sin certificado o con ARCA caída vuelve `verificado: false` y el motivo. */
  titulares: () => api.get<ListadoDeTitulares>('/api/cartas-porte/titulares'),
  /** Sólo un administrador. 409 si el CUIT ya está cargado. */
  crearTitular: (datos: DatosDeTitular) => api.post<Titular>('/api/cartas-porte/titulares', datos),
  editarTitular: (id: number, datos: EdicionDeTitular) =>
    api.put<Titular>(`/api/cartas-porte/titulares/${id}`, datos),
  /** Saca al titular de la lista; su plantilla queda. */
  borrarTitular: (id: number) => api.del<void>(`/api/cartas-porte/titulares/${id}`),
  plantilla: (id: number) => api.get<PlantillaGuardada>(`/api/cartas-porte/titulares/${id}/plantilla`),
  guardarPlantilla: (id: number, datos: DatosDePlantilla) =>
    api.put<PlantillaGuardada>(`/api/cartas-porte/titulares/${id}/plantilla`, { datos }),
  borrarPlantilla: (id: number) => api.del<void>(`/api/cartas-porte/titulares/${id}/plantilla`),
  instruccionesDeDelegacion: () =>
    api.get<InstruccionesDeDelegacion>('/api/cartas-porte/titulares/instrucciones'),
  /** Para la ficha del cliente: su titular, o `null`. */
  titularDeEntidad: (terceroId: number) =>
    api.get<TitularDeEntidad | null>(`/api/cartas-porte/titulares/de-tercero/${terceroId}`),
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

// ── Texto para compartir ──────────────────────────────────────────────────

/** Lo que se le manda al chofer: `Carta de porte 00001-00072413 · CTG 10123456781 · Origen → Destino · 29.500 kg ·
 *  320 km. PDF: https://…`. Lo que no se sabe se omite en vez de dejar un hueco. */
export function textoParaCompartir(
  carta: Pick<CartaPorte, 'numero' | 'nro_ctg' | 'peso_neto' | 'km'>, origen: string, destino: string, url: string,
): string {
  const tramo = origen && destino ? `${origen} → ${destino}` : origen || destino
  const partes = [
    `Carta de porte ${carta.numero}`, `CTG ${carta.nro_ctg}`, tramo,
    carta.peso_neto != null ? `${formatearKilos(carta.peso_neto)} kg` : '',
    carta.km != null ? `${carta.km} km` : '',
  ].filter(Boolean)
  return `${partes.join(' · ')}. PDF: ${url}`
}

/** El enlace de WhatsApp con el texto ya escrito: se abre y la persona elige a quién mandárselo. */
export const enlaceDeWhatsApp = (texto: string) => `https://wa.me/?text=${encodeURIComponent(texto)}`

// ── Titulares: cómo se leen ───────────────────────────────────────────────

/** El texto de la pastilla de cada estado de delegación. */
export function etiquetaDeDelegacion(d: Delegacion, emite: QuienEmite = 'nosotros'): string {
  if (d === 'delegado') return 'Delegado ✓'
  if (d === 'pendiente') return 'Pendiente'
  if (d === 'sin_verificar') return 'Sin verificar'
  return emite === 'titular' ? 'Emite él' : '—'
}

export function tonoDeDelegacion(d: Delegacion): 'neutro' | 'curso' | 'atencion' | 'ok' | 'negativo' {
  if (d === 'delegado') return 'ok'
  if (d === 'pendiente') return 'atencion'
  return 'neutro'
}

export const ETIQUETA_DE_QUIEN_EMITE: Record<QuienEmite, string> = { nosotros: 'Nosotros', titular: 'El titular' }

/** La línea de la ficha del cliente: «Carta de porte: delegó a nosotros ✓ / emite él / pendiente». */
export function lineaDeCartaDePorte(t: Pick<Titular, 'emite' | 'delegacion' | 'activo'>): string {
  const base = t.emite === 'titular' ? 'emite él'
    : t.delegacion === 'delegado' ? 'delegó a nosotros ✓'
      : t.delegacion === 'pendiente' ? 'pendiente (ARCA todavía no informa su delegación)'
        : 'emitimos nosotros (sin verificar en ARCA)'
  return t.activo ? base : `${base} · dado de baja`
}

// ── Instrucciones de delegación ───────────────────────────────────────────

/** El paso a paso para que un titular nos delegue `wscpe`, armado con los datos del certificado cargado. Nada de esto
 *  está escrito a mano: el CUIT del representante y el alias (el computador fiscal) salen del .crt. */
export function textoDeInstrucciones(
  i: Pick<InstruccionesDeDelegacion, 'alias' | 'cuit_representante' | 'ambiente'>, titular?: string,
): string {
  const quien = titular ? `en representación de ${titular}` : 'en representación del titular'
  const alias = i.alias ?? ''
  const aviso = alias.endsWith('homo') ? '' : ' (no el que termina en «homo»)'
  return [
    `Para que podamos emitir tus cartas de porte, entrá a ARCA con tu clave fiscal y delegá el servicio:`,
    `Administrador de Relaciones de Clave Fiscal, actuando ${quien} → Nueva Relación → Servicio: Buscar → ARCA → `
    + `WebServices → wscpe (Carta de Porte Electrónica) → Representante: Buscar → CUIT ${formatearCuit(i.cuit_representante)} `
    + `→ en Computador Fiscal elegir ${alias}${aviso} → Confirmar dos veces.`,
  ].join('\n')
}
