/** Los adjuntos de una orden: el campo de archivo es el del kit (`CampoArchivo`, ADR-037 de libra-ui). */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const postForm = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, postForm, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { AdjuntosDeOrden } = await import('./AdjuntosDeOrden')
const { ApiError } = await import('libra-ui/api-client')

const orden = (estado = 'pendiente') => ({ id: 7, estado }) as unknown as Parameters<typeof AdjuntosDeOrden>[0]['orden']
const ticket = (nombre = 'ticket.pdf') => new File(['%PDF-1.4'], nombre, { type: 'application/pdf' })
const campo = () => document.getElementById('adjunto-nuevo') as HTMLInputElement

beforeEach(() => {
  get.mockReset(); postForm.mockReset()
  get.mockResolvedValue([])
})

describe('AdjuntosDeOrden', () => {
  it('el campo de archivo es el del kit: el botón de subir está en la caja y el input nativo queda oculto', async () => {
    render(<AdjuntosDeOrden orden={orden()} />)
    await screen.findByText('Todavía no tiene archivos.')
    expect(screen.getByRole('button', { name: 'Subir archivo' })).toBeInTheDocument()
    expect(campo()).toHaveAttribute('accept', 'image/*,application/pdf')
    expect(campo()).toHaveClass('sr-only')
  })

  it('elegir un archivo lo sube, lo agrega a la lista y deja el campo listo para otro', async () => {
    postForm.mockResolvedValue({ id: 1, nombre: 'ticket.pdf', tamanio: 1024, created_at: '2026-10-01T10:00:00' })
    render(<AdjuntosDeOrden orden={orden()} />)
    await screen.findByText('Todavía no tiene archivos.')
    fireEvent.change(campo(), { target: { files: [ticket()] } })

    expect(await screen.findByText('ticket.pdf')).toBeInTheDocument()
    expect(postForm).toHaveBeenCalledWith('/api/ordenes/7/adjuntos', expect.any(FormData))
    expect((postForm.mock.calls[0][1] as FormData).get('archivo')).toBeInstanceOf(File)
    // Sin archivo «elegido» en el campo: es un uso de «elegir y subir ya».
    expect(screen.queryByRole('button', { name: 'Quitar archivo' })).toBeNull()
    expect(campo().value).toBe('')
  })

  it('un 422 del servidor se muestra tal cual, y se puede elegir el mismo archivo otra vez', async () => {
    postForm.mockRejectedValueOnce(new ApiError(422, 'El archivo pesa más de 10 MB'))
    render(<AdjuntosDeOrden orden={orden()} />)
    await screen.findByText('Todavía no tiene archivos.')
    fireEvent.change(campo(), { target: { files: [ticket()] } })
    expect(await screen.findByRole('alert')).toHaveTextContent('El archivo pesa más de 10 MB')

    postForm.mockResolvedValueOnce({ id: 2, nombre: 'ticket.pdf', tamanio: 8, created_at: '2026-10-01T10:00:00' })
    fireEvent.change(campo(), { target: { files: [ticket()] } })
    await waitFor(() => expect(postForm).toHaveBeenCalledTimes(2))
  })

  it('una orden anulada no ofrece el campo', async () => {
    render(<AdjuntosDeOrden orden={orden('anulada')} />)
    expect(await screen.findByText('Una orden anulada no admite archivos nuevos.')).toBeInTheDocument()
    expect(campo()).toBeNull()
  })
})
