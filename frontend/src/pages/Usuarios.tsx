/** ABM de usuarios — el de `libra-ui`, apuntado al router de este producto.
 *
 * No se reimplementa nada: la pantalla es la misma que la de los otros
 * productos de la familia, y lo único propio es la ruta del backend. El resto
 * de LibraCargo tiene su API en castellano, así que el router va en
 * `/api/usuarios` y no en el `/users` que trae por default.
 *
 * `roles` queda en su default (`staff`/`admin`, en ese orden): es exactamente
 * la tupla `("admin", "staff")` del `UserRepository` de este producto, así
 * que no hay nada propio que pasarle.
 */
import { UserCog } from 'lucide-react'
import { Usuarios as UsuariosCompartido } from 'libra-ui/Usuarios'
import { useAuth } from '@/context/AuthContext'

export default function Usuarios() {
  const { user } = useAuth()

  return (
    <div className="p-6">
      {/* El título lo pone la pantalla compartida, que desde libra-ui v0.34.0
          recibe el icono del sidebar de este producto. Antes había uno acá
          también y la pantalla decía «Usuarios» dos veces. */}
      <UsuariosCompartido
        icono={UserCog}
        basePath="/api/usuarios"
        // El backend adoptó `libraauth.usuarios.build_users_router()`
        // (ADR-018, v0.43.0), que trae el `DELETE` con las guardas del único
        // admin -- recién con eso tiene sentido ofrecer el botón acá.
        permitirEliminar
        // Oculta el botón «Eliminar» en la fila propia: el backend igual lo
        // rechaza (409), pero mejor no ofrecerlo.
        usuarioActualId={user?.id}
      />
    </div>
  )
}
