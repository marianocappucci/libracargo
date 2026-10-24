/** Cómo se lee un pedido de la cola de comprobantes del nodo (libra-ui ADR-094; el backend es ADR-056 y `app/servicios/emisores.py`).
 *
 *  Los `datos` los arma el emisor de este producto:
 *  - una **carta de porte**: `{orden_id, solicitud, confirmo, usuario}`;
 *  - una **factura**: `{clase: "ordenes" | "directa", cliente_id, orden_ids?, conceptos?, tipo, …}`.
 *
 *  🔑 El `origen_id` NO sirve para saber de qué orden es: es `orden41:<uuid>` (único por pedido, para poder volver a pedir una CPE
 *  descartada) y el id de la orden está en `datos.orden_id`. Por eso `coincide` compara ahí y no el `origen_id` pelado.
 */
import type { PedidoDeCola } from 'libra-ui/cola-del-nodo'

import { numeroCorto } from '@/lib/numero-de-orden'

/** ¿Es el pedido de CPE de esta orden? Es lo que recibe `<AvisoSinCpeValida coincide={…}/>`. */
export const esPedidoDeLaOrden = (idDeOrden: number) => (p: PedidoDeCola): boolean => p.datos.orden_id === idDeOrden

const numeros = (valor: unknown): number[] =>
  Array.isArray(valor) ? valor.filter((n): n is number => typeof n === 'number') : []

/** La línea de una tarjeta: «Carta de porte · Orden 41», «Factura · Cereales SA · 3 órdenes», «Factura · Cereales SA · conceptos libres».
 *  `nombreDelCliente` es el de `cliente_id`; sin él (todavía no cargó, o el cliente ya no está) se dice «cliente 7». */
export function describirPedido(p: PedidoDeCola, nombreDelCliente: (id: number) => string | undefined): string {
  if (p.origen_tipo === 'cpe') {
    const orden = p.datos.orden_id
    return typeof orden === 'number' ? `Carta de porte · Orden ${numeroCorto(orden)}` : 'Carta de porte'
  }
  const cliente = typeof p.datos.cliente_id === 'number'
    ? (nombreDelCliente(p.datos.cliente_id) ?? `cliente ${p.datos.cliente_id}`) : ''
  const ordenes = numeros(p.datos.orden_ids)
  const que = p.datos.clase === 'directa' ? 'conceptos libres'
    : ordenes.length === 1 ? `la orden ${numeroCorto(ordenes[0])}`
    : ordenes.length > 1 ? `${ordenes.length} órdenes` : ''
  return ['Factura', cliente, que].filter(Boolean).join(' · ')
}
