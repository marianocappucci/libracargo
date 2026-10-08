/** La lógica de «Emitir carta de porte» que no es pantalla: del borrador que se edita a lo que se manda, y qué falta.
 *
 *  🔑 **El borrador son textos.** Es lo que escribe la persona; los números, los CUIT sin guiones y la fecha con zona se
 *  arman recién en {@link datosDe}, que es lo único que sale hacia ARCA. Los rangos de {@link problemasDe} son los
 *  mismos que valida `SolicitudCpe.problemas()` de `libracore` (para que no se entere recién ARCA); si una regla cambia
 *  allá, el servidor sigue siendo el que manda y su 422 se muestra tal cual.
 */
import type { DatosDeEmision, DatosDePlantilla, Propuesta } from '@/api/cartas-porte'
import { enmascararCuit } from '@/api/cartas-porte'

/** Los intervinientes opcionales, con el nombre del WSDL de ARCA (`IntervinientesSolicitud`) y como se leen. */
export const INTERVINIENTES: { clave: string; etiqueta: string }[] = [
  { clave: 'cuitRemitenteComercialVentaPrimaria', etiqueta: 'Remitente comercial (venta primaria)' },
  { clave: 'cuitRemitenteComercialVentaSecundaria', etiqueta: 'Remitente comercial (venta secundaria)' },
  { clave: 'cuitRemitenteComercialVentaSecundaria2', etiqueta: 'Remitente comercial (venta secundaria 2)' },
  { clave: 'cuitMercadoATermino', etiqueta: 'Mercado a término' },
  { clave: 'cuitCorredorVentaPrimaria', etiqueta: 'Corredor (venta primaria)' },
  { clave: 'cuitCorredorVentaSecundaria', etiqueta: 'Corredor (venta secundaria)' },
  { clave: 'cuitRepresentanteEntregador', etiqueta: 'Representante del entregador' },
  { clave: 'cuitRepresentanteRecibidor', etiqueta: 'Representante del recibidor' },
]

/** Hasta tres dominios: chasis y hasta dos acoplados. */
export const MAX_DOMINIOS = 3

export type Borrador = {
  sucursal: number
  origenTipo: 'campo' | 'planta'
  origenProvincia: string
  origenLocalidad: string
  origenPlanta: string
  origenRenspa: string
  codGrano: string
  cosecha: string
  pesoBruto: string
  pesoTara: string
  destinoCuit: string
  destinoProvincia: string
  destinoLocalidad: string
  destinoPlanta: string
  destinoEsCampo: boolean
  cuitDestinatario: string
  cuitTransportista: string
  dominios: string[]
  /** `aaaa-mm-ddTHH:mm`, hora de Argentina: el valor de un `<input type="datetime-local">`. */
  partida: string
  km: string
  cuitChofer: string
  cuitPagador: string
  cuitIntermediario: string
  tarifa: string
  fumigada: boolean
  intervinientes: Record<string, string>
  remitenteProductor: string
  observaciones: string
}

const texto = (v: unknown) => (v === null || v === undefined ? '' : String(v))
const cuitTexto = (v: unknown) => enmascararCuit(texto(v))
const digitos = (v: string) => v.replace(/\D/g, '')

// ── La partida: ahora + 1 h, en hora de Argentina ─────────────────────────

const ZONA = 'America/Argentina/Buenos_Aires'
/** Argentina no tiene horario de verano: el desfase es fijo y es el que ARCA espera en `fechaHoraPartida`. */
const DESFASE = '-03:00'

