/** El selector de origen y destino de una orden (ADR-041, ADR-042).
 *
 *  Se escribe y aparecen, primero, las localidades que ya están en el maestro (las que usan las órdenes) y debajo, bajo
 *  «Del catálogo (Argentina y Mercosur)», las del catálogo que todavía no están, con su provincia. Las de afuera de
 *  Argentina llevan además el país: «Nueva Palmira — Colonia (Uruguay)». Elegir una del catálogo
 *  la trae al maestro (`POST /desde-catalogo`) y queda seleccionada la que devuelve el servidor. Al final siempre está
 *  «Cargar «…» como paraje…»: la excepción, un lugar que no está en ningún catálogo.
 *
 *  Es un componente propio y no el `SelectBuscable` de `libra-ui` porque éste filtra en memoria y acá las opciones las
 *  decide el servidor según lo escrito (ver `BuscadorAsincrono`).
 */
import { useState } from 'react'

import { conProvincia, localidadesApi, type Localidad, type OpcionLocalidad } from '@/api/localidades'
import { BuscadorAsincrono, type GrupoBuscado } from '@/components/BuscadorAsincrono'
import { DialogoParaje } from '@/components/DialogoParaje'

export function ElegirLocalidad({ id, etiqueta, valor, localidades, alElegir, alIncorporar, invalido, children }: {
  id: string
  etiqueta: string
  /** El id de la localidad elegida, como texto (`''` si no hay). */
  valor: string
  /** Las que el formulario ya conoce: de acá sale el nombre de la elegida. */
  localidades: OpcionLocalidad[]
  alElegir: (id: string) => void
  /** Se llama con la localidad que devuelve el servidor (traída del catálogo o cargada como paraje) para que el
   *  formulario la sume a su lista y pueda mostrar su nombre. */
  alIncorporar: (l: Localidad) => void
  invalido?: boolean
  children?: React.ReactNode
}) {
  const [parajeDe, setParajeDe] = useState<string | null>(null)
  const actual = localidades.find((l) => String(l.id) === valor)

  async function buscar(q: string): Promise<GrupoBuscado[]> {
    const { maestro, catalogo } = await localidadesApi.buscar(q)
    const grupos: GrupoBuscado[] = []
    if (maestro.length) {
      grupos.push({
        items: maestro.map((l) => ({
          clave: `maestro-${l.id}`,
          etiqueta: conProvincia(l.nombre, l.provincia, l.pais),
          // Una marca discreta: que se note que no es del catálogo, sin competir con el nombre.
          marca: !l.activo ? 'De baja' : l.es_paraje ? 'Paraje' : undefined,
          deshabilitado: !l.activo,
          alElegir: () => { alIncorporar(l); alElegir(String(l.id)) },
        })),
      })
    }
    if (catalogo.length) {
      grupos.push({
        titulo: 'Del catálogo (Argentina y Mercosur)',
        items: catalogo.map((c) => ({
          clave: `catalogo-${c.id}`,
          etiqueta: conProvincia(c.nombre, c.provincia, c.pais),
          alElegir: async () => {
            const l = await localidadesApi.desdeCatalogo(c.id)
            alIncorporar(l)
            alElegir(String(l.id))
          },
        })),
      })
    }
    return grupos
  }

  return (
    <>
      <BuscadorAsincrono
        id={id} etiqueta={etiqueta} className="w-full min-w-0"
        valorVisible={actual ? conProvincia(actual.etiqueta, actual.provincia, actual.pais) : ''}
        placeholder="Buscar localidad…"
        buscar={buscar}
        alFinal={(q) => ({
          clave: 'cargar-paraje',
          etiqueta: `Cargar «${q}» como paraje…`,
          alElegir: () => setParajeDe(q),
        })}
        alQuitar={() => alElegir('')}
        mensajeVacio="No hay ninguna con ese nombre."
        invalido={invalido}
      >
        {children}
      </BuscadorAsincrono>
      {parajeDe !== null && (
        <DialogoParaje
          alCerrar={() => setParajeDe(null)}
          nombreInicial={parajeDe}
          confirmar={async ({ nombre, provincia, pais }) => {
            const l = await localidadesApi.cargarParaje(nombre, provincia, pais)
            alIncorporar(l)
            alElegir(String(l.id))
            setParajeDe(null)
          }}
        />
      )}
    </>
  )
}
