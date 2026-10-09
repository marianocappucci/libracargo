/** Los datos habituales para emitir a nombre de un titular (ADR-044), en su propia página desde el 2026-10-09.
 *
 *  Antes iban al pie de la ficha del titular, que es un diálogo: el formulario es largo y quedaba apretado. La ficha
 *  ahora sólo dice si hay plantilla y trae acá (`irA.plantillaDeTitular`). Cuelga de «Cartas de porte» en el menú, así
 *  que el título lleva su icono.
 *
 *  El titular y el CUIT para pedir los catálogos de ARCA salen del listado de titulares, el mismo pedido de la pestaña:
 *  no hay otro que traiga un titular solo, y así lo que se ve acá es lo mismo que allá (su estado de delegación incluido).
 */
import { INDICADORES } from 'libra-ui/iconos-indicador'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import type { ListadoDeTitulares } from '@/api/cartas-porte'
import { cartasPorte, formatearCuit } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { PlantillaDeTitular } from '@/components/PlantillaDeTitular'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/context/AuthContext'
import { irA } from '@/navegacion'

export default function PlantillaDeTitularPagina() {
  const { id: param } = useParams()
  const id = Number(param)
  const valido = Number.isInteger(id) && id > 0
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const [listado, setListado] = useState<ListadoDeTitulares | null>(null)
  const [error, setError] = useState<string | null>(valido ? null : 'La dirección no tiene un titular válido.')

  useEffect(() => {
    if (!valido) return
    let vigente = true
    cartasPorte.titulares()
      .then((r) => { if (vigente) setListado(r) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [valido])

  const titular = listado?.titulares.find((t) => t.id === id) ?? null
  const volver = valido ? irA.titulares(id) : irA.titulares()

  let cuerpo: React.ReactNode
  if (error) {
    cuerpo = <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>
  } else if (!listado) {
    cuerpo = <p className="text-muted-foreground text-sm">Cargando el titular…</p>
  } else if (!titular) {
    cuerpo = <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">
      No hay un titular con ese número: puede que lo hayan sacado de la lista.
    </p>
  } else if (titular.emite !== 'nosotros') {
    cuerpo = <p className="text-muted-foreground text-sm">
      {titular.razon_social} emite sus propias cartas de porte: no emitimos a su nombre, así que no lleva datos habituales.
    </p>
  } else {
    cuerpo = <PlantillaDeTitular titular={titular} cuitParaCatalogos={listado.cuit_para_catalogos}
                                 puedeEditar={esAdmin} />
  }

  return (
    <div className="mx-auto grid max-w-4xl gap-4">
      <TituloPantalla icono={INDICADORES.cartasDePorte}>Datos habituales para emitir</TituloPantalla>
      {titular && (
        <p className="text-sm">
          <span className="font-medium">{titular.razon_social}</span>
          <span className="text-muted-foreground tabular-nums"> · CUIT {formatearCuit(titular.cuit)}</span>
        </p>
      )}
      {cuerpo}
      <div><Button asChild variant="outline"><Link to={volver}>Volver al titular</Link></Button></div>
    </div>
  )
}
