/** Pre liquidación de transportistas: qué se le va a liquidar a cada fletero por sus fletes.
 *
 * Es un reporte del catálogo (`pre-liquidacion-transportistas`) pero **no usa la grilla genérica**
 * de `Reporte.tsx`: viene en bloques por transportista, cada uno con su condición de IVA y su
 * subtotal, y un total general al final. El estilo es el mismo —título, filtros, botones de arriba
 * a la derecha— y el reporte sigue figurando en el catálogo y en el índice.
 *
 * 🔑 **El rango es obligatorio**, como el de los otros listados: sin `desde` y `hasta` no se pide
 * nada y no hay botones. La guarda de verdad está en el backend (422); acá se sabe que falta un
 * filtro, no que algo salió mal.
 *
 * 🔑 **Es un papel para mandarle al transportista**, así que además de imprimir —como los otros
 * reportes— tiene su **PDF** (con el encabezado de la empresa), que arma el servidor. Ninguno de los
 * dos es un comprobante, y los dos lo dicen.
 */
import { ArrowLeft, Download, ExternalLink, Printer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'

import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import type { BloqueDeTransportista, FleteDePreLiquidacion, PreLiquidacion,
  ValoresDeFiltro } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { formatearFecha, formatearFechaHora, formatearImporte } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ICONOS_LC } from '@/iconos'

const TITULO = 'Pre liquidación de transportistas'
const LEYENDA = 'Pre liquidación — no es un comprobante'

/** `10.000` -> `10`, `12.500` -> `12,5`: la cantidad sale con tres decimales de la base. */
function formatearCantidad(f: FleteDePreLiquidacion): string {
  if (f.cantidad != null) {
    const texto = f.cantidad.includes('.') ? f.cantidad.replace(/\.?0+$/, '') : f.cantidad
    return [texto.replace('.', ','), f.unidad].filter(Boolean).join(' ')
  }
  return f.cantidad_legado ?? ''
}

function datosDelTransportista(b: BloqueDeTransportista): string {
  return [b.cuit ? `CUIT ${b.cuit}` : 'Sin CUIT',
          `${b.condicion_iva_texto} (${b.discrimina_iva ? 'suma IVA' : 'sin IVA'})`].join(' · ')
}

function Celda({ children, derecha, fuerte }: {
  children: React.ReactNode; derecha?: boolean; fuerte?: boolean
}) {
  return (
    <td className={`px-2 py-1.5 ${derecha ? 'text-right tabular-nums' : ''} ${fuerte ? 'font-semibold' : ''}`}>
      {children}
    </td>
  )
}

