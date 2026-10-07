/** Editar una pre factura: la pantalla de «Facturar pendientes» sobre una que ya existe.
 *
 * Es un envoltorio y no la misma ruta con otro título: acá el título es «Editar pre factura N» y no «Facturar
 * pendientes». Las dos cuelgan de «Comprobantes» en el menú, y por eso el icono del título es el de esa
 * entrada (`Receipt`): el de cada pantalla tiene que ser el de su entrada del sidebar.
 */
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

import { ICONOS_LC } from '@/iconos'
import FacturarPendientes from '@/pages/FacturarPendientes'

export default function EditarPreFactura() {
  return (
    <FacturarPendientes
      titulo={(numero) => (
        <TituloPantalla icono={ICONOS_LC.preFacturas}>{`Editar pre factura ${numero}`.trim()}</TituloPantalla>
      )}
    />
  )
}
