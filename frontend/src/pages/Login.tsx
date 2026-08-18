// Shim sobre libra-ui/Login.
//
// Sin `forgotPasswordPath`: la recuperación por correo es opt-in también en el
// backend y LibraCargo todavía no la enciende. Mostrar el enlace sería mandar
// a una pantalla que no existe.
import { createLogin } from 'libra-ui/Login'

import { useAuth } from '@/context/AuthContext'

type Usuario = { role?: string; name?: string }

export const Login = createLogin<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  redirectTo: '/',
  useAuth,
})

export default Login
