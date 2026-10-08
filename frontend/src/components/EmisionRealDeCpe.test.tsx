/** El interruptor «Emitir Cartas de Porte reales» (ADR-043): sólo para administradores, apagado por defecto, y prender
 *  pide una confirmación (apagar no). */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const { EmisionRealDeCpe } = await import('./EmisionRealDeCpe')

const RUTA = '/api/cartas-porte/emision'

beforeEach(() => {
  get.mockReset(); put.mockReset()
  sesion.rol = 'admin'
  get.mockResolvedValue({ ambiente: 'produccion', habilitada: false, puede_emitir: false })
})

describe('Interruptor de la emisión real de cartas de porte', () => {
  it('un administrador lo ve apagado y con la advertencia', async () => {
    render(<EmisionRealDeCpe />)
    const interruptor = await screen.findByRole('switch', { name: 'Emitir Cartas de Porte reales' })
    await waitFor(() => expect(interruptor).toBeEnabled())
    expect(interruptor).toHaveAttribute('aria-checked', 'false')
    expect(get).toHaveBeenCalledWith(`${RUTA}/estado`)
    expect(screen.getByText(/emite Cartas de Porte REALES ante ARCA/)).toBeInTheDocument()
    expect(screen.getByText('La emisión real está apagada.')).toBeInTheDocument()
  })

  it('quien no es administrador no lo ve, y ni siquiera pide el estado', () => {
    sesion.rol = 'operador'
    const { container } = render(<EmisionRealDeCpe />)
    expect(container).toBeEmptyDOMElement()
    expect(get).not.toHaveBeenCalled()
  })

  it('prender pide confirmación y recién entonces manda PUT /emision/habilitada', async () => {
    put.mockResolvedValue({ ambiente: 'produccion', habilitada: true, puede_emitir: true })
    render(<EmisionRealDeCpe />)
    const interruptor = await screen.findByRole('switch')
    await waitFor(() => expect(interruptor).toBeEnabled())
    fireEvent.click(interruptor)

    const dialogo = await screen.findByRole('alertdialog')
    expect(within(dialogo).getByText('¿Prender la emisión de Cartas de Porte reales?')).toBeInTheDocument()
    expect(put).not.toHaveBeenCalled()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Prender' }))

    await waitFor(() => expect(put).toHaveBeenCalledWith(`${RUTA}/habilitada`, { habilitada: true }))
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true'))
    expect(screen.getByText('La emisión real está prendida.')).toBeInTheDocument()
  })

  it('cancelar la confirmación deja todo apagado', async () => {
    render(<EmisionRealDeCpe />)
    const interruptor = await screen.findByRole('switch')
    await waitFor(() => expect(interruptor).toBeEnabled())
    fireEvent.click(interruptor)
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(put).not.toHaveBeenCalled()
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  })

  it('apagar no pide confirmación', async () => {
    get.mockResolvedValue({ ambiente: 'produccion', habilitada: true, puede_emitir: true })
    put.mockResolvedValue({ ambiente: 'produccion', habilitada: false, puede_emitir: false })
    render(<EmisionRealDeCpe />)
    const interruptor = await screen.findByRole('switch')
    await waitFor(() => expect(interruptor).toHaveAttribute('aria-checked', 'true'))
    fireEvent.click(interruptor)
    await waitFor(() => expect(put).toHaveBeenCalledWith(`${RUTA}/habilitada`, { habilitada: false }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('un error del servidor se muestra y el interruptor no cambia', async () => {
    const { ApiError } = await import('libra-ui/api-client')
    put.mockRejectedValue(new (ApiError as unknown as new (s: number, d: string) => Error)(
      409, 'Primero cargá los datos de la empresa en Configuración.'))
    render(<EmisionRealDeCpe />)
    const interruptor = await screen.findByRole('switch')
    await waitFor(() => expect(interruptor).toBeEnabled())
    fireEvent.click(interruptor)
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Prender' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Primero cargá los datos de la empresa en Configuración.')
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  })

  it('en homologación avisa que se puede emitir de prueba sin prenderlo', async () => {
    get.mockResolvedValue({ ambiente: 'homologacion', habilitada: false, puede_emitir: true })
    render(<EmisionRealDeCpe />)
    expect(await screen.findByText(/homologación/)).toBeInTheDocument()
  })
})
