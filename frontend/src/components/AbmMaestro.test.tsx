import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  // Misma firma que la real: `ApiError(status, detail)`. Si el doble tuviera
  // otra, el test pasaria y el codigo real recibiria algo distinto.
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail))
      this.status = status
      this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { ApiError } = await import('libra-ui/api-client')
const { mensajeDeError } = await import('./AbmMaestro')
const { Terceros } = await import('@/pages/maestros')

describe('AbmMaestro', () => {
  beforeEach(() => get.mockReset())

  it('muestra las filas y distingue la baja del alta', async () => {
    get.mockResolvedValue([
      { id: 1, razon_social: 'Agro Norte', activo: true, es_cliente: true },
      { id: 2, razon_social: 'Vieja SA', activo: false, es_fletero: true },
    ])
    render(<MemoryRouter><Terceros /></MemoryRouter>)

    await waitFor(() => expect(screen.getByText('Agro Norte')).toBeInTheDocument())
    expect(screen.getByText('Vieja SA')).toBeInTheDocument()
    // La columna de estado es lo que hace visible la baja lógica: sin ella las
    // dos filas se ven iguales y no hay forma de saber cuál está dada de baja.
    expect(screen.getByText('Activo')).toBeInTheDocument()
    expect(screen.getByText('Baja')).toBeInTheDocument()
    // Y los roles, que en la tabla van en una sola columna.
    expect(screen.getByText('Cliente')).toBeInTheDocument()
    expect(screen.getByText('Fletero')).toBeInTheDocument()
  })

  it('el boton de cada fila dice si da de baja o reactiva', async () => {
    get.mockResolvedValue([
      { id: 1, razon_social: 'Activa SA', activo: true, es_cliente: true },
      { id: 2, razon_social: 'Baja SA', activo: false, es_cliente: true },
    ])
    render(<MemoryRouter><Terceros /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('Activa SA')).toBeInTheDocument())
    expect(screen.getByLabelText('Dar de baja')).toBeInTheDocument()
    expect(screen.getByLabelText('Reactivar')).toBeInTheDocument()
  })

  it('la tabla vacia no se confunde con la tabla cargando', async () => {
    get.mockResolvedValue([])
    render(<MemoryRouter><Terceros /></MemoryRouter>)
    await waitFor(() =>
      expect(screen.getByText('Todavía no hay nada cargado.')).toBeInTheDocument())
  })
})

describe('mensajeDeError', () => {
  it('muestra el detalle de un 409 tal cual', () => {
    const e = new ApiError(409, 'ya existe un registro que choca con la restriccion uq_x')
    expect(mensajeDeError(e)).toContain('uq_x')
  })

  it('junta los errores de un 422 de pydantic', () => {
    // Los 422 traen una LISTA de errores, no un string. Y `libra-ui` tipa
    // `detail` como `string`, asi que el tipo MIENTE sobre lo que manda el
    // servidor: de ahi el cast, y de ahi que este caso exista. Sin el la
    // pantalla mostraria "[object Object]" y nadie sabria que corregir.
    const detalle = [{ msg: 'el tercero tiene que ser al menos una cosa' }]
    const e = new ApiError(422, detalle as unknown as string)
    expect(mensajeDeError(e)).toBe('el tercero tiene que ser al menos una cosa')
  })

  it('un error cualquiera no rompe la pantalla', () => {
    expect(mensajeDeError(new Error('se cayo la red'))).toBe('se cayo la red')
    expect(mensajeDeError('un string suelto')).toContain('No se pudo')
  })
})
