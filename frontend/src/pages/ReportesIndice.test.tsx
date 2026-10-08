/** El índice de reportes: cada tarjeta lleva el ícono de su concepto del catálogo (`libra-ui/iconos-indicador`, ADR-038). */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { default: ReportesIndice } = await import('./ReportesIndice')

const reporte = (slug: string, titulo: string, detalle = false) => ({
  slug, titulo, descripcion: `Descripción de ${titulo}`, parametros: ['rango'], detalle, solo_admin: false,
})

describe('el índice de reportes', () => {
  beforeEach(() => {
    get.mockReset()
    get.mockResolvedValue([
      reporte('saldos', 'Saldos de cuenta corriente'),
      reporte('por-ruta', 'Rutas más transitadas'),
      reporte('listado-ordenes', 'Listado de órdenes', true),
      reporte('reporte-que-el-servidor-sumo', 'Uno nuevo'),
    ])
  })

  it('🔴 cada tarjeta es una TarjetaReporte con el concepto de su slug, y un slug desconocido cae en «reportes»', async () => {
    render(<MemoryRouter><ReportesIndice /></MemoryRouter>)
    await screen.findByText('Saldos de cuenta corriente')

    const tarjetas = Array.from(document.querySelectorAll('[data-slot="tarjeta-reporte"]'))
    expect(tarjetas.map((t) => t.getAttribute('data-concepto'))).toEqual(['saldos', 'rutas', 'reportes', 'ordenesDeCarga'])
  })

  it('cada tarjeta lleva a su reporte y conserva el texto de siempre', async () => {
    render(<MemoryRouter><ReportesIndice /></MemoryRouter>)
    const tarjeta = (await screen.findByText('Rutas más transitadas')).closest('a')
    expect(tarjeta).toHaveAttribute('href', '/reportes/por-ruta')
    expect(screen.getByText('Descripción de Rutas más transitadas')).toBeInTheDocument()
    expect(screen.getAllByText('Se filtra por: fechas')).toHaveLength(4)
  })
})
