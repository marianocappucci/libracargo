/** ABM de usuarios — el de `libra-ui`, apuntado al router de este producto.
 *
 * No se reimplementa nada: la pantalla es la misma que la de los otros
 * productos de la familia, y lo único propio es la ruta del backend. El resto
 * de LibraCargo tiene su API en castellano, así que el router va en
 * `/api/usuarios` y no en el `/users` que trae por default.
 */
import { UserCog } from 'lucide-react'
import { Usuarios as UsuariosCompartido } from 'libra-ui/Usuarios'

export default function Usuarios() {
  return (
    <div className="p-6">
      {/* El título lo pone la pantalla compartida, que desde libra-ui v0.34.0
          recibe el icono del sidebar de este producto. Antes había uno acá
          también y la pantalla decía «Usuarios» dos veces. */}
      <UsuariosCompartido icono={UserCog} basePath="/api/usuarios" />
    </div>
  )
}
