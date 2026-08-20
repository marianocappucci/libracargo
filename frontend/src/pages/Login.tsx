// Shim sobre libra-ui/Login.
//
// Sin `forgotPasswordPath`: la recuperación por correo es opt-in también en el
// backend y LibraCargo todavía no la enciende. Mostrar el enlace sería mandar
// a una pantalla que no existe.
import { createLogin } from 'libra-ui/Login'

import { LOGO, WORDMARK } from '@/branding'

import { useAuth } from '@/context/AuthContext'

type Usuario = { role?: string; name?: string }

export const Login = createLogin<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  // El logo y el nombre en Montserrat Bold. `productInitial` sigue arriba
  // porque es el fallback del motor: si el asset no resuelve, la pantalla
  // muestra la inicial en vez de un hueco.
  logo: { src: LOGO, className: 'h-[72px] w-[72px]' },
  wordmarkClassName: `${WORDMARK} text-[22px]`,
  redirectTo: '/',
  useAuth,
})

export default Login