/** `aaaa-mm-ddTHH:mm` de la hora de pared de Argentina en ese instante. */
export function relojDeArgentina(instante: Date): string {
  const partes = new Intl.DateTimeFormat('en-CA', {
    timeZone: ZONA, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(instante)
  const d = Object.fromEntries(partes.map((p) => [p.type, p.value]))
  return `${d.year}-${d.month}-${d.day}T${d.hour}:${d.minute}`
}

/** La partida que se propone: dentro de una hora. La persona la corrige; ARCA la exige. */
export function partidaPorDefecto(ahora: Date = new Date()): string {
  return relojDeArgentina(new Date(ahora.getTime() + 3600_000))
}

/** `2026-10-08T15:30` → `2026-10-08T15:30:00-03:00`. */
export const partidaAIso = (local: string) => `${local}:00${DESFASE}`

// ── De la propuesta al borrador y de vuelta ───────────────────────────────

export function borradorDe(p: Propuesta, ahora: Date = new Date()): Borrador {
  const t = p.transporte
  const dominios = [...t.dominios.map((d) => d.toUpperCase()), '', '', ''].slice(0, MAX_DOMINIOS)
  const destinoCuit = cuitTexto(p.destino.cuit)
  const interv: Record<string, string> = {}
  for (const { clave } of INTERVINIENTES) interv[clave] = cuitTexto(p.intervinientes?.[clave])
  return {
    sucursal: p.sucursal || 1,
    origenTipo: p.origen.tipo === 'planta' ? 'planta' : 'campo',
    origenProvincia: texto(p.origen.cod_provincia),
    origenLocalidad: texto(p.origen.cod_localidad),
    origenPlanta: texto(p.origen.planta),
    origenRenspa: texto(p.origen.renspa),
    codGrano: texto(p.cod_grano),
    cosecha: texto(p.cosecha),
    pesoBruto: texto(p.peso_bruto),
    pesoTara: texto(p.peso_tara),
    destinoCuit,
    destinoProvincia: texto(p.destino.cod_provincia),
    destinoLocalidad: texto(p.destino.cod_localidad),
    destinoPlanta: texto(p.destino.planta),
    destinoEsCampo: Boolean(p.destino.es_campo),
    // Por defecto el destinatario es el destino: lo más común es que sean la misma persona.
    cuitDestinatario: cuitTexto(p.cuit_destinatario) || destinoCuit,
    cuitTransportista: cuitTexto(t.cuit_transportista),
    dominios,
    partida: partidaPorDefecto(ahora),
    km: texto(t.km),
    cuitChofer: cuitTexto(t.cuit_chofer),
    cuitPagador: cuitTexto(t.cuit_pagador_flete),
    cuitIntermediario: cuitTexto(t.cuit_intermediario_flete),
    tarifa: texto(t.tarifa),
    fumigada: Boolean(t.mercaderia_fumigada),
    intervinientes: interv,
    remitenteProductor: cuitTexto(p.cuit_remitente_comercial_productor),
    observaciones: texto(p.observaciones),
  }
}

const entero = (v: string) => (v.trim() === '' ? null : Number(v))
const cuitODigitos = (v: string) => digitos(v) || null

/** Lo que viaja a `POST /emision/emitir` como `datos`. Sólo se llama con el borrador sin problemas. */
export function datosDe(b: Borrador, cuitTitular: string): DatosDeEmision {
  const intervinientes: Record<string, string | null> = {}
  for (const { clave } of INTERVINIENTES) {
    const d = digitos(b.intervinientes[clave] ?? '')
    if (d) intervinientes[clave] = d
  }
  return {
    cuit_titular: cuitTitular,
    sucursal: b.sucursal,
    origen: b.origenTipo === 'planta'
      ? { tipo: 'planta', cod_provincia: entero(b.origenProvincia), cod_localidad: entero(b.origenLocalidad),
          planta: entero(b.origenPlanta) }
      : { tipo: 'campo', cod_provincia: entero(b.origenProvincia), cod_localidad: entero(b.origenLocalidad),
          renspa: b.origenRenspa.trim() || null },
    cod_grano: entero(b.codGrano),
    cosecha: entero(b.cosecha),
    peso_bruto: entero(b.pesoBruto),
    peso_tara: entero(b.pesoTara),
    destino: {
      cuit: cuitODigitos(b.destinoCuit), cod_provincia: entero(b.destinoProvincia),
      cod_localidad: entero(b.destinoLocalidad), planta: entero(b.destinoPlanta), es_campo: b.destinoEsCampo,
    },
    cuit_destinatario: cuitODigitos(b.cuitDestinatario),
    intervinientes,
    cuit_remitente_comercial_productor: cuitODigitos(b.remitenteProductor),
    transporte: {
      cuit_transportista: cuitODigitos(b.cuitTransportista),
      dominios: b.dominios.map((d) => d.trim().toUpperCase()).filter(Boolean),
      fecha_hora_partida: b.partida ? partidaAIso(b.partida) : null,
      km: entero(b.km),
      cuit_chofer: cuitODigitos(b.cuitChofer),
      cuit_pagador_flete: cuitODigitos(b.cuitPagador),
      cuit_intermediario_flete: cuitODigitos(b.cuitIntermediario),
      tarifa: b.tarifa.trim() ? b.tarifa.trim().replace(',', '.') : null,
      mercaderia_fumigada: b.fumigada,
    },
    observaciones: b.observaciones.trim() || null,
  }
}

// ── Qué falta ─────────────────────────────────────────────────────────────

export const netoDe = (b: Pick<Borrador, 'pesoBruto' | 'pesoTara'>): number | null => {
  if (!/^\d+$/.test(b.pesoBruto) || !/^\d+$/.test(b.pesoTara)) return null
  return Number(b.pesoBruto) - Number(b.pesoTara)
}

// Las reglas de formato que comparten el asistente de emitir y la plantilla de un titular (`PlantillaDeTitular`): una
// sola definición de qué es un CUIT, una cosecha o unos kilómetros válidos. Devuelven el mensaje, o `undefined` si sirve.
// Un valor vacío no es asunto de estas reglas: «obligatorio» lo decide cada pantalla.

/** Un CUIT escrito: once dígitos (con o sin guiones). */
export const reglaDeCuit = (valor: string): string | undefined =>
  digitos(valor).length === 11 ? undefined : 'Un CUIT tiene 11 dígitos'

export const reglaDeCosecha = (valor: string): string | undefined =>
  /^\d{4}$/.test(valor) ? undefined : 'Cuatro cifras (2526 = 2025/2026)'

export const reglaDeKm = (valor: string): string | undefined =>
  /^\d+$/.test(valor) && Number(valor) >= 1 && Number(valor) <= 99999 ? undefined : 'Los kilómetros van de 1 a 99.999'

export const reglaDeObservaciones = (valor: string): string | undefined =>
  valor.length > 2000 ? 'Hasta 2.000 caracteres' : undefined

/** Los problemas de cada campo, por su nombre; un campo sin problema no aparece. Los mensajes son lo que se lee debajo
 *  del campo: «Obligatorio» cuando está vacío, y la regla cuando está mal. */
export function problemasDe(b: Borrador): Record<string, string> {
  const p: Record<string, string> = {}
  const falta = (campo: string, valor: string) => {
    if (valor.trim() === '') { p[campo] = 'Obligatorio'; return true }
    return false
  }
  const cuit = (campo: string, valor: string, obligatorio = true) => {
    if (valor.trim() === '') { if (obligatorio) p[campo] = 'Obligatorio'; return }
    const mensaje = reglaDeCuit(valor)
    if (mensaje) p[campo] = mensaje
  }

  falta('origenProvincia', b.origenProvincia)
  falta('origenLocalidad', b.origenLocalidad)
  if (b.origenTipo === 'planta') falta('origenPlanta', b.origenPlanta)

  falta('codGrano', b.codGrano)
  if (!falta('cosecha', b.cosecha)) { const m = reglaDeCosecha(b.cosecha); if (m) p.cosecha = m }
  for (const [campo, valor, nombre] of [['pesoBruto', b.pesoBruto, 'bruto'], ['pesoTara', b.pesoTara, 'tara']] as const) {
    if (falta(campo, valor)) continue
    if (!/^\d+$/.test(valor) || Number(valor) < 1 || Number(valor) > 88000) {
      p[campo] = `El peso ${nombre} va de 1 a 88.000 kg`
    }
  }
  if (!p.pesoBruto && !p.pesoTara && Number(b.pesoTara) >= Number(b.pesoBruto)) {
    p.pesoTara = 'La tara tiene que ser menor que el peso bruto'
  }

  cuit('destinoCuit', b.destinoCuit)
  falta('destinoProvincia', b.destinoProvincia)
  falta('destinoLocalidad', b.destinoLocalidad)
  cuit('cuitDestinatario', b.cuitDestinatario)

  cuit('cuitTransportista', b.cuitTransportista)
  const dominios = b.dominios.map((d) => d.trim()).filter(Boolean)
  if (dominios.length === 0) p.dominios = 'Obligatorio: al menos uno'
  else if (dominios.some((d) => d.length < 6 || d.length > 7)) p.dominios = 'Un dominio tiene 6 o 7 caracteres'
  falta('partida', b.partida)
  if (!falta('km', b.km)) { const m = reglaDeKm(b.km); if (m) p.km = m }
  cuit('cuitChofer', b.cuitChofer)
  cuit('cuitPagador', b.cuitPagador)
  cuit('cuitIntermediario', b.cuitIntermediario, false)
  if (b.tarifa.trim() !== '') {
    const t = b.tarifa.trim().replace(',', '.')
    if (!/^\d{1,5}(\.\d{1,2})?$/.test(t)) p.tarifa = 'De 0 a 99.999,99 (por tonelada)'
  }
  for (const { clave } of INTERVINIENTES) cuit(`interviniente:${clave}`, b.intervinientes[clave] ?? '', false)
  cuit('remitenteProductor', b.remitenteProductor, false)
  const obs = reglaDeObservaciones(b.observaciones)
  if (obs) p.observaciones = obs
  return p
}

// ── La plantilla de un titular ────────────────────────────────────────────
//
// Lo que `propuesta()` del backend lee de `plantillas_cpe` (`CAMPOS_DE_PLANTILLA`): el origen, el grano, la cosecha, el
// destino, los intervinientes y lo habitual del transporte. Mismas claves que `datosDe` manda al emitir, mismas reglas
// de formato; lo único distinto es que acá **nada es obligatorio**: una plantilla puede ser parcial y lo que falte lo
// completa quien emite.

export type BorradorDePlantilla = Pick<Borrador,
  'sucursal' | 'origenTipo' | 'origenProvincia' | 'origenLocalidad' | 'origenPlanta' | 'origenRenspa' | 'codGrano'
  | 'cosecha' | 'destinoCuit' | 'destinoProvincia' | 'destinoLocalidad' | 'destinoPlanta' | 'destinoEsCampo'
  | 'cuitDestinatario' | 'km' | 'fumigada' | 'intervinientes' | 'remitenteProductor' | 'observaciones'>

export function borradorDePlantilla(d: DatosDePlantilla): BorradorDePlantilla {
  const interv: Record<string, string> = {}
  for (const { clave } of INTERVINIENTES) interv[clave] = cuitTexto(d.intervinientes?.[clave])
  return {
    sucursal: d.sucursal || 1,
    origenTipo: d.origen?.tipo === 'planta' ? 'planta' : 'campo',
    origenProvincia: texto(d.origen?.cod_provincia),
    origenLocalidad: texto(d.origen?.cod_localidad),
    origenPlanta: texto(d.origen?.planta),
    origenRenspa: texto(d.origen?.renspa),
    codGrano: texto(d.cod_grano),
    cosecha: texto(d.cosecha),
    destinoCuit: cuitTexto(d.destino?.cuit),
    destinoProvincia: texto(d.destino?.cod_provincia),
    destinoLocalidad: texto(d.destino?.cod_localidad),
    destinoPlanta: texto(d.destino?.planta),
    destinoEsCampo: Boolean(d.destino?.es_campo),
    cuitDestinatario: cuitTexto(d.cuit_destinatario),
    km: texto(d.km),
    fumigada: Boolean(d.mercaderia_fumigada),
    intervinientes: interv,
    remitenteProductor: cuitTexto(d.cuit_remitente_comercial_productor),
    observaciones: texto(d.observaciones),
  }
}

/** Los problemas de formato de lo que se escribió; lo vacío no es un problema. Mismos nombres de campo que `problemasDe`. */
export function problemasDePlantilla(b: BorradorDePlantilla): Record<string, string> {
  const p: Record<string, string> = {}
  const si = (campo: string, valor: string, regla: (v: string) => string | undefined) => {
    if (valor.trim() === '') return
    const m = regla(valor)
    if (m) p[campo] = m
  }
  si('cosecha', b.cosecha, reglaDeCosecha)
  si('km', b.km, reglaDeKm)
  for (const campo of ['destinoCuit', 'cuitDestinatario', 'remitenteProductor'] as const) si(campo, b[campo], reglaDeCuit)
  for (const { clave } of INTERVINIENTES) si(`interviniente:${clave}`, b.intervinientes[clave] ?? '', reglaDeCuit)
  si('observaciones', b.observaciones, (v) => reglaDeObservaciones(v))
  return p
}

/** Lo que viaja a `PUT /titulares/:id/plantilla`. Lo vacío se omite: una clave ausente es «que lo complete quien emite». */
export function datosDePlantilla(b: BorradorDePlantilla): DatosDePlantilla {
  const numero = (v: string) => (v.trim() === '' ? null : Number(v))
  const d: DatosDePlantilla = {}
  const poner = <K extends keyof DatosDePlantilla>(clave: K, valor: DatosDePlantilla[K] | null) => {
    if (valor !== null && valor !== undefined && valor !== '') d[clave] = valor
  }
  poner('sucursal', b.sucursal && b.sucursal !== 1 ? b.sucursal : null)
  const origen = b.origenTipo === 'planta'
    ? { tipo: 'planta' as const, cod_provincia: numero(b.origenProvincia), cod_localidad: numero(b.origenLocalidad),
        planta: numero(b.origenPlanta) }
    : { tipo: 'campo' as const, cod_provincia: numero(b.origenProvincia), cod_localidad: numero(b.origenLocalidad),
        renspa: b.origenRenspa.trim() || null }
  const hayOrigen = origen.cod_provincia !== null || origen.cod_localidad !== null
    || ('planta' in origen && origen.planta !== null) || ('renspa' in origen && origen.renspa !== null)
  if (hayOrigen || b.origenTipo === 'planta') d.origen = origen
  poner('cod_grano', numero(b.codGrano))
  poner('cosecha', numero(b.cosecha))
  const destino = {
    cuit: cuitODigitos(b.destinoCuit), cod_provincia: numero(b.destinoProvincia),
    cod_localidad: numero(b.destinoLocalidad), planta: numero(b.destinoPlanta), es_campo: b.destinoEsCampo,
  }
  if (destino.cuit !== null || destino.cod_provincia !== null || destino.cod_localidad !== null
      || destino.planta !== null || destino.es_campo) d.destino = destino
  poner('cuit_destinatario', cuitODigitos(b.cuitDestinatario))
  const intervinientes: Record<string, string | null> = {}
  for (const { clave } of INTERVINIENTES) {
    const c = digitos(b.intervinientes[clave] ?? '')
    if (c) intervinientes[clave] = c
  }
  if (Object.keys(intervinientes).length > 0) d.intervinientes = intervinientes
  poner('cuit_remitente_comercial_productor', cuitODigitos(b.remitenteProductor))
  if (b.fumigada) d.mercaderia_fumigada = true
  poner('km', numero(b.km))
  poner('observaciones', b.observaciones.trim() || null)
  return d
}
