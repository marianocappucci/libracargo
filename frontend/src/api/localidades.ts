import { api } from 'libra-ui/api-client'

import { nombreDePais, PAIS_POR_OMISION, type LocalidadDelCatalogo } from '@/api/geo'

/** El maestro de localidades (ADR-041): lo que referencian las órdenes como origen y destino.
 *
 *  Cada fila es **del catálogo** (`catalogo_id` es el código censal del INDEC), **un paraje** (`es_paraje`: un lugar real
 *  que no está en ningún catálogo, cargado a mano con su provincia) o **sin vincular** (las que se fueron cargando a
 *  mano antes del catálogo y todavía no se emparejaron con ninguna). */
export type Localidad = {
  id: number
  nombre: string
  provincia: string | null
  /** ISO de dos letras (`AR` por omisión; ADR-042). */
  pais: string
  es_paraje: boolean
  activo: boolean
  catalogo_id: string | null
}

/** Lo que un formulario sabe de cada localidad para mostrar la elegida sin pedirla otra vez (`Opcion` con lo que el
 *  selector de origen y destino necesita además del nombre). */
export type OpcionLocalidad = {
  id: number
  etiqueta: string
  provincia?: string | null
  pais?: string
  es_paraje?: boolean
}

export const aOpcionLocalidad = (l: Localidad): OpcionLocalidad => ({
  id: l.id, etiqueta: l.nombre, provincia: l.provincia, pais: l.pais, es_paraje: l.es_paraje,
})

/** Lo que contesta `/buscar/combinado`: lo que ya está en el maestro y, aparte, lo del catálogo que todavía no. */
export type BusquedaCombinada = { maestro: Localidad[]; catalogo: LocalidadDelCatalogo[] }

export type OrigenDeLocalidad = 'catalogo' | 'paraje' | 'sin_vincular'

export function origenDe(l: Pick<Localidad, 'catalogo_id' | 'es_paraje'>): OrigenDeLocalidad {
  if (l.catalogo_id) return 'catalogo'
  return l.es_paraje ? 'paraje' : 'sin_vincular'
}

export const ETIQUETA_ORIGEN: Record<OrigenDeLocalidad, string> = {
  catalogo: 'Catálogo',
  paraje: 'Paraje',
  sin_vincular: 'Sin vincular',
}

/** «Suipacha — Buenos Aires», o sólo el nombre si la fila no tiene provincia. Un lugar de afuera de Argentina lleva además
 *  el país: «Nueva Palmira — Colonia (Uruguay)». Los de Argentina quedan como siempre, sin país. */
export const conProvincia = (nombre: string, provincia: string | null | undefined, pais?: string | null) => {
  const base = provincia ? `${nombre} — ${provincia}` : nombre
  return pais && pais !== PAIS_POR_OMISION ? `${base} (${nombreDePais(pais)})` : base
}

const base = '/api/localidades'

export const localidadesApi = {
  buscar: (q: string, limite = 20) =>
    api.get<BusquedaCombinada>(`${base}/buscar/combinado?q=${encodeURIComponent(q)}&limite=${limite}`),
  /** La localidad del maestro que corresponde a esa del catálogo (la crea o la vincula si hace falta). */
  desdeCatalogo: (catalogoId: string) => api.post<Localidad>(`${base}/desde-catalogo`, { catalogo_id: catalogoId }),
  /** Un lugar que no está en el catálogo. 422 si falta la provincia; 409 si ya existe ese nombre en esa provincia. */
  cargarParaje: (nombre: string, provincia: string, pais: string = PAIS_POR_OMISION) =>
    api.post<Localidad>(base, { nombre, provincia, pais, es_paraje: true, activo: true }),
  /** Vincula una que ya existe. 409 si ese código ya es de otra. */
  vincular: (id: number, catalogoId: string) =>
    api.post<Localidad>(`${base}/${id}/vincular`, { catalogo_id: catalogoId }),
  /** Sólo administrador: las órdenes de `id` pasan a `enId` y `id` queda de baja. Devuelve la que queda. */
  unificar: (id: number, enId: number) => api.post<Localidad>(`${base}/${id}/unificar`, { en_id: enId }),
  editar: (id: number, datos: Partial<Localidad>) => api.put<Localidad>(`${base}/${id}`, datos),
}
