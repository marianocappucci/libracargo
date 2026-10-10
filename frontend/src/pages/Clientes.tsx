/** Clientes: las personas y empresas a las que se les transporta, en una entrada propia del menú (ADR-045).
 *
 *  Pedido del dueño (2026-10-10): *«clientes y proveedores pasan al menú principal»*. Era la pestaña Clientes de «Entidades»
 *  (ADR-040); el contenido y el comportamiento son los mismos (`TercerosPorRol`): el listado del rol, el alta con el rol marcado, el
 *  CUIT repetido que ofrece sumar el rol, y la ficha con la línea de Carta de porte (ADR-044).
 *
 *  Con `?ver=<id>` se abre la ficha de esa fila: así llegan los enlaces de Titulares y del CUIT repetido. El «Nuevo» va en la línea
 *  del título, arriba a la derecha (`AccionesDelTitulo`). Los enlaces de antes (`/entidades?pestana=clientes`, `/terceros`,
 *  `/configuracion?seccion=terceros`) se redirigen acá (`App.tsx`, `Configuracion.tsx`).
 */
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { PantallaConTitulo } from '@/components/AccionesDelTitulo'
import { ICONOS_LC } from '@/iconos'

import { TercerosPorRol } from './maestros/TercerosPorRol'

export default function Clientes() {
  return (
    <div>
      <PantallaConTitulo titulo={<TituloPantalla icono={ICONOS_LC.clientes}>Clientes</TituloPantalla>}>
        <TercerosPorRol rol="cliente" />
      </PantallaConTitulo>
    </div>
  )
}
