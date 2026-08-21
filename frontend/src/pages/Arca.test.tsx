import { render, screen } from '@testing-library/react'
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
  return { ApiError, api: { get, put, post: vi.fn(), postForm: vi.fn(), del: vi.fn() } }
})

const { FacturacionArca } = await import('./Arca')

function fila(extra: Record<string, unknown> = {}) {
  return {
    razon_social_id: 1, razon_social: 'Suitrans', cuit: '30-11111111-1', punto_venta: 1,
    ambiente: 'homologacion', habilitado: false,
    certificado: null, tiene_clave: false, clave_nombre: null, coinciden: null,
    ...extra,
  }
}

const CERT = {
  nombre: 'suitrans.crt', sujeto: 'CN=suitrans', emisor: 'CN=ARCA',
  vence: '2028-01-15T00:00:00Z', vencido: false, dias_para_vencer: 500,
}

describe('FacturacionArca', () => {
  // Cuerpo de bloque: `mockReset()` devuelve el mock y vitest llamaria a lo
  // devuelto como hook de limpieza.
  beforeEach(() => { get.mockReset(); put.mockReset() })

  it('sin credenciales lo dice, y no deja habilitar', async () => {
    get.mockResolvedValue([fila()])
    render(<FacturacionArca />)
    expect(await screen.findByText(/Todavía no hay credenciales/)).toBeInTheDocument()
    const casilla = screen.getByLabelText('Habilitar facturación electrónica')
    expect((casilla as HTMLInputElement).disabled).toBe(true)
  })

  it('con una sola mitad dice cuál falta', async () => {
    get.mockResolvedValue([fila({ certificado: CERT })])
    render(<FacturacionArca />)
    expect(await screen.findByText(/Falta la clave privada/)).toBeInTheDocument()
  })

  it('🔴 avisa cuando el certificado y la clave NO son pareja', async () => {
    // Es el hallazgo que ningun nombre de archivo puede dar: los dos archivos
    // son validos por separado y juntos no autentican.
    get.mockResolvedValue([fila({
      certificado: CERT, tiene_clave: true, clave_nombre: 'otra.key', coinciden: false,
    })])
    render(<FacturacionArca />)
    const alarma = await screen.findByRole('alert')
    expect(alarma.textContent).toContain('no son pareja')
  })

  it('avisa que el certificado vencio', async () => {
    get.mockResolvedValue([fila({
      certificado: { ...CERT, vencido: true, dias_para_vencer: -3, vence: '2026-08-01T00:00:00Z' },
      tiene_clave: true, clave_nombre: 'k.key', coinciden: true,
    })])
    render(<FacturacionArca />)
    const alarma = await screen.findByRole('alert')
    // La fecha en dd-mm-aaaa, como manda el estandar de la casa.
    expect(alarma.textContent).toContain('01-08-2026')
  })

  it('avisa ANTES de que venza, no despues', async () => {
    // Un certificado dura dos anios: el dia que vence, la facturacion deja de
    // andar sin que nadie haya tocado nada. Avisar recien ahi no sirve.
    get.mockResolvedValue([fila({
      certificado: { ...CERT, dias_para_vencer: 12 },
      tiene_clave: true, clave_nombre: 'k.key', coinciden: true,
    })])
    render(<FacturacionArca />)
    expect(await screen.findByText(/vence en 12 días/)).toBeInTheDocument()
  })

  it('con todo en orden lo dice, y deja habilitar', async () => {
    // El control de los de arriba: sin este, una pantalla que gritara SIEMPRE
    // pasaria igual y las alarmas dejarian de significar algo.
    get.mockResolvedValue([fila({
      certificado: CERT, tiene_clave: true, clave_nombre: 'k.key', coinciden: true,
    })])
    render(<FacturacionArca />)
    expect(await screen.findByText(/verificados/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    const casilla = screen.getByLabelText('Habilitar facturación electrónica')
    expect((casilla as HTMLInputElement).disabled).toBe(false)
  })

  it('sin razones sociales explica por donde empezar', async () => {
    get.mockResolvedValue([])
    render(<FacturacionArca />)
    expect(await screen.findByText(/Razones sociales/)).toBeInTheDocument()
  })
})
