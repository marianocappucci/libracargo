import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { AuthProvider } from '@/context/AuthContext'

import Login from './Login'

// Humo sobre el cableado de `createLogin`: si la config estuviera mal armada
// —el shim exportando otra cosa, el nombre del producto vacío— la pantalla
// compila igual y no se nota hasta abrirla en un navegador.
//
// Va dentro de `AuthProvider` porque `Login` usa `useAuth`, que tira si no
// encuentra el contexto: sin el provider el test falla por el andamiaje y no
// por la pantalla.
describe('Login', () => {
  it('muestra el nombre del producto y pide una contraseña', () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.getByText('LibraCargo')).toBeInTheDocument()
    expect(document.querySelector('input[type="password"]')).not.toBeNull()
  })
})
