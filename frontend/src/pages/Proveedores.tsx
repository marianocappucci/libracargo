/** Proveedores: a quienes la empresa les compra, en una entrada propia del menú (ADR-045).
 *
 *  Pedido del dueño (2026-10-10): *«clientes y proveedores pasan al menú principal»*. Era la pestaña Proveedores de «Entidades»
 *  (ADR-040); el contenido y el comportamiento son los mismos (`TercerosPorRol`). Los comprobantes de proveedores son otra cosa: la
 *  sección «Proveedores» de Comprobantes.
 *
 *  Con `?ver=<id>` se abre la ficha de esa fila. El «Nuevo» va en la línea del título, arriba a la derecha (`AccionesDelTitulo`). Los
 *  enlaces de antes (`/entidades?pestana=proveedores`) se redirigen acá (`App.tsx`).
 */
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { PantallaConTitulo } from '@/components/AccionesDelTitulo'
import { ICONOS_LC } from '@/iconos'

import { TercerosPorRol } from './maestros/TercerosPorRol'

export default function Proveedores() {
  return (
    <div>
      <PantallaConTitulo titulo={<TituloPantalla icono={ICONOS_LC.proveedores}>Proveedores</TituloPantalla>}>
        <TercerosPorRol rol="proveedor" />
      </PantallaConTitulo>
    </div>
  )
}