function Bloque({ b }: { b: BloqueDeTransportista }) {
  return (
    <section className="rounded border" aria-label={b.transportista}>
      <header className="bg-muted/40 border-b px-3 py-2">
        <h2 className="font-semibold">{b.transportista}</h2>
        <p className="text-muted-foreground text-xs">{datosDelTransportista(b)}</p>
        {b.aviso && (
          <p role="note" className="mt-1 text-xs text-amber-700 dark:text-amber-400">{b.aviso}</p>
        )}
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b text-left text-xs">
              <th className="px-2 py-1.5 font-normal">Fecha</th>
              <th className="px-2 py-1.5 font-normal">Orden</th>
              <th className="px-2 py-1.5 font-normal">Remito</th>
              <th className="px-2 py-1.5 font-normal">Cliente</th>
              <th className="px-2 py-1.5 font-normal">Origen → Destino</th>
              <th className="px-2 py-1.5 text-right font-normal">Cantidad</th>
              <th className="px-2 py-1.5 text-right font-normal">Comisión</th>
              <th className="px-2 py-1.5 text-right font-normal">IVA</th>
              <th className="px-2 py-1.5 text-right font-normal">Total</th>
            </tr>
          </thead>
          <tbody>
            {b.fletes.map((f) => (
              <tr key={f.orden_id} className="border-b last:border-b-0">
                <Celda>{formatearFecha(f.fecha)}</Celda>
                <Celda>{f.orden_id}</Celda>
                <Celda>{f.remito ?? ''}</Celda>
                <Celda>{f.cliente}</Celda>
                <Celda>{f.origen} → {f.destino}</Celda>
                <Celda derecha>{formatearCantidad(f)}</Celda>
                <Celda derecha>{formatearImporte(f.neto)}</Celda>
                <Celda derecha>{formatearImporte(f.iva)}</Celda>
                <Celda derecha>{formatearImporte(f.total)}</Celda>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 font-semibold">
              <td colSpan={6} className="px-2 py-1.5">
                Subtotal · {b.cantidad_fletes} flete{b.cantidad_fletes === 1 ? '' : 's'}
              </td>
              <Celda derecha fuerte>{formatearImporte(b.neto)}</Celda>
              <Celda derecha fuerte>{formatearImporte(b.iva)}</Celda>
              <Celda derecha fuerte>{formatearImporte(b.total)}</Celda>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  )
}

function TotalGeneral({ datos }: { datos: PreLiquidacion }) {
  return (
    <section aria-label="Total general" className="bg-muted/40 ml-auto w-full max-w-sm rounded border p-4">
      <h2 className="text-sm font-semibold">
        Total general · {datos.fletes} flete{datos.fletes === 1 ? '' : 's'}
      </h2>
      <dl className="mt-2 grid grid-cols-2 gap-y-1 text-sm tabular-nums">
        <dt>Comisión (neto)</dt><dd className="text-right">{formatearImporte(datos.neto)}</dd>
        <dt>IVA</dt><dd className="text-right">{formatearImporte(datos.iva)}</dd>
        <dt className="font-semibold">Total a liquidar</dt>
        <dd className="text-right text-base font-semibold">{formatearImporte(datos.total)}</dd>
      </dl>
    </section>
  )
}

/** La hoja de impresión del navegador: el mismo mecanismo que `HojaImpresa` —un portal fuera de
 *  `#root` que el CSS de impresión deja como única cosa visible—, pero en bloques. */
function HojaPreLiquidacion({ datos }: { datos: PreLiquidacion }) {
  return (
    <div id="hoja-impresa" className="hoja-impresa">
      <header>
        <h1>{TITULO}</h1>
        <p>
          LibraCargo · emitido el {formatearFechaHora(new Date())} · {datos.fletes} flete
          {datos.fletes === 1 ? '' : 's'}
        </p>
        <p>Período: {formatearFecha(datos.desde)} al {formatearFecha(datos.hasta)}</p>
        <p className="aviso">{LEYENDA}</p>
      </header>
      {datos.transportistas.map((b) => (
        <div key={b.tercero_id}>
          <h2>{b.transportista}</h2>
          <p className="de-bloque">
            {datosDelTransportista(b)}{b.aviso ? ` · ${b.aviso}` : ''}
          </p>
          <table>
            <thead>
              <tr>
                <th>Fecha</th><th>Orden</th><th>Remito</th><th>Cliente</th>
                <th>Origen → Destino</th>
                <th className="derecha">Cantidad</th><th className="derecha">Comisión</th>
                <th className="derecha">IVA</th><th className="derecha">Total</th>
              </tr>
            </thead>
            <tbody>
              {b.fletes.map((f) => (
                <tr key={f.orden_id}>
                  <td>{formatearFecha(f.fecha)}</td><td>{f.orden_id}</td><td>{f.remito ?? ''}</td>
                  <td>{f.cliente}</td><td>{f.origen} → {f.destino}</td>
                  <td className="derecha">{formatearCantidad(f)}</td>
                  <td className="derecha">{formatearImporte(f.neto)}</td>
                  <td className="derecha">{formatearImporte(f.iva)}</td>
                  <td className="derecha">{formatearImporte(f.total)}</td>
                </tr>
              ))}
              <tr className="subtotal">
                <td colSpan={6}>
                  Subtotal · {b.cantidad_fletes} flete{b.cantidad_fletes === 1 ? '' : 's'}
                </td>
                <td className="derecha">{formatearImporte(b.neto)}</td>
                <td className="derecha">{formatearImporte(b.iva)}</td>
                <td className="derecha">{formatearImporte(b.total)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      ))}
      <footer>
        <p><strong>Total general:</strong> {datos.fletes} flete{datos.fletes === 1 ? '' : 's'}</p>
        <p><strong>Comisión (neto):</strong> {formatearImporte(datos.neto)}</p>
        <p><strong>IVA:</strong> {formatearImporte(datos.iva)}</p>
        <p><strong>Total a liquidar:</strong> {formatearImporte(datos.total)}</p>
        <p>{LEYENDA}</p>
      </footer>
    </div>
  )
}

export default function PreLiquidacionTransportistas() {
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [valores, setValores] = useState<ValoresDeFiltro>({})
  const [datos, setDatos] = useState<PreLiquidacion | null>(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [imprimiendo, setImprimiendo] = useState(false)

  const desde = String(valores.desde ?? '')
  const hasta = String(valores.hasta ?? '')
  const hayRango = desde !== '' && hasta !== ''
  const alReves = hayRango && desde > hasta
  const puedeCorrer = hayRango && !alReves

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  useEffect(() => {
    // Sin rango —o al revés— no se pide: acá se sabe que falta un filtro, no que algo salió mal.
    if (!puedeCorrer) { setDatos(null); setCargando(false); return }
    let vigente = true
    setCargando(true)
    setError(null)
    // `datos` y `cargando` se actualizan juntos: una pantalla con los datos nuevos y el "Calculando"
    // viejo (o al revés) es un parpadeo que no corresponde a ningún estado.
    reportes.preLiquidacion(valores)
      .then((d) => { if (vigente) { setDatos(d); setCargando(false) } })
      .catch((e) => {
        if (vigente) { setDatos(null); setError(mensajeDeError(e)); setCargando(false) }
      })
    return () => { vigente = false }
  }, [puedeCorrer, valores])

  const set = (c: ValoresDeFiltro) => setValores((v) => ({ ...v, ...c }))

  function imprimir() {
    setImprimiendo(true)
    // Se espera un frame para que la hoja esté en el DOM antes de abrir el diálogo del navegador:
    // `window.print()` fotografía lo que hay (ver `BotonImprimir`).
    requestAnimationFrame(() => requestAnimationFrame(() => {
      window.print()
      setImprimiendo(false)
    }))
  }

  const hayFletes = datos !== null && datos.transportistas.length > 0
  const urlDelPdf = reportes.urlDelPdfPreLiquidacion(valores)

  return (
    <div>
      <Link to="/reportes"
            className="text-muted-foreground no-imprimir mb-2 inline-flex items-center gap-1 text-sm hover:underline">
        <ArrowLeft className="size-3" /> Todos los reportes
      </Link>

      <div className="mb-4">
        {/* Sin rango no hay hoja que imprimir: los botones no están, en vez de estar y fallar. */}
        <TituloPantalla
          icono={ICONOS_LC.reportes}
          acciones={hayFletes && (
            <div className="no-imprimir flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={imprimir} disabled={imprimiendo}>
                <Printer className="size-4" /> Imprimir
              </Button>
              <Button variant="outline" asChild>
                <a href={urlDelPdf} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-4" /> Ver PDF
                </a>
              </Button>
              <Button variant="outline" asChild>
                <a href={urlDelPdf}
                   download={`pre-liquidacion-transportistas-${desde}-${hasta}.pdf`}>
                  <Download className="size-4" /> Descargar PDF
                </a>
              </Button>
            </div>
          )}
        >
          {TITULO}
        </TituloPantalla>
        <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
          Los fletes que hizo cada transportista en el período, con la comisión de cada uno, el
          IVA si es responsable inscripto y los subtotales. Es para mandarle antes de que
          facture. <strong>{LEYENDA}.</strong>
        </p>
      </div>

      <div className="no-imprimir mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="grid gap-1">
          <Label htmlFor="f-desde">Desde</Label>
          <Input id="f-desde" type="date" value={desde}
                 onChange={(e) => set({ desde: e.target.value })} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="f-hasta">Hasta</Label>
          <Input id="f-hasta" type="date" value={hasta}
                 onChange={(e) => set({ hasta: e.target.value })} />
        </div>
        <Elegir id="f-fletero" etiqueta="Transportista" vacio="Todos"
                valor={String(valores.fletero_id ?? '')} opciones={opciones?.fleteros ?? []}
                alCambiar={(v) => set({ fletero_id: v })} />
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {!hayRango ? (
        <p className="text-muted-foreground rounded border border-dashed p-8 text-center text-sm">
          Elegí un <strong>desde</strong> y un <strong>hasta</strong>. La pre liquidación es de un
          período: sin fechas no hay qué liquidar.
        </p>
      ) : alReves ? (
        <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">
          El rango está al revés: el desde es posterior al hasta.
        </p>
      ) : cargando && datos === null ? (
        <p className="text-muted-foreground p-8 text-center text-sm">Calculando…</p>
      ) : datos !== null && !hayFletes ? (
        <p className="text-muted-foreground rounded border border-dashed p-8 text-center text-sm">
          No hay fletes con comisión en ese período{valores.fletero_id ? ' para ese transportista' : ''}.
        </p>
      ) : datos !== null ? (
        <div className="grid gap-4">
          {datos.transportistas.map((b) => <Bloque key={b.tercero_id} b={b} />)}
          <TotalGeneral datos={datos} />
        </div>
      ) : null}

      {imprimiendo && datos && createPortal(<HojaPreLiquidacion datos={datos} />, document.body)}
    </div>
  )
}
