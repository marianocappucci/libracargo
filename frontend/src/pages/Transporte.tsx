/** Transporte: los fleteros, los choferes y los vehículos, en una entrada del menú (ADR-045).
 *
 *  Pedido del dueño (2026-10-10): *«En entidades está clientes, fleteros, choferes y proveedores. Entidades se va a pasar a llamar
 *  Transporte y dentro va a tener fleteros y choferes en pestañas separadas y clientes y proveedores pasan al menú principal.»*
 *  Después sumó: *Vehículos también va dentro de Transporte* (antes tenía su propia entrada, `/vehiculos`).
 *  Hasta ADR-040 esta pantalla se llamó «Entidades» y tenía cuatro pestañas; Clientes y Proveedores son hoy `pages/Clientes.tsx` y
 *  `pages/Proveedores.tsx`.
 *
 *  ## Un modelo, tres pestañas
 *
 *  - **Fleteros** es un **rol** de una misma entidad (`terceros`): una empresa que es a la vez fletero y proveedor es **una fila**,
 *    que aparece en las dos pantallas. No se carga dos veces; se le suma el rol.
 *  - **Choferes** es otra cosa: la persona que conduce, que trabaja para un fletero (el transportista propietario o contratado).
 *    Tiene su propia tabla.
 *  - **Vehículos** son las patentes (chasis y acoplado): otra tabla. No se atan a un fletero: a veces el vehículo es del chofer que
 *    maneja (el dueño, 2026-10-10); la columna «Fletero» de la tabla es la de antes y es opcional.
 *
 *  ## La pestaña va en la URL
 *
 *  `/transporte?pestana=choferes|vehiculos`, igual que Cuenta corriente y Comprobantes: la URL es la fuente de verdad, así los enlaces andan.
 *  Cambiar de pestaña **empuja** una entrada al historial (atrás vuelve a la anterior) y **descarta el resto del query**: un `?ver=`
 *  es de una pestaña. Con `?ver=<id>` se abre la ficha de esa fila, que es como llegan los enlaces de la ficha del fletero (sus
 *  choferes y vehículos) y el «Ver …» del CUIT repetido.
 *
 *  Con una `pestana` desconocida es Fleteros. Sólo la pestaña activa se monta.
 *
 *  ## Recuerda la última pestaña
 *
 *  Pedido del dueño: al entrar desde el menú (`/transporte`, sin `pestana`) se abre la última que se usó en este navegador
 *  (`pestana-recordada.ts`, `localStorage`), y Fleteros si no hay una o no se puede leer. Con `?pestana=` manda la URL. Al entrar sin
 *  ella la URL se **completa** con la pestaña que se abrió (con `replace`, sin ensuciar el historial): así el botón de atrás vuelve a una
 *  URL que dice qué pestaña era, en vez de reabrir la «recordada», que para entonces ya es la otra. Un `?ver=` sin pestaña no es de
 *  ninguna en particular y cae en Fleteros, no en la recordada: abriría la ficha de otra tabla.
 *
 *  Los enlaces de antes (`/entidades?pestana=fleteros|choferes`, `/choferes`, `/vehiculos`, `/configuracion?seccion=choferes|vehiculos`) se redirigen acá
 *  (`App.tsx`, `Configuracion.tsx`).
 */
import { CarFront, UserSquare } from 'lucide-react'
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ICONOS_LC } from '@/iconos'
import { PESTANAS_DE_TRANSPORTE, pestanaDeTransporte } from '@/navegacion'
import { leerPestanaDeTransporte, recordarPestanaDeTransporte } from '@/pestana-recordada'
import { PantallaConTitulo } from '@/components/AccionesDelTitulo'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { Choferes, Vehiculos } from './maestros'
import { TercerosPorRol } from './maestros/TercerosPorRol'

/** `UserSquare` y no `Users`: el catálogo de la familia (ADR-035) ya lo usa para Clientes, y el chofer —la persona que conduce— no es un
 *  concepto de él. `CarFront` y no `Truck`: el camión es el de los fleteros, y el catálogo de identidad no tiene un concepto «vehículo»
 *  (es el que llevaba la entrada de menú de Vehículos). */
const PESTANAS = {
  fleteros: { etiqueta: 'Fleteros', icono: ICONOS_LC.fleteros },
  choferes: { etiqueta: 'Choferes', icono: UserSquare },
  vehiculos: { etiqueta: 'Vehículos', icono: CarFront },
} as const

export default function Transporte() {
  const [params, setParams] = useSearchParams()
  const explicita = params.get('pestana')
  const actual = explicita !== null ? pestanaDeTransporte(explicita)
    : params.has('ver') ? 'fleteros' : leerPestanaDeTransporte()

  useEffect(() => {
    if (explicita === null) {
      // Sin pestaña en la URL: se completa con la que se abrió (y de ahí en más manda la URL).
      setParams((previos) => { const nuevos = new URLSearchParams(previos); nuevos.set('pestana', actual); return nuevos }, { replace: true })
    } else {
      recordarPestanaDeTransporte(actual)
    }
  }, [explicita, actual, setParams])

  function elegir(valor: string) {
    const pestana = pestanaDeTransporte(valor)
    if (pestana !== actual) setParams({ pestana })
  }

  return (
    <div>
      {/* El «Nuevo» de cada pestaña va en la línea del título, arriba a la derecha (`AccionesDelTitulo`). El ícono es el camión del
          catálogo de identidad (`fleteros`), el mismo del menú. */}
      <PantallaConTitulo titulo={<TituloPantalla icono={ICONOS_LC.fleteros}>Transporte</TituloPantalla>}>
        <Tabs value={actual} onValueChange={elegir} className="gap-4">
          <TabsList className="no-imprimir">
            {PESTANAS_DE_TRANSPORTE.map((p) => {
              const { etiqueta, icono: Icono } = PESTANAS[p]
              return (
                <TabsTrigger key={p} value={p}>
                  <Icono className="size-4" />{etiqueta}
                </TabsTrigger>
              )
            })}
          </TabsList>
          <TabsContent value="fleteros"><TercerosPorRol rol="fletero" /></TabsContent>
          <TabsContent value="choferes"><Choferes encabezado={false} /></TabsContent>
          <TabsContent value="vehiculos"><Vehiculos encabezado={false} /></TabsContent>
        </Tabs>
      </PantallaConTitulo>
    </div>
  )
}
