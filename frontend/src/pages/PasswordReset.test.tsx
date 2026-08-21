import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Que las dos pantallas de recuperación sean **públicas**, y que el login
 * ofrezca el enlace.
 *
 * 🔴 Lo segundo es lo que se reportó como faltante y lo que un test no obvio
 * cubre: sin `forgotPasswordPath` el kit simplemente no pinta el enlace — la
 * pantalla queda idéntica y no falla nada.
 */

// Se mockea `libra-ui/AuthContext` y no el shim del producto: `libra-ui/Login`
// importa `useAuth` del kit directamente, así que mockear el re-export lo deja
// afuera y el render del login revienta en vez de probar nada.
vi.mock('libra-ui/AuthContext', async (original) => {
  const real = await original<Record<string, unknown>>()
  return {
    ...real,
    AuthProvider: ({ children }: { children: React.ReactNode }) => children,
    useAuth: () => ({ user: null, loading: false, login: vi.fn(), logout: vi.fn() }),
  }
})

const { default: App } = await import('../App')

function enLaRuta(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <App />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('recuperación de contraseña, sin sesión', () => {
  it('/forgot-password abre la pantalla de recuperación', async () => {
    enLaRuta('/forgot-password')
    expect(await screen.findByRole('button', { name: /Enviar enlace/i })).toBeInTheDocument()
  })

  it('/reset-password con token abre la de cambio', async () => {
    enLaRuta('/reset-password?token=un-token-cualquiera')
    expect(
      await screen.findByRole('button', { name: /Guardar contraseña/i }),
    ).toBeInTheDocument()
  })

  it('/reset-password SIN token explica que el enlace está incompleto', async () => {
    enLaRuta('/reset-password')
    expect(await screen.findByText(/no trae el código de recuperación/i)).toBeInTheDocument()
  })

  it('el login ofrece el enlace de recuperación', async () => {
    enLaRuta('/login')
    const enlace = await screen.findByRole('link', { name: /Olvidaste tu contraseña/i })
    expect(enlace).toHaveAttribute('href', '/forgot-password')
  })

  it('una ruta privada sigue mandando al login', async () => {
    // Control negativo: sin él, un ruteo que mostrara la recuperación en
    // cualquier URL pasaría los tests de arriba.
    enLaRuta('/ordenes')
    expect(await screen.findByLabelText('Usuario')).toBeInTheDocument()
  })
})
