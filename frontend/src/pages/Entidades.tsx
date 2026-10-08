/** Entidades: las personas y empresas con las que trabaja la empresa, en una entrada del menú (ADR-040).
 *
 *  Pedido del humano: *«De Configuración sacamos Terceros y Choferes y ponemos un ítem en el menú principal que diga
 *  Entidades y dentro Clientes, Fleteros, Choferes y Proveedores.»*
 *
 *  ## Un modelo, cuatro pestañas
 *
 *  - **Clientes, Fleteros y Proveedores** son **roles** de una misma entidad (`terceros`): una empresa que es a la vez
 *    fletero y proveedor es **una fila**, que aparece en las dos pestañas. No se carga dos veces; se le suma el rol.
 *  - **Choferes** es otra cosa: la persona que conduce, que trabaja para un fletero (el transportista propietario o
 *    contratado). Tiene su propia tabla.
 *
 *  ## La pestaña va en la URL
 *
 *  `/entidades?pestana=fleteros`, igual que Cuenta corriente y Comprobantes: la URL es la fuente de verdad, así los
 *  enlaces andan. Cambiar de pestaña **empuja** una entrada al historial (atrás vuelve a la anterior) y **descarta el
 *  resto del query**: un `?ver=` es de una pestaña. Con `?ver=<id>` se abre la ficha de esa fila, que es como llegan
 *  los enlaces de la ficha del fletero (sus choferes) y el «Ver …» del CUIT repetido.
 *
 *  Sin `pestana`, o con una desconocida, es Clientes. Sólo la pestaña activa se monta.
 *
 *  Los enlaces de antes (`/terceros`, `/choferes`, `/configuracion?seccion=terceros|choferes`) se redirigen acá
 *  (`App.tsx`, `Configuracion.tsx`).
 */
import { Building2, UserSquare } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ICONOS_LC } from '@/iconos'
import { PESTANAS_DE_ENTIDADES, pestanaDeEntidades } from '@/navegacion'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { Choferes } from './maestros'
import { TercerosPorRol } from './maestros/TercerosPorRol'

/** `UserSquare` y no `Truck`/`Users`: el catálogo de la familia (ADR-035) ya los usa para Fleteros y Clientes, y el chofer
 *  —la persona que conduce— no es un concepto de él. */
const PESTANAS = {
  clientes: { etiqueta: 'Clientes', icono: ICONOS_LC.clientes },
  fleteros: { etiqueta: 'Fleteros', icono: ICONOS_LC.fleteros },
  choferes: { etiqueta: 'Choferes', icono: UserSquare },
  proveedores: { etiqueta: 'Proveedores', icono: ICONOS_LC.proveedores },
} as const

export default function Entidades() {
  const [params, setParams] = useSearchParams()
  const actual = pestanaDeEntidades(params.get('pestana'))

  function elegir(valor: string) {
    const pestana = pestanaDeEntidades(valor)
    if (pestana !== actual) setParams({ pestana })
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <TituloPantalla icono={Building2}>Entidades</TituloPantalla>
      </div>
      <Tabs value={actual} onValueChange={elegir} className="gap-4">
        <TabsList className="no-imprimir">
          {PESTANAS_DE_ENTIDADES.map((p) => {
            const { etiqueta, icono: Icono } = PESTANAS[p]
            return (
              <TabsTrigger key={p} value={p}>
                <Icono className="size-4" />{etiqueta}
              </TabsTrigger>
            )
          })}
        </TabsList>
        <TabsContent value="clientes"><TercerosPorRol rol="cliente" /></TabsContent>
        <TabsContent value="fleteros"><TercerosPorRol rol="fletero" /></TabsContent>
        <TabsContent value="choferes"><Choferes encabezado={false} /></TabsContent>
        <TabsContent value="proveedores"><TercerosPorRol rol="proveedor" /></TabsContent>
      </Tabs>
    </div>
  )
}
