/** La orden de carga en papel: la que viaja con el camión.
 *
 * No es un listado, así que no usa `HojaImpresa` —esa arma una tabla— pero sí el
 * mismo mecanismo: se monta en un portal fuera de `#root` y el CSS de impresión
 * esconde todo lo demás.
 *
 * 🔑 **El encabezado sale de la configuración de la empresa**, no de una
 * constante: es lo que hace que el papel de Suitrans diga Suitrans. Si todavía
 * no se cargó, el papel sale sin membrete y **igual sirve** — lo que no puede
 * pasar es que no se pueda imprimir porque falta un dato de configuración.
 */
import { createPortal } from 'react-dom'

import type { Configuracion } from '@/api/configuracion'
import { urlDelLogo } from '@/api/configuracion'
import type { Opciones, Orden } from '@/api/ordenes'
import { formatearFechaHora, formatearImporte } from '@/components/esquema-orden'

function nombre(lista: { id: number; etiqueta: string }[] | undefined, id: number | null) {
  return lista?.find((o) => o.id === id)?.etiqueta ?? ''
}

function Dato({ etiqueta, valor, ancho }: { etiqueta: string; valor: string; ancho?: boolean }) {
  return (
    <div className={ancho ? 'dato ancho' : 'dato'}>
      <span className="etiqueta">{etiqueta}</span>
      <span className="valor">{valor || '—'}</span>
    </div>
  )
}

export function OrdenImpresa({ orden, opciones, empresa }: {
  orden: Orden
  opciones: Opciones | null
  empresa: Configuracion
}) {
  const domicilio = [empresa.domicilio, empresa.localidad, empresa.provincia]
    .filter(Boolean).join(', ')
  const fiscal = [empresa.cuit && `CUIT ${empresa.cuit}`, empresa.condicion_iva,
                  empresa.ingresos_brutos && `IIBB ${empresa.ingresos_brutos}`]
    .filter(Boolean).join(' · ')

  return createPortal(
    <div id="hoja-impresa" className="hoja-impresa hoja-orden">
      <header className="membrete">
        {empresa.tiene_logo && (
          <img src={urlDelLogo()} alt="" className="logo" />
        )}
        <div className="quien">
          <p className="empresa">{empresa.nombre_fantasia || empresa.razon_social}</p>
          {domicilio && <p>{domicilio}</p>}
          {fiscal && <p>{fiscal}</p>}
          {(empresa.telefono || empresa.email) && (
            <p>{[empresa.telefono, empresa.email].filter(Boolean).join(' · ')}</p>
          )}
        </div>
        <div className="titulo">
          <p className="que">ORDEN DE CARGA</p>
          <p className="numero">Nº {String(orden.id).padStart(8, '0')}</p>
          <p className="fecha">{orden.fecha}</p>
        </div>
      </header>

      <section className="bloque">
        <Dato etiqueta="Cliente" valor={nombre(opciones?.clientes, orden.cliente_id)} ancho />
        <Dato etiqueta="Remito" valor={orden.remito ?? ''} />
        <Dato etiqueta="Origen" valor={nombre(opciones?.localidades, orden.origen_id)} />
        <Dato etiqueta="Destino" valor={nombre(opciones?.localidades, orden.destino_id)} />
        <Dato etiqueta="Tipo de carga" valor={nombre(opciones?.tipos, orden.tipo_carga_id)} />
        <Dato etiqueta="Cantidad"
              valor={[orden.cantidad, orden.unidad].filter(Boolean).join(' ')
                     || orden.cantidad_legado || ''} />
      </section>

      <section className="bloque">
        <Dato etiqueta="Fletero" valor={nombre(opciones?.fleteros, orden.fletero_id)} ancho />
        <Dato etiqueta="Chofer" valor={nombre(opciones?.choferes, orden.chofer_id)} />
        <Dato etiqueta="Vehículo" valor={nombre(opciones?.vehiculos, orden.vehiculo_id)} />
      </section>

      <table className="importes">
        <tbody>
          <tr><th>Tarifa</th><td>{formatearImporte(orden.tarifa)}</td></tr>
          <tr><th>IVA ({orden.alicuota_iva}%)</th><td>{formatearImporte(orden.iva)}</td></tr>
          <tr className="total"><th>Total</th><td>{formatearImporte(orden.total)}</td></tr>
          <tr><th>Comisión</th><td>{formatearImporte(orden.comision)}</td></tr>
        </tbody>
      </table>

      {orden.observaciones && (
        <section className="observaciones">
          <span className="etiqueta">Observaciones</span>
          <p>{orden.observaciones}</p>
        </section>
      )}

      {/* Las dos firmas: el papel viaja con el camión y vuelve firmado. Sin
          ellas es una ficha impresa, no un remito. */}
      <section className="firmas">
        <div><span className="linea" />Firma y aclaración del transportista</div>
        <div><span className="linea" />Recibí conforme</div>
      </section>

      <footer className="pie">
        {empresa.pie_de_impresion && <p>{empresa.pie_de_impresion}</p>}
        <p className="chico">
          Emitido el {formatearFechaHora(new Date())} · LibraCargo
        </p>
      </footer>
    </div>,
    document.body,
  )
}
