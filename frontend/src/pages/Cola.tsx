/** «Cola de comprobantes»: las facturas y las cartas de porte que un nodo pidió sin conexión y todavía no salieron en ARCA (ADR-056 del
 *  backend; la pantalla es `BandejaDeLaCola` de libra-ui, ADR-094).
 *
 *  La entrada del menú sólo existe en un nodo (`components/Layout.tsx`); si alguien llega por la dirección desde la web, la bandeja dice
 *  que esta instalación no es un nodo. Mirar la cola y pedir «Emitir ahora» lo puede cualquier usuario; reintentar, descartar y marcar
 *  emitido deciden sobre un documento fiscal y son de un administrador (el backend lo exige igual, `resolver_con=require_admin`).
 */
import { BandejaDeLaCola } from 'libra-ui/BandejaDeLaCola'
import { useCallback, useEffect, useState } from 'react'

import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { useAuth } from '@/context/AuthContext'
import { describirPedido } from '@/lib/pedido-de-la-cola'

export default function Cola() {
  const { user } = useAuth() as { user: { role?: string } | null }
  const esAdmin = user?.role === 'admin'
  // Para nombrar al cliente de cada factura. Si no carga, la tarjeta dice «cliente 7» y la cola sigue sirviendo.
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  useEffect(() => {
    let vigente = true
    cargarOpciones().then((o) => { if (vigente) setOpciones(o) }).catch(() => { /* es un detalle de la tarjeta */ })
    return () => { vigente = false }
  }, [])

  const describir = useCallback(
    (p: Parameters<typeof describirPedido>[0]) =>
      describirPedido(p, (id) => opciones?.clientes.find((c) => c.id === id)?.etiqueta),
    [opciones],
  )

  return <BandejaDeLaCola puedeResolver={esAdmin} describir={describir} />
}
