/** ABM de usuarios — el de , apuntado al router de este producto.
 *
 * No se reimplementa nada: la pantalla es la misma que la de los otros
 * productos de la familia, y lo único propio es la ruta del backend. El resto
 * de LibraCargo tiene su API en castellano, así que el router va en
 *  y no en el  que trae por default.
 */
import { Usuarios as UsuariosCompartido } from 'libra-ui/Usuarios'

export default function Usuarios() {
  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-semibold">Usuarios</h1>
      <UsuariosCompartido basePath="/api/usuarios" />
    </div>
  )
}
