/** Los botones de acción de una pantalla con pestañas, en la línea de su título, arriba a la derecha.
 *
 *  Pedido del dueño: en Transporte (antes Entidades) el «Nuevo» y en Comprobantes los de «Pre facturas» y «Facturar pendientes»
 *  quedaban debajo de las pestañas; en las demás pantallas (Órdenes, Caja, Cartas de porte) están a la altura del título.
 *
 *  El problema es que el botón es de la pestaña (cada una tiene su alta, su acceso) y el título es de la pantalla que
 *  las contiene. `TituloPantalla` del kit no tiene lugar para acciones, así que la pantalla arma la línea con
 *  `PantallaConTitulo`, que deja un hueco a la derecha del título, y la pestaña pone sus botones ahí con
 *  `AccionesDelTitulo` (un portal). Sólo la pestaña activa está montada, así que en el hueco hay sólo los botones de
 *  la que se ve.
 *
 *  Sin `PantallaConTitulo` alrededor —el componente solo, en un test o en otra pantalla— `AccionesDelTitulo` dibuja los
 *  botones en su propia fila, a la derecha, como antes.
 */
import { createContext, useContext, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** `undefined`: no hay título que aloje acciones. `null`: lo hay, pero el hueco todavía no está montado. */
const Hueco = createContext<HTMLElement | null | undefined>(undefined)

/** El título de la pantalla con el hueco de las acciones a la derecha, y debajo lo que la pantalla contenga. */
export function PantallaConTitulo({ titulo, children }: {
  /** El `<TituloPantalla icono=…>` de la pantalla, tal cual: se sigue escribiendo en su fuente, que es donde los guards
   *  (el ícono del título es el del menú) lo buscan. */
  titulo: ReactNode
  children: ReactNode
}) {
  const [hueco, setHueco] = useState<HTMLElement | null>(null)
  return (
    <Hueco.Provider value={hueco}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {titulo}
        <div ref={setHueco} className="no-imprimir flex flex-wrap items-center justify-end gap-2" />
      </div>
      {children}
    </Hueco.Provider>
  )
}

export function AccionesDelTitulo({ children }: { children: ReactNode }) {
  const hueco = useContext(Hueco)
  if (hueco === undefined) {
    return <div className="no-imprimir mb-4 flex flex-wrap items-center justify-end gap-2">{children}</div>
  }
  // El hueco se monta en el mismo commit que la pestaña; hasta que el estado lo publica no hay dónde poner nada.
  return hueco ? createPortal(children, hueco) : null
}
