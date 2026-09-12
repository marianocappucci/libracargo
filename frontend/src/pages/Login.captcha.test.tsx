/**
 * El recuadro «No soy un robot» del login y de «olvidé mi contraseña».
 *
 * `libra-ui` sólo lo pinta si la sonda `GET /auth/captcha` contesta un
 * desafío, así que lo que se puede romper de este lado es que la pantalla deje
 * de consultarla — sin `captchaPath` el kit no la pide nunca, la pantalla queda
 * idéntica y el login contesta 400 a todo el mundo, porque el backend lo exige
 * (`captcha=True` en `app/routers/auth.py`).
 *
 * La sonda contesta 404: el widget en sí (el web component de ALTCHA) lo prueba
 * libra-ui, y en jsdom no tiene workers.
 */
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/context/AuthContext'

import Login from './Login'
import { ForgotPassword } from './PasswordReset'

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Registra cada URL pedida; la sonda del captcha contesta 404. */
function registrarPedidos(): string[] {
  const pedidos: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    pedidos.push(url)
    if (url.includes('/auth/captcha')) return new Response('', { status: 404 })
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return pedidos
}

describe('el captcha', () => {
  it('el login consulta /auth/captcha', async () => {
    const pedidos = registrarPedidos()
    render(
      <MemoryRouter>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(pedidos.some((u) => u.includes('/auth/captcha'))).toBe(true)
    })
  })

  it('«olvidé mi contraseña» también la consulta', async () => {
    const pedidos = registrarPedidos()
    render(
      <MemoryRouter>
        <ForgotPassword />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(pedidos.some((u) => u.includes('/auth/captcha'))).toBe(true)
    })
  })
})
