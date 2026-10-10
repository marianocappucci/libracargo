/** El menú con Clientes, Proveedores y Transporte, y que ningún enlace viejo se rompa (ADR-045, que reemplaza en parte a ADR-040).
 *
 *  Pedido del dueño (2026-10-10): «Entidades se va a pasar a llamar Transporte y dentro va a tener fleteros y choferes en pestañas
 *  separadas y clientes y proveedores pasan al menú principal»; después sumó Vehículos como tercera pestaña de Transporte.
 *
 *  Se monta la `App` entera, con su router y su menú de verdad: lo que se prueba son las rutas y las redirecciones, que es lo que un
 *  marcador, un correo o el log de actividad usan. Las pantallas en sí tienen sus tests (`Clientes`, `Proveedores`, `Transporte`).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { responder, simularMatchMedia } from '@/test/entidades-de-prueba'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'operador', name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: App } = await import('@/App')
const { Configuracion } = await import('@/pages/Configuracion')

function Ubicacion() {
  const { pathname, search } = useLocation()
  return <p data-testid="ubicacion">{pathname + search}</p>
}
const ubicacion = () => screen.getByTestId('ubicacion').textContent

function abrir(url: string) {
  return render(<MemoryRouter initialEntries={[url]}><App /><Ubicacion /></MemoryRouter>)
}

beforeEach(() => {
  get.mockReset()
  responder(get)
  simularMatchMedia()
  window.localStorage.clear()
})

/** El menú lateral del kit (no es un `<nav>`): su contenido, con el enlace de cada entrada. */
const menu = () => document.querySelector('[data-sidebar="content"]') as HTMLElement

/** Las entradas del menú lateral, en el orden en que se dibujan. */
const entradasDelMenu = () => within(menu()).getAllByRole('link')
  .map((a) => [a.textContent?.trim(), a.getAttribute('href')] as const)

