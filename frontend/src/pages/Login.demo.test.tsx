/**
 * El botón "Entrar a la demo" de la pantalla de login.
 *
 * 🔴 Existe por un defecto real de la familia, no por completitud. El
 * 2026-08-06 las seis SPA tenían `POST /auth/demo` andando en el backend —
 * verificado con `curl`— y **ninguna lo llamaba nunca**: el visitante de
 * `demo.<producto>.com.ar` veía el login normal, pidiéndole credenciales que
 * no tenía. Todo lo demás estaba bien; faltaba esta línea del frontend, y
 * nada la reclamaba porque la verificación había sido contra el endpoint.
 *
 * Por eso lo que se afirma acá es lo que ve el visitante, y no que
 * `demoPath` esté escrito en la config.
 *
 * Los dos casos van juntos a propósito: sin el negativo, un botón que se
 * dibujara SIEMPRE pasaría el positivo — y estaría ofreciéndole "entrar a la
 * demo" a los clientes de `suitrans`.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/context/AuthContext'

import Login from './Login'

function montar() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Login />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Responde la sonda `GET /auth/demo` con lo que contestaría cada instancia. */
function sondaDeDemo(respuesta: Response) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/auth/demo')) return respuesta
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
}

describe('el botón de la demo', () => {
  it('aparece cuando la instancia se declara demo', async () => {
    sondaDeDemo(new Response(
      JSON.stringify({ enabled: true, username: 'visitante', requiere_codigo: true }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    montar()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /entrar a la demo/i })).toBeInTheDocument()
    })
  })

  it('NO aparece en la instancia de un cliente, que contesta el index.html con 200', async () => {
    // El control que importa: LibraCargo sirve la SPA con un catch-all, así
    // que la sonda contra una instancia normal **devuelve 200** con HTML. Un
    // botón condicionado al código de estado aparecería en todas.
    sondaDeDemo(new Response(
      '<!DOCTYPE html><html><body>la SPA</body></html>',
      { status: 200, headers: { 'Content-Type': 'text/html' } },
    ))
    const { container } = montar()
    // Se espera a que el efecto de la sonda haya corrido y asentado.
    await waitFor(() => {
      expect(container.querySelector('input[type="password"]')).not.toBeNull()
    })
    expect(screen.queryByText(/entrar a la demo/i)).toBeNull()
  })
})
