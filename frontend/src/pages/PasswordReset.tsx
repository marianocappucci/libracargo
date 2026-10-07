// Shim sobre libra-ui/PasswordReset, mismo patrón que Login.
//
// Las dos pantallas son **públicas**: van fuera de `Privado` en `App.tsx`,
// porque quien las usa justamente no puede entrar.
import { createForgotPassword, createResetPassword } from 'libra-ui/PasswordReset'

// El mismo branding que el login. 🔴 `createForgotPassword`/`createResetPassword` (libra-ui v0.123.0) NO aceptan `logo` ni `producto`: dibujan la
// inicial sobre `bg-primary` (que con `aplicarIdentidad` ya es el acento del producto). Se retira el `logo` que se pasaba y el kit ignoraba;
// la marca de estas dos pantallas es una mejora pendiente en libra-ui.
const branding = {
  productName: 'LibraCargo',
  productInitial: 'C',
}

// El pedido de enlace lleva el mismo captcha que el login (sin él, el endpoint
// manda correos a pedido de cualquiera). El cambio de contraseña no: ahí ya
// hace falta el token que llegó por correo.
export const ForgotPassword = createForgotPassword({ ...branding, captchaPath: '/auth/captcha' })
export const ResetPassword = createResetPassword(branding)