describe('el menú', () => {
  it('🔴 muestra Clientes, Proveedores y Transporte, en ese orden y donde estaba Entidades; ya no Entidades ni Vehículos', async () => {
    abrir('/')
    await screen.findByRole('link', { name: 'Clientes' })
    const entradas = entradasDelMenu()
    const nombres = entradas.map(([n]) => n)
    expect(entradas).toEqual(expect.arrayContaining([
      ['Clientes', '/clientes'], ['Proveedores', '/proveedores'], ['Transporte', '/transporte'],
    ]))
    expect(nombres).not.toContain('Entidades')
    expect(nombres).not.toContain('Vehículos')
    expect(entradas.map(([, href]) => href)).not.toContain('/entidades')
    expect(entradas.map(([, href]) => href)).not.toContain('/vehiculos')
    const i = nombres.indexOf('Clientes')
    expect(nombres.slice(i - 1, i + 4)).toEqual(['Cartas de porte', 'Clientes', 'Proveedores', 'Transporte', 'Cuenta corriente'])
  })

  it('el menú marca la entrada de la pantalla en que se está', async () => {
    abrir('/transporte?pestana=choferes')
    await screen.findByRole('heading', { name: 'Transporte' })
    const enlace = (nombre: string) => within(menu()).getByRole('link', { name: nombre })
    expect(enlace('Transporte')).toHaveAttribute('aria-current', 'page')
    expect(enlace('Clientes')).not.toHaveAttribute('aria-current')
  })

  it('🔑 tocar «Transporte» en el menú abre la pantalla (sin ?pestana=: la última usada, o Fleteros)', async () => {
    abrir('/')
    await screen.findByRole('link', { name: 'Clientes' })
    fireEvent.click(within(menu()).getByRole('link', { name: 'Transporte' }))
    expect(await screen.findByRole('heading', { name: 'Transporte' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Fleteros' })).toHaveAttribute('data-state', 'active')
  })

  it('🔑 y con una pestaña recordada, el menú abre esa', async () => {
    window.localStorage.setItem('libracargo.transporte.pestana', 'vehiculos')
    abrir('/')
    await screen.findByRole('link', { name: 'Clientes' })
    fireEvent.click(within(menu()).getByRole('link', { name: 'Transporte' }))
    expect(await screen.findByText('AB123CD')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vehículos' })).toHaveAttribute('data-state', 'active')
  })
})

describe('las pantallas nuevas están en sus rutas', () => {
  it.each([
    ['/clientes', 'Clientes', 'Agro Norte SA'],
    ['/proveedores', 'Proveedores', 'Ferretería Central'],
    ['/transporte', 'Transporte', 'Transportes del Sur'],
  ])('%s abre «%s»', async (ruta, titulo, fila) => {
    abrir(ruta)
    expect(await screen.findByRole('heading', { name: titulo })).toBeInTheDocument()
    expect(await screen.findByText(fila)).toBeInTheDocument()
  })
})

describe('🔴 los enlaces viejos no se rompen', () => {
  it.each([
    // /entidades, con y sin `ver`, a la pantalla de cada pestaña
    ['/entidades', '/clientes'],
    ['/entidades?pestana=clientes', '/clientes'],
    ['/entidades?pestana=clientes&ver=1', '/clientes?ver=1'],
    ['/entidades?pestana=proveedores', '/proveedores'],
    ['/entidades?pestana=proveedores&ver=3', '/proveedores?ver=3'],
    ['/entidades?pestana=fleteros', '/transporte?pestana=fleteros'],
    ['/entidades?pestana=fleteros&ver=2', '/transporte?pestana=fleteros&ver=2'],
    ['/entidades?pestana=choferes', '/transporte?pestana=choferes'],
    ['/entidades?pestana=choferes&ver=11', '/transporte?pestana=choferes&ver=11'],
    ['/entidades?pestana=cualquier-cosa', '/clientes'],
    // las rutas más viejas todavía
    ['/terceros', '/clientes'],
    ['/choferes', '/transporte?pestana=choferes'],
    // Vehículos ya no es una entrada: es una pestaña de Transporte, con todo lo que traía
    ['/vehiculos', '/transporte?pestana=vehiculos'],
    ['/vehiculos?ver=21', '/transporte?pestana=vehiculos&ver=21'],
    ['/vehiculos?ver=21&otro=x', '/transporte?pestana=vehiculos&ver=21&otro=x'],
    // desde Configuración, directo al destino de hoy
    ['/configuracion?seccion=terceros', '/clientes'],
    ['/configuracion?seccion=terceros&ver=1', '/clientes?ver=1'],
    ['/configuracion?seccion=choferes', '/transporte?pestana=choferes'],
    ['/configuracion?seccion=choferes&ver=11', '/transporte?pestana=choferes&ver=11'],
    ['/configuracion?seccion=vehiculos', '/transporte?pestana=vehiculos'],
    ['/configuracion?seccion=vehiculos&ver=21', '/transporte?pestana=vehiculos&ver=21'],
  ])('%s lleva a %s', async (viejo, nuevo) => {
    abrir(viejo)
    await waitFor(() => expect(ubicacion()).toBe(nuevo))
  })

  it('🔑 y la ficha que traía el enlace queda abierta en la pantalla nueva', async () => {
    const { unmount } = abrir('/entidades?pestana=clientes&ver=1')
    expect(within(await screen.findByRole('dialog')).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    unmount()

    const otro = abrir('/entidades?pestana=proveedores&ver=3')
    expect(within(await screen.findByRole('dialog')).getByLabelText('Razón social')).toHaveValue('Ferretería Central')
    otro.unmount()

    const tercero = abrir('/entidades?pestana=choferes&ver=11')
    expect(within(await screen.findByRole('dialog')).getByLabelText('Nombre')).toHaveValue('Juan Pérez')
    expect(ubicacion()).toBe('/transporte?pestana=choferes&ver=11')
    tercero.unmount()

    abrir('/vehiculos?ver=21')
    expect(within(await screen.findByRole('dialog')).getByLabelText('Patente del chasis')).toHaveValue('AB123CD')
    expect(ubicacion()).toBe('/transporte?pestana=vehiculos&ver=21')
  })
})

describe('Configuración sin Terceros, Choferes ni Vehículos', () => {
  it('🔑 ya no tiene las pestañas Terceros, Choferes ni Vehículos; quedan las demás', async () => {
    render(<MemoryRouter initialEntries={['/configuracion']}><Configuracion /></MemoryRouter>)
    const pestanas = (await screen.findAllByRole('tab')).map((t) => t.textContent)
    expect(pestanas).not.toContain('Terceros')
    expect(pestanas).not.toContain('Choferes')
    expect(pestanas).not.toContain('Vehículos')
    for (const queda of ['Localidades', 'Tipos de carga', 'Tarifario de referencia']) {
      expect(pestanas).toContain(queda)
    }
  })

  it('los demás enlaces de Configuración no se tocan', async () => {
    render(<MemoryRouter initialEntries={['/configuracion?seccion=localidades']}><Configuracion /></MemoryRouter>)
    const pestana = await screen.findByRole('tab', { name: 'Localidades' })
    expect(pestana).toHaveAttribute('data-state', 'active')
  })
})
