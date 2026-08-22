import { UserCog } from 'lucide-react'
/** ABM de usuarios — el de , apuntado al router de este producto.
 *
 * No se reimplementa nada: la pantalla es la misma que la de los otros
 * productos de la familia, y lo único propio es la ruta del backend. El resto
 * de LibraCargo tiene su API en castellano, así que el router va en
 *  y no en el  que trae por default.
 */
import { Usuarios as UsuariosCompartido } from 'libra-ui/Usuarios'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

export default function Usuarios() {
  return (
    <div className="p-6">
      <TituloPantalla icono={UserCog} className="mb-4">Usuarios</TituloPantalla>
      <UsuariosCompartido basePath="/api/usuarios" />
    </div>
  )
}
