/** Vehículos: el ABM de los vehículos de los fleteros, en una entrada propia del menú.
 *
 *  Pedido del dueño (2026-10-08): *«vehículos hay que sacarlo de configuración y pasarlo al menú principal.»* Era una
 *  sección de Configuración; se usa a diario al armar una orden, así que sube al menú, debajo de «Entidades».
 *
 *  El título lleva el ícono del menú (`CarFront`) y el «Nuevo» va en su línea, arriba a la derecha (`AccionesDelTitulo`),
 *  como en el resto de las pantallas. Con `?ver=<id>` se abre la ficha de esa fila: así llegan los enlaces de la ficha
 *  del fletero. Los enlaces viejos (`/configuracion?seccion=vehiculos`) se redirigen acá (`Configuracion.tsx`).
 */
import { CarFront } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { PantallaConTitulo } from '@/components/AccionesDelTitulo'

import { Vehiculos as AbmVehiculos } from './maestros'

export default function Vehiculos() {
  return (
    <div>
      <PantallaConTitulo titulo={<TituloPantalla icono={CarFront}>Vehículos</TituloPantalla>}>
        <AbmVehiculos encabezado={false} />
      </PantallaConTitulo>
    </div>
  )
}
