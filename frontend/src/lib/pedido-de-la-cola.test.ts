import type { PedidoDeCola } from 'libra-ui/cola-del-nodo'
import { describe, expect, it } from 'vitest'

import { describirPedido, esPedidoDeLaOrden } from './pedido-de-la-cola'

const pedido = (extra: Partial<PedidoDeCola>): PedidoDeCola => ({
  id: 1, origen_producto: 'libracargo', origen_instancia: 'oficina', origen_tipo: 'cpe', origen_id: 'orden41:3f1c9a',
  estado: 'esperando', datos: {}, fecha_ref: '', concepto: 1, intentos: 0, ultimo_error: '', resultado: null, revision: 1,
  created_at: '', updated_at: '', resuelto_at: '', ...extra,
})

describe('esPedidoDeLaOrden', () => {
  it('🔑 compara `datos.orden_id` y no el `origen_id`, que es `orden<id>:<uuid>`', () => {
    const p = pedido({ origen_id: 'orden41:3f1c9a', datos: { orden_id: 41 } })
    expect(esPedidoDeLaOrden(41)(p)).toBe(true)
    expect(esPedidoDeLaOrden(4)(p)).toBe(false)
    expect(esPedidoDeLaOrden(99)(p)).toBe(false)
    // El `origen_id` de otra orden con el mismo prefijo no engaña.
    expect(esPedidoDeLaOrden(41)(pedido({ origen_id: 'orden41:aa', datos: { orden_id: 410 } }))).toBe(false)
  })

  it('una orden provisoria (id negativo) también se reconoce', () => {
    expect(esPedidoDeLaOrden(-3)(pedido({ origen_id: 'orden-3:aa', datos: { orden_id: -3 } }))).toBe(true)
  })

  it('un pedido sin `orden_id` (una factura) no es de ninguna orden', () => {
    expect(esPedidoDeLaOrden(41)(pedido({ origen_tipo: 'documento', datos: { orden_ids: [41] } }))).toBe(false)
  })
})

describe('describirPedido', () => {
  const cliente = (id: number) => (id === 1 ? 'Agro Norte' : undefined)

  it('una carta de porte dice de qué orden es', () => {
    expect(describirPedido(pedido({ datos: { orden_id: 41 } }), cliente)).toBe('Carta de porte · Orden 41')
    expect(describirPedido(pedido({ datos: { orden_id: -3 } }), cliente)).toBe('Carta de porte · Orden P-3')
    expect(describirPedido(pedido({ datos: {} }), cliente)).toBe('Carta de porte')
  })

  it('una factura dice el cliente y qué factura', () => {
    const f = (datos: Record<string, unknown>) => pedido({ origen_tipo: 'documento', origen_id: 'ordenes:aa', datos })
    expect(describirPedido(f({ clase: 'ordenes', cliente_id: 1, orden_ids: [41, 42, 43] }), cliente)).toBe('Factura · Agro Norte · 3 órdenes')
    expect(describirPedido(f({ clase: 'ordenes', cliente_id: 1, orden_ids: [41] }), cliente)).toBe('Factura · Agro Norte · la orden 41')
    expect(describirPedido(f({ clase: 'directa', cliente_id: 1, conceptos: [] }), cliente)).toBe('Factura · Agro Norte · conceptos libres')
  })

  it('sin el nombre del cliente (no cargó o ya no está) dice el número, y sin cliente no inventa nada', () => {
    const f = (datos: Record<string, unknown>) => pedido({ origen_tipo: 'documento', datos })
    expect(describirPedido(f({ clase: 'ordenes', cliente_id: 7, orden_ids: [1, 2] }), cliente)).toBe('Factura · cliente 7 · 2 órdenes')
    expect(describirPedido(f({}), cliente)).toBe('Factura')
  })
})
