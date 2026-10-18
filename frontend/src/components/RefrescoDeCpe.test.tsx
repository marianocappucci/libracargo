/** El interruptor «Refrescar solas las cartas de porte abiertas» (ADR-051): sólo para administradores, apagado por
 *  defecto, y la pantalla dice cuándo corrió por última vez (que es lo que delata un cron que no está instalado). */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put, del: vi.fn(), postForm: vi.fn() } }
})

const sesion = vi.hoisted(() => ({ rol: 'admin' }))
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: sesion.rol, name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { RefrescoDeCpe } = await import('./RefrescoDeCpe')

const RUTA = '/api/cartas-porte/refresco'
const APAGADO = { habilitado: false, ambiente: 'produccion', ultima_corrida: null, resumen: null, es_demo: false }

beforeEach(() => {
  get.mockReset(); put.mockReset()
  sesion.rol = 'admin'
  get.mockResolvedValue(APAGADO)
})

describe('Interruptor del refresco de cartas de porte abiertas', () => {
  it('un administrador lo ve apagado, y dice que sólo consulta', async () => {
    render(<RefrescoDeCpe />)
    const interruptor = await screen.findByRole('switch', { name: 'Refrescar solas las cartas de porte abiertas' })
    await waitFor(() => expect(interruptor).toBeEnabled())
    expect(interruptor).toHaveAttribute('aria-checked', 'false')
    expect(get).toHaveBeenCalledWith(`${RUTA}/estado`)
    expect(screen.getByText(/no emite ni anula nada/)).toBeInTheDocument()
  })

  it('quien no es administrador no lo ve, y ni siquiera pide el estado', () => {
    sesion.rol = 'operador'
    const { container } = render(<RefrescoDeCpe />)
    expect(container).toBeEmptyDOMElement()
    expect(get).not.toHaveBeenCalled()
  })

  it('prender manda PUT /refresco/habilitado, sin confirmación: leer no se paga', async () => {
    put.mockResolvedValue({ ...APAGADO, habilitado: true })
    render(<RefrescoDeCpe />)
    const interruptor = await screen.findByRole('switch')
    await waitFor(() => expect(interruptor).toBeEnabled())
    fireEvent.click(interruptor)

    await waitFor(() => expect(put).toHaveBeenCalledWith(`${RUTA}/habilitado`, { habilitado: true }))
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true'))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('prendido y sin corridas avisa que falta la tarea programada del servidor', async () => {
    get.mockResolvedValue({ ...APAGADO, habilitado: true })
    render(<RefrescoDeCpe />)
    expect(await screen.findByText(/Todavía no corrió/)).toHaveTextContent('falta la tarea programada del servidor')
  })

  it('prendido y con corridas dice cuándo fue la última y qué pasó', async () => {
    get.mockResolvedValue({
      ...APAGADO, habilitado: true, ultima_corrida: '2026-10-18T12:30:00-03:00', resumen: '3 actualizadas, 1 con error',
    })
    render(<RefrescoDeCpe />)
    const estado = await screen.findByRole('status')
    expect(estado).toHaveTextContent('Última corrida:')
    expect(estado).toHaveTextContent('3 actualizadas, 1 con error')
    expect(estado).not.toHaveTextContent('Todavía no corrió')
  })

  it('apagado no habla de corridas', async () => {
    render(<RefrescoDeCpe />)
    await screen.findByRole('switch')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('en una demo avisa que no corre', async () => {
    get.mockResolvedValue({ ...APAGADO, ambiente: null, es_demo: true })
    render(<RefrescoDeCpe />)
    expect(await screen.findByText(/instancia de demostración/)).toBeInTheDocument()
  })

  it('sin certificado avisa que no hay nada que consultar', async () => {
    get.mockResolvedValue({ ...APAGADO, ambiente: null })
    render(<RefrescoDeCpe />)
    expect(await screen.findByText(/Todavía no hay un certificado/)).toBeInTheDocument()
  })

  it('un error del servidor se muestra y el interruptor no cambia', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    put.mockRejectedValue(new (ApiError as unknown as new (s: number, d: string) => Error)(
      409, 'Primero cargá los datos de la empresa en Configuración.'))
    render(<RefrescoDeCpe />)
    const interruptor = await screen.findByRole('switch')
    await waitFor(() => expect(interruptor).toBeEnabled())
    fireEvent.click(interruptor)
    expect(await screen.findByRole('alert')).toHaveTextContent('Primero cargá los datos de la empresa en Configuración.')
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  })
})
