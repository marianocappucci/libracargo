/** Comprobantes: la entrada del menú, con dos pestañas — Clientes y Proveedores.
 *
 *  Antes eran tres entradas sueltas del menú («Comprobantes», «Pre facturas» y «Comprobantes de proveedores»).
 *  Son lo mismo visto de dos lados: lo que se le emite al cliente y lo que entrega el proveedor.
 *
 *  - **Clientes** es `Comprobantes`: las facturas y notas emitidas, con los accesos a «Facturar pendientes»
 *    y a «Pre facturas» (que ya no está en el menú).
 *  - **Proveedores** es `Gastos`, sin cambios de comportamiento.
 *
 *  ## La pestaña va en la URL
 *
 *  `/comprobantes` es Clientes y `/comprobantes?seccion=proveedores` es Proveedores — el mismo mecanismo que
 *  la Configuración de la familia (`?seccion=`), y se combina con el `?ver=` que cada pantalla ya tenía
 *  (`?seccion=proveedores&ver=5` abre ese comprobante de proveedor). Cambiar de pestaña **empuja** una entrada
 *  al historial, así atrás/adelante vuelven a la pestaña anterior, y **descarta el resto del query**: un
 *  `?ver=` es de una pestaña y no tiene sentido en la otra.
 *
 *  Los enlaces de antes siguen andando: `/gastos` (con su `?ver=`) se redirige en `App.tsx` a la pestaña
 *  Proveedores, y `/pre-facturas*` y `/comprobantes/facturar` son pantallas propias que cuelgan de esta entrada.
 *
 *  Sólo la pestaña activa se monta (`TabsContent` desmonta la otra): cada una pide sus datos al abrirse, y el
 *  `?ver=` lo lee quien está a la vista.
 *
 *  Permisos: las dos pantallas las ven los mismos roles que antes (el backend exige `require_staff` en las
 *  dos y el frontend nunca las gateó por rol), así que no hay pestaña que ocultar.
 */
import { useSearchParams } from 'react-router-dom'

import { ICONOS_LC } from '@/iconos'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { seccionDe } from '@/navegacion'
import { PantallaConTitulo } from '@/components/AccionesDelTitulo'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import Comprobantes from './Comprobantes'
import Gastos from './Gastos'

export default function ComprobantesSeccion() {
  const [params, setParams] = useSearchParams()
  const actual = seccionDe(params.get('seccion'))

  function elegir(valor: string) {
    const seccion = seccionDe(valor)
    setParams(seccion === 'clientes' ? {} : { seccion })
  }

  return (
    <div>
      <PantallaConTitulo titulo={<TituloPantalla icono={ICONOS_LC.comprobantes}>Comprobantes</TituloPantalla>}>
        <Tabs value={actual} onValueChange={elegir} className="gap-4">
          <TabsList className="no-imprimir">
            <TabsTrigger value="clientes">
              <ICONOS_LC.clientes className="size-4" />Clientes
            </TabsTrigger>
            <TabsTrigger value="proveedores">
              <ICONOS_LC.proveedores className="size-4" />Proveedores
            </TabsTrigger>
          </TabsList>
          <TabsContent value="clientes"><Comprobantes /></TabsContent>
          <TabsContent value="proveedores"><Gastos /></TabsContent>
        </Tabs>
      </PantallaConTitulo>
    </div>
  )
}
