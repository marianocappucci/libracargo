/** Editar una pre factura: la pantalla de «Facturar pendientes» sobre una que ya existe.
 *
 * Es un envoltorio y no la misma ruta con otro título por una razón de menú: `/pre-facturas/:id/editar` cuelga
 * de «Pre facturas», y el icono del título de cada pantalla tiene que ser el de su entrada del sidebar (hay un
 * test que lo cruza, `titulos-con-icono.test.ts`). «Facturar pendientes» cuelga de «Comprobantes».
 */
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { FileText } from 'lucide-react'

import FacturarPendientes from '@/pages/FacturarPendientes'

export default function EditarPreFactura() {
  return (
    <FacturarPendientes
      titulo={(numero) => (
        <TituloPantalla icono={FileText}>{`Editar pre factura ${numero}`.trim()}</TituloPantalla>
      )}
    />
  )
}
