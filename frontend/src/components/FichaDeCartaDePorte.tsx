/** Los datos de una carta de porte, para la vista previa («Traer de ARCA») y para el detalle del listado.
 *
 *  Es la misma ficha en los dos lugares a propósito: lo que se ve antes de guardar es lo que queda guardado.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'

import type { CartaPorte, Parte } from '@/api/cartas-porte'
import {
  esEstadoFinal, etiquetaDeGrano, formatearCuit, formatearInstante, formatearKilos, nombreOCuit, tonoDeEstado,
} from '@/api/cartas-porte'
import { formatearImporte } from '@/components/esquema-orden'

/** Un CUIT con el nombre del tercero cargado: `Agro Norte SA (30-22222222-3)`. */
function parteConCuit(parte: Parte): string {
  const cuit = formatearCuit(parte.cuit)
  if (!cuit) return '—'
  return parte.nombre?.trim() ? `${parte.nombre.trim()} (${cuit})` : cuit
}

/** Un código de ARCA con su nombre, si se lo bajó (ADR-051): `Rosario`; sin nombre, `Localidad 4211`. */
function conNombre(nombre: string | null | undefined, etiqueta: string, codigo: number | null): string | null {
  if (nombre) return nombre
  return codigo != null ? `${etiqueta} ${codigo}` : null
}

/** El lugar de carga o de descarga: el CUIT, la localidad y la provincia que informa ARCA. Con los dos nombres se lee
 *  `Rosario, Santa Fe`; si falta alguno, cada uno va aparte y el que no tiene nombre muestra su código. */
function lugar(
  parte: Parte,
  provincia: { codigo: number | null; nombre?: string | null },
  localidad: { codigo: number | null; nombre?: string | null },
  planta?: number | null,
): string {
  const prov = conNombre(provincia.nombre, 'Provincia', provincia.codigo)
  const loc = conNombre(localidad.nombre, 'Localidad', localidad.codigo)
  const geografia = provincia.nombre && localidad.nombre ? [`${localidad.nombre}, ${provincia.nombre}`] : [prov, loc]
  const partes = [parte.cuit ? parteConCuit(parte) : null, ...geografia, planta != null && `Planta ${planta}`]
  return partes.filter(Boolean).join(' · ') || '—'
}

/** `Soja · cosecha 25/26`. La cosecha de ARCA es `2526`; cualquier otra cosa se muestra tal cual. */
function granoYCosecha(carta: CartaPorte): string {
  const tieneGrano = Boolean(carta.grano) || carta.cod_grano != null
  const grano = tieneGrano ? etiquetaDeGrano(carta) : null
  const c = carta.cosecha != null ? String(carta.cosecha) : ''
  const cosecha = c.length === 4 ? `cosecha ${c.slice(0, 2)}/${c.slice(2)}` : c ? `cosecha ${c}` : null
  return [grano, cosecha].filter(Boolean).join(' · ') || '—'
}

function Dato({ etiqueta, children, ancho }: { etiqueta: string; children: React.ReactNode; ancho?: boolean }) {
  return (
    <div className={ancho ? 'col-span-2' : undefined}>
      <p className="text-muted-foreground text-xs">{etiqueta}</p>
      <div className="font-medium break-words">{children}</div>
    </div>
  )
}

export function FichaDeCartaDePorte({ carta }: { carta: CartaPorte }) {
  const filasDeKilos: [string, number | null, number | null][] = [
    ['Bruto', carta.peso_bruto, carta.peso_bruto_descarga],
    ['Tara', carta.peso_tara, carta.peso_tara_descarga],
    ['Neto', carta.peso_neto, carta.peso_neto_descarga],
  ]
  return (
    <div className="grid gap-4 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <Dato etiqueta="N.º de CPE">{carta.numero || '—'}</Dato>
        <Dato etiqueta="CTG">{carta.nro_ctg}</Dato>
        <Dato etiqueta="Estado">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <BadgeEstado tono={tonoDeEstado(carta.estado)}>{carta.estado_descripcion}</BadgeEstado>
            {carta.fecha_inicio_estado && (
              <span className="text-muted-foreground text-xs font-normal">
                desde {formatearInstante(carta.fecha_inicio_estado)}
              </span>
            )}
          </div>
        </Dato>
        <Dato etiqueta="Emisión">{formatearInstante(carta.fecha_emision)}</Dato>
        <Dato etiqueta="Vencimiento">{formatearInstante(carta.fecha_vencimiento)}</Dato>
        <Dato etiqueta="Partida">{formatearInstante(carta.fecha_partida)}</Dato>
        {/* Cuándo se le preguntó a ARCA por última vez: lo que se ve es de ese momento (el refresco programado lo renueva). */}
        {carta.consultada_en && <Dato etiqueta="Última consulta a ARCA">{formatearInstante(carta.consultada_en)}</Dato>}
        <Dato etiqueta="Pagador del flete" ancho>{parteConCuit(carta.pagador_flete)}</Dato>
        <Dato etiqueta="Transportista" ancho>{parteConCuit(carta.transportista)}</Dato>
        <Dato etiqueta="Chofer" ancho>{parteConCuit(carta.chofer)}</Dato>
        <Dato etiqueta="Dominios">{carta.dominios.length ? carta.dominios.join(', ') : '—'}</Dato>
        <Dato etiqueta="Destinatario">{nombreOCuit(carta.destinatario)}</Dato>
        <Dato etiqueta="Origen" ancho>
          {lugar(carta.origen, { codigo: carta.cod_provincia_origen, nombre: carta.provincia_origen },
                 { codigo: carta.cod_localidad_origen, nombre: carta.localidad_origen })}
        </Dato>
        <Dato etiqueta="Destino" ancho>
          {lugar(carta.destino, { codigo: carta.cod_provincia_destino, nombre: carta.provincia_destino },
                 { codigo: carta.cod_localidad_destino, nombre: carta.localidad_destino }, carta.planta_destino)}
        </Dato>
        <Dato etiqueta="Grano" ancho>{granoYCosecha(carta)}</Dato>
        <Dato etiqueta="Kilómetros">{carta.km != null ? formatearKilos(carta.km) : '—'}</Dato>
        <Dato etiqueta="Tarifa">{carta.tarifa != null ? formatearImporte(carta.tarifa) : '—'}</Dato>
      </div>

      <table className="w-full text-sm">
        <caption className="sr-only">Kilos de carga y de descarga</caption>
        <thead>
          <tr className="text-muted-foreground border-b text-left text-xs">
            <th scope="col" className="py-1 font-normal">Kilos</th>
            <th scope="col" className="py-1 text-right font-normal">Carga</th>
            <th scope="col" className="py-1 text-right font-normal">Descarga</th>
          </tr>
        </thead>
        <tbody>
          {filasDeKilos.map(([nombre, carga, descarga]) => (
            <tr key={nombre} className={nombre === 'Neto' ? 'border-t font-medium' : undefined}>
              <th scope="row" className="py-1 text-left font-normal">{nombre}</th>
              <td className="py-1 text-right tabular-nums">{formatearKilos(carga)}</td>
              <td className="py-1 text-right tabular-nums">
                {/* «pendiente» una sola vez, en el neto: tres renglones iguales serían ruido. */}
                {descarga == null && nombre === 'Neto' && !esEstadoFinal(carta.estado)
                  ? 'pendiente' : formatearKilos(descarga)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
