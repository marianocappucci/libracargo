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
  // El enlace de recuperación. Sin esta línea el kit no lo pinta: la pantalla
  // queda idéntica y no falla nada, que es por lo que faltó hasta el
  // 2026-08-21 sin que ningún test lo dijera.
  forgotPasswordPath: '/forgot-password',
  wordmarkClassName: `${WORDMARK} text-[22px]`,
  redirectTo: '/',
  // Botón "Entrar a la demo" — va de la mano con `incluir_demo=True` en
  // `app/routers/auth.py`.
  //
  // 🔴 Declararlo acá NO alcanza para que aparezca, y esa es la mitad que ya
  // se pagó una vez: `libra-ui` consulta `GET /auth/demo` al montar y sólo
  // pinta el botón si la instancia contesta —con JSON— que es una demo. En
  // `suitrans` no aparece nada.
  //
  // Al revés importa igual: sin esta línea, `demo.libracargo.com.ar` mostraría
  // el login normal pidiéndole credenciales a un visitante que no tiene
  // ninguna, con el endpoint contestando perfecto del otro lado. Es lo que les
  // pasó a las seis SPA de la familia el 2026-08-06 — el `POST /auth/demo` en
  // verde, y nadie podía entrar.
  demoPath: '/auth/demo',
  useAuth,
})

export default Login
