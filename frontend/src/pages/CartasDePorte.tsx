/** Cartas de porte: las que ARCA informa por cada viaje y los titulares a cuyo nombre se emiten (ADR-036, ADR-044).
 *
 *  Dos pestañas, como Entidades y Comprobantes:
 *
 *  - **Cartas** (la de siempre): el listado, traer de ARCA por CTG, actualizar, vincular a una orden, anular.
 *  - **Titulares**: los clientes que nos delegaron la emisión en ARCA y los que emiten ellos. Antes esto no existía en
 *    pantalla y «Integración AFIP» (Configuración / ARCA) iba a quedar con todo junto: ahí quedan sólo los certificados, el
 *    ambiente y el interruptor de la emisión real.
 *
 *  ## La pestaña va en la URL
 *
 *  `/cartas-porte` es el listado y `/cartas-porte?pestana=titulares` son los titulares; con `&ver=<id>` se abre la ficha de
 *  uno (es como llega el enlace de la ficha del cliente). Cambiar de pestaña **empuja** una entrada al historial y
 *  **descarta el resto del query**: un `?ver=` es de la pestaña que lo abre. Sólo la pestaña activa se monta.
 *
 *  El título es de la pantalla, y los botones de cada pestaña van en su línea (`AccionesDelTitulo`).
 */
import { INDICADORES } from 'libra-ui/iconos-indicador'
import { IconoIndicador } from 'libra-ui/IconoIndicador'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { Handshake } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { PantallaConTitulo } from '@/components/AccionesDelTitulo'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PESTANAS_DE_CARTAS_DE_PORTE, pestanaDeCartasDePorte } from '@/navegacion'

import { ListadoDeCartasDePorte } from './CartasDePorteListado'
import { Titulares } from './Titulares'

export default function CartasDePorte() {
  const [params, setParams] = useSearchParams()
  const actual = pestanaDeCartasDePorte(params.get('pestana'))

  function elegir(valor: string) {
    const pestana = pestanaDeCartasDePorte(valor)
    if (pestana !== actual) setParams(pestana === 'cartas' ? {} : { pestana })
  }

  return (
    <div>
      <PantallaConTitulo titulo={<TituloPantalla icono={INDICADORES.cartasDePorte}>Cartas de porte</TituloPantalla>}>
        <Tabs value={actual} onValueChange={elegir} className="gap-4">
          <TabsList className="no-imprimir">
            {PESTANAS_DE_CARTAS_DE_PORTE.map((p) => (
              <TabsTrigger key={p} value={p}>
                {p === 'cartas'
                  ? <><IconoIndicador concepto="cartasDePorte" className="size-4" />Cartas</>
                  : <><Handshake className="size-4" />Titulares</>}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="cartas"><ListadoDeCartasDePorte /></TabsContent>
          <TabsContent value="titulares"><Titulares /></TabsContent>
        </Tabs>
      </PantallaConTitulo>
    </div>
  )
}
