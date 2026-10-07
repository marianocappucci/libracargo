/** Los datos de una carta de porte, para la vista previa («Traer de ARCA») y para el detalle del listado.
 *
 *  Es la misma ficha en los dos lugares a propósito: lo que se ve antes de guardar es lo que queda guardado.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'

import type { CartaPorte, Parte } from '@/api/cartas-porte'
import {
  esEstadoFinal, formatearCuit, formatearInstante, formatearKilos, nombreOCuit, tonoDeEstado,
} from '@/api/cartas-porte'
import { formatearImporte } from '@/components/esquema-orden'

/** Un CUIT con el nombre del tercero cargado: `Agro Norte SA (30-22222222-3)`. */
function parteConCuit(parte: Parte): string {
  const cuit = formatearCuit(parte.cuit)
  if (!cuit) return '—'
  return parte.nombre?.trim() ? `${parte.nombre.trim()} (${cuit})` : cuit
}

/** El lugar de carga o de descarga: el CUIT y los códigos de provincia y localidad que informa ARCA. */
function lugar(parte: Parte, provincia: number | null, localidad: number | null, planta?: number | null): string {
  const codigos = [
    provincia != null && `Provincia ${provincia}`,
    localidad != null && `Localidad ${localidad}`,
    planta != null && `Planta ${planta}`,
  ].filter(Boolean)
  return [parte.cuit ? parteConCuit(parte) : null, ...codigos].filter(Boolean).join(' · ') || '—'
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
          <BadgeEstado tono={tonoDeEstado(carta.estado)}>{carta.estado_descripcion}</BadgeEstado>
        </Dato>
        <Dato etiqueta="Emisión">{formatearInstante(carta.fecha_emision)}</Dato>
        <Dato etiqueta="Vencimiento">{formatearInstante(carta.fecha_vencimiento)}</Dato>
        <Dato etiqueta="Partida">{formatearInstante(carta.fecha_partida)}</Dato>
        <Dato etiqueta="Pagador del flete" ancho>{parteConCuit(carta.pagador_flete)}</Dato>
        <Dato etiqueta="Transportista" ancho>{parteConCuit(carta.transportista)}</Dato>
        <Dato etiqueta="Chofer" ancho>{parteConCuit(carta.chofer)}</Dato>
        <Dato etiqueta="Dominios">{carta.dominios.length ? carta.dominios.join(', ') : '—'}</Dato>
        <Dato etiqueta="Destinatario">{nombreOCuit(carta.destinatario)}</Dato>
        <Dato etiqueta="Origen" ancho>
          {lugar(carta.origen, carta.cod_provincia_origen, carta.cod_localidad_origen)}
        </Dato>
        <Dato etiqueta="Destino" ancho>
          {lugar(carta.destino, carta.cod_provincia_destino, carta.cod_localidad_destino, carta.planta_destino)}
        </Dato>
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
