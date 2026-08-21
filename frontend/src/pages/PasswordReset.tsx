// Shim sobre libra-ui/PasswordReset, mismo patrón que Login.
//
// Las dos pantallas son **públicas**: van fuera de `Privado` en `App.tsx`,
// porque quien las usa justamente no puede entrar.
import { createForgotPassword, createResetPassword } from 'libra-ui/PasswordReset'

import { LOGO } from '@/branding'

// El mismo branding que el login: si el logo apareciera en una pantalla y no en
// la otra, la de recuperación parecería de otro sistema — que es justo la duda
// que uno no quiere sembrar donde se pide una contraseña.
const branding = {
  productName: 'LibraCargo',
  productInitial: 'C',
  logo: { src: LOGO, className: 'h-[72px] w-[72px]' },
}

export const ForgotPassword = createForgotPassword(branding)
export const ResetPassword = createResetPassword(branding)
