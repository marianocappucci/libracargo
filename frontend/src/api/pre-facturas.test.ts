import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', () => ({ api: { get, post, put, del: vi.fn() } }))

const {
  ESTADOS_ABIERTOS, NOMBRE_DE_ESTADO, TIPO_DE_CODIGO, TONO_DE_ESTADO, preFacturas, tipoDe,
} = await import('./pre-facturas')

describe('estados', () => {
  beforeEach(() => { get.mockReset(); post.mockReset(); put.mockReset() })

  it('se dicen en castellano, como los dice el operador', () => {
    expect(NOMBRE_DE_ESTADO).toEqual({
      pendiente: 'Pendiente', enviado: 'Enviada', aceptado: 'Aceptada',
      facturado: 'Facturada', descartado: 'Anulada',
    })
  })

  it('cada estado tiene su tono y las abiertas son las tres del medio del circuito', () => {
    expect(Object.keys(TONO_DE_ESTADO).sort()).toEqual(Object.keys(NOMBRE_DE_ESTADO).sort())
    expect(ESTADOS_ABIERTOS).toEqual(['pendiente', 'enviado', 'aceptado'])
  })
})

describe('tipoDe', () => {
  it('traduce el código de ARCA con que guarda el tipo el motor', () => {
    expect(TIPO_DE_CODIGO).toMatchObject({ 1: 'factura_a', 6: 'factura_b', 11: 'factura_c', 201: 'fce_a' })
    expect(tipoDe({ tipo_comprobante: 6 } as never)).toBe('factura_b')
    expect(tipoDe({ tipo_comprobante: null } as never)).toBeNull()
    expect(tipoDe({ tipo_comprobante: 999 } as never)).toBeNull()
  })
})

describe('preFacturas', () => {
  beforeEach(() => { get.mockReset(); post.mockReset(); put.mockReset() })

  it('listar manda sólo los filtros que tienen valor', async () => {
    get.mockResolvedValue({ items: [], counts: {} })
    await preFacturas.listar({ estado: 'aceptado', cliente: '' })
    expect(get).toHaveBeenCalledWith('/api/pre-facturas?estado=aceptado')
    await preFacturas.listar()
    expect(get).toHaveBeenLastCalledWith('/api/pre-facturas')
  })

  it('crear y editar van a los caminos de siempre, sin punto de venta ni número', async () => {
    const datos = { tipo: 'factura_a', fecha: '2026-08-20', orden_ids: [1, 2] }
    await preFacturas.crear({ ...datos, cliente_id: 1 })
    expect(post).toHaveBeenCalledWith('/api/pre-facturas', { ...datos, cliente_id: 1 })
    await preFacturas.editar(7, datos)
    expect(put).toHaveBeenCalledWith('/api/pre-facturas/7', datos)
  })

  it('aceptar, anular, enviar y facturar', async () => {
    await preFacturas.aceptar(7)
    expect(post).toHaveBeenLastCalledWith('/api/pre-facturas/7/aceptar', {})
    await preFacturas.anular(7, 'se equivocó el pedido')
    expect(post).toHaveBeenLastCalledWith('/api/pre-facturas/7/anular', { motivo: 'se equivocó el pedido' })
    await preFacturas.enviarPorCorreo(7, 'compras@agronorte.test')
    expect(post).toHaveBeenLastCalledWith('/api/pre-facturas/7/enviar-email', { email: 'compras@agronorte.test' })
    await preFacturas.facturar(7)
    expect(post).toHaveBeenLastCalledWith('/api/pre-facturas/7/facturar', {})
    await preFacturas.facturar(7, '2026-08-30')
    expect(post).toHaveBeenLastCalledWith('/api/pre-facturas/7/facturar', { fecha: '2026-08-30' })
  })

  it('el PDF se pide por un enlace común', () => {
    expect(preFacturas.urlDelPdf(7)).toBe('/api/pre-facturas/7/pdf')
  })
})
