/** Comprobantes: lo facturado, y el gate de F5 a la vista.
 *
 * El sistema **registra** el comprobante, no lo emite: el número lo tipea una
 * persona, igual que en el sistema viejo. Eso es lo que permite comparar
 * totales contra el legado durante la migración; emitir es F8.
 *
 * 🔑 **El panel de totales muestra los dos lados, no uno.** El total por razón
 * social se cuenta por los encabezados de los comprobantes y por las órdenes
 * que agrupan. Mostrar sólo uno haría que un total divergente se viera igual de
 * confiable que uno sano — que es justo cuando no hay que usarlo.
 */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { FileText, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import type { Comprobante, ComprobanteConOrdenes, TotalDeRazonSocial } from '@/api/comprobantes'
import { NOMBRE_DE_TIPO, comprobantes, numeroDe, sumarImportes } from '@/api/comprobantes'
import type { Opcion, Opciones, Orden } from '@/api/ordenes'
import { cargarOpciones, ordenes as apiOrdenes } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import type { Columna } from '@/components/impresion'
import { BotonImprimir, traerTodo } from '@/components/impresion'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Borrador = {
  fecha: string
  cliente_id: string
  razon_social_id: string
  tipo: string
  punto_venta: string
  numero: string
}

// La fecha por defecto sale de la de Argentina y no de `toISOString`: un
// comprobante cargado de noche nacía con la fecha de mañana.
const VACIO: Borrador = {
  fecha: hoyEnArgentina(), cliente_id: '', razon_social_id: '',
  tipo: 'factura_a', punto_venta: '1', numero: '',
}

function Campo({ id, etiqueta, valor, alCambiar, tipo = 'text' }: {
  id: string; etiqueta: string; valor: string
  alCambiar: (v: string) => void; tipo?: string
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <Input id={id} type={tipo} value={valor} onChange={(e) => alCambiar(e.target.value)} />
    </div>
  )
}

function Eleccion({ id, etiqueta, valor, alCambiar, children }: {
  id: string; etiqueta: string; valor: string
  alCambiar: (v: string) => void; children: React.ReactNode
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <select id={id} className="h-9 w-full min-w-0 rounded-md border px-2 text-sm" value={valor}
              onChange={(e) => alCambiar(e.target.value)}>
        {children}
      </select>
    </div>
  )
}

function nombre(opciones: Opcion[], id: number | null): string {
  return opciones.find((o) => o.id === id)?.etiqueta ?? ''
}

/** El panel del gate: cada razón social, contada por los dos lados. */
function Totales({ filas, razones }: { filas: TotalDeRazonSocial[]; razones: Opcion[] }) {
  if (filas.length === 0) return null
  const divergen = filas.filter((f) => !f.coinciden)
  return (
    <section className="mb-6 rounded border p-4">
      <h2 className="mb-3 text-sm font-semibold">Total facturado por razón social</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted-foreground text-xs">
            <tr>
              <th className="p-1 text-left">Razón social</th>
              <th className="p-1 text-right">Comprobantes</th>
              <th className="p-1 text-right">Total por comprobantes</th>
              <th className="p-1 text-right">Órdenes</th>
              <th className="p-1 text-right">Total por órdenes</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr key={String(f.razon_social_id)}
                  className={f.coinciden ? '' : 'text-destructive font-semibold'}>
                <td className="p-1">
                  {f.razon_social_id == null
                    ? 'Sin razón social'
                    : nombre(razones, f.razon_social_id) || `#${f.razon_social_id}`}
                </td>
                <td className="p-1 text-right">{f.cantidad_comprobantes}</td>
                <td className="p-1 text-right">{f.total_comprobantes}</td>
                <td className="p-1 text-right">{f.cantidad_ordenes}</td>
                <td className="p-1 text-right">{f.total_ordenes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {divergen.length > 0 && (
        <p role="alert" className="text-destructive mt-3 text-sm font-semibold">
          🔴 Hay {divergen.length} razón/es social/es donde los dos lados NO
          coinciden. No usar estos totales: hay importes que están en una razón
          social por los comprobantes y en otra por las órdenes.
        </p>
      )}
    </section>
  )
}

export default function Comprobantes() {
  const [filas, setFilas] = useState<Comprobante[]>([])
  const [totales, setTotales] = useState<TotalDeRazonSocial[]>([])
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [razonFiltro, setRazonFiltro] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [borrador, setBorrador] = useState<Borrador>(VACIO)
  const [pendientes, setPendientes] = useState<Orden[]>([])
  const [elegidas, setElegidas] = useState<number[]>([])
  const [detalle, setDetalle] = useState<ComprobanteConOrdenes | null>(null)
  const [confirmando, setConfirmando] = useState(false)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  const recargar = useCallback(() => {
    setCargando(true)
    Promise.all([
      comprobantes.listar({ desde, hasta, razon_social_id: razonFiltro }),
      comprobantes.totales(desde || undefined, hasta || undefined),
    ])
      .then(([lista, tot]) => { setFilas(lista); setTotales(tot) })
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [desde, hasta, razonFiltro])

  useEffect(recargar, [recargar])

  // Las pendientes del cliente elegido. Sin cliente no se piden: un comprobante
  // es de un solo cliente, y una lista de todos invitaria a mezclarlos.
  useEffect(() => {
    if (!borrador.cliente_id) { setPendientes([]); return }
    apiOrdenes
      .listar({ cliente_id: Number(borrador.cliente_id), facturada: false, estado: 'pendiente' })
      .then(setPendientes)
      .catch((e) => setError(mensajeDeError(e)))
  }, [borrador.cliente_id])

  const razon = borrador.razon_social_id ? Number(borrador.razon_social_id) : null
  // Una orden que ya tiene OTRA razón social no entra en este comprobante: el
  // backend la rechaza, y ofrecerla en la lista invita a mandarla. Las que no
  // tienen ninguna heredan la del comprobante.
  const visibles = pendientes.filter(
    (o) => razon != null && (o.razon_social_id == null || o.razon_social_id === razon),
  )
  // Se factura lo elegido **y visible**: si cambia la razón social, lo que dejó
  // de poder facturarse deja de contar, en la vista previa y en el envío.
  const aFacturar = visibles.filter((o) => elegidas.includes(o.id))
  const totalPrevio = sumarImportes(aFacturar.map((o) => o.total))

  const set = (c: Partial<Borrador>) => setBorrador((b) => ({ ...b, ...c }))

  async function facturar() {
    setError(null)
    try {
      await comprobantes.facturar({
        fecha: borrador.fecha,
        cliente_id: Number(borrador.cliente_id),
        razon_social_id: Number(borrador.razon_social_id),
        tipo: borrador.tipo,
        punto_venta: Number(borrador.punto_venta),
        numero: Number(borrador.numero),
        orden_ids: aFacturar.map((o) => o.id),
      })
      setAbierto(false)
      setBorrador(VACIO)
      setElegidas([])
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function ver(id: number) {
    setError(null)
    setConfirmando(false)
    try {
      setDetalle(await comprobantes.ver(id))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function anular(id: number) {
    setError(null)
    try {
      await comprobantes.anular(id)
      setDetalle(null)
      setConfirmando(false)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  const COLUMNAS_IMPRESAS: Columna<Comprobante>[] = [
    { encabezado: 'Fecha', valor: (c) => c.fecha },
    { encabezado: 'Comprobante', valor: (c) => `${NOMBRE_DE_TIPO[c.tipo]} ${numeroDe(c)}` },
    { encabezado: 'Cliente',
      valor: (c) => nombre(opciones?.clientes ?? [], c.cliente_id) },
    { encabezado: 'Estado', valor: (c) => (c.anulado ? 'anulado' : 'vigente') },
    { encabezado: 'Neto', valor: (c) => c.neto, numerica: true, moneda: true },
    { encabezado: 'IVA', valor: (c) => c.iva, numerica: true, moneda: true },
    { encabezado: 'Total', valor: (c) => c.total, numerica: true, moneda: true },
  ]

  const columnas = [
    { accessorKey: 'fecha', header: sortableHeader('Fecha') },
    { id: 'comprobante', header: 'Comprobante',
      accessorFn: (c: Comprobante) => `${NOMBRE_DE_TIPO[c.tipo]} ${numeroDe(c)}` },
    { id: 'razon', header: 'Razón social',
      accessorFn: (c: Comprobante) => nombre(opciones?.razones ?? [], c.razon_social_id) },
    { id: 'cliente', header: 'Cliente',
      accessorFn: (c: Comprobante) => nombre(opciones?.clientes ?? [], c.cliente_id) },
    { id: 'neto', header: 'Neto',
      accessorFn: (c: Comprobante) => formatearImporte(c.neto) },
    { id: 'iva', header: 'IVA',
      accessorFn: (c: Comprobante) => formatearImporte(c.iva) },
    { id: 'total', header: sortableHeader('Total'),
      accessorFn: (c: Comprobante) => formatearImporte(c.total) },
    { id: 'estado', header: 'Estado',
      accessorFn: (c: Comprobante) => (c.anulado ? 'anulado' : 'vigente'),
      cell: ({ row }: { row: { original: Comprobante } }) => (
        <Badge variant={row.original.anulado ? 'destructive' : 'secondary'}>
          {row.original.anulado ? 'anulado' : 'vigente'}
        </Badge>
      ) },
    { id: 'acciones', header: '',
      cell: ({ row }: { row: { original: Comprobante } }) => (
        <Button variant="ghost" size="sm" onClick={() => ver(row.original.id)}>
          <FileText className="size-4" /> Ver
        </Button>
      ) },
  ]

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Comprobantes</h1>
        <div className="flex gap-2">
          <BotonImprimir
            titulo="Comprobantes"
            filtros={[desde && `desde ${desde}`, hasta && `hasta ${hasta}`,
                      razonFiltro && 'una razón social'].filter(Boolean).join(' · ')
                     || 'sin filtros'}
            columnas={COLUMNAS_IMPRESAS}
            traer={() => traerTodo(async (desplazamiento, limite) =>
              comprobantes.listar({ desde, hasta, razon_social_id: razonFiltro,
                                    desplazamiento, limite }))}
            totales={(f) => [
              { etiqueta: 'Comprobantes', valor: String(f.length) },
              { etiqueta: 'Total', valor: sumarImportes(f.map((c) => c.total)) },
            ]}
          />
          <Button onClick={() => { setBorrador(VACIO); setElegidas([]); setError(null); setAbierto(true) }}>
            <Plus className="size-4" /> Facturar pendientes
          </Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Campo id="f-desde" etiqueta="Desde" tipo="date" valor={desde} alCambiar={setDesde} />
        <Campo id="f-hasta" etiqueta="Hasta" tipo="date" valor={hasta} alCambiar={setHasta} />
        <Eleccion id="f-razon" etiqueta="Razón social" valor={razonFiltro} alCambiar={setRazonFiltro}>
          <option value="">Todas</option>
          {(opciones?.razones ?? []).map((r) => (
            <option key={r.id} value={r.id}>{r.etiqueta}</option>
          ))}
        </Eleccion>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <Totales filas={totales} razones={opciones?.razones ?? []} />

      <DataTable
        columns={columnas}
        data={filas}
        emptyMessage={cargando ? 'Cargando…' : 'No hay comprobantes en ese rango.'}
      />

      <Dialog open={abierto} onOpenChange={setAbierto}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>Facturar pendientes</DialogTitle></DialogHeader>
          <div className="grid gap-3 md:grid-cols-2">
            <Campo id="n-fecha" etiqueta="Fecha" tipo="date" valor={borrador.fecha}
                   alCambiar={(v) => set({ fecha: v })} />
            <Elegir id="n-cliente" etiqueta="Cliente" vacio="Elegir…"
                    valor={borrador.cliente_id} opciones={opciones?.clientes ?? []}
                    alCambiar={(v) => { set({ cliente_id: v }); setElegidas([]) }} />
            <Eleccion id="n-razon" etiqueta="Razón social" valor={borrador.razon_social_id}
                      alCambiar={(v) => set({ razon_social_id: v })}>
              <option value="">Elegir…</option>
              {(opciones?.razones ?? []).map((r) => (
                <option key={r.id} value={r.id}>{r.etiqueta}</option>
              ))}
            </Eleccion>
            <Eleccion id="n-tipo" etiqueta="Tipo" valor={borrador.tipo}
                      alCambiar={(v) => set({ tipo: v })}>
              <option value="factura_a">Factura A</option>
              <option value="factura_b">Factura B</option>
              <option value="factura_c">Factura C</option>
            </Eleccion>
            <Campo id="n-pv" etiqueta="Punto de venta" valor={borrador.punto_venta}
                   alCambiar={(v) => set({ punto_venta: v })} />
            <Campo id="n-numero" etiqueta="Número" valor={borrador.numero}
                   alCambiar={(v) => set({ numero: v })} />
          </div>

          <div className="mt-4">
            <h3 className="mb-2 text-sm font-semibold">Órdenes pendientes</h3>
            {!borrador.cliente_id || !borrador.razon_social_id ? (
              <p className="text-muted-foreground text-sm">
                Elegí el cliente y la razón social para ver qué se puede facturar.
              </p>
            ) : visibles.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                Este cliente no tiene órdenes pendientes para esa razón social.
              </p>
            ) : (
              <ul className="divide-y rounded border">
                {visibles.map((o) => (
                  <li key={o.id} className="flex items-center gap-3 p-2 text-sm">
                    <input type="checkbox" id={`o-${o.id}`}
                           checked={elegidas.includes(o.id)}
                           onChange={(e) => setElegidas((previas) => (
                             e.target.checked
                               ? [...previas, o.id]
                               : previas.filter((i) => i !== o.id)
                           ))} />
                    <label htmlFor={`o-${o.id}`} className="flex-1">
                      #{o.id} · {o.fecha} · remito {o.remito || 's/n'}
                    </label>
                    <span className="tabular-nums">{o.total}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-3 flex items-center justify-between rounded border p-3">
            <span className="text-sm">
              {aFacturar.length} orden/es elegida/s
            </span>
            {/* Vista previa: el importe que queda guardado lo calcula el
                servidor sobre las mismas ordenes. La suma de aca va en
                centavos enteros, no en punto flotante. */}
            <span className="text-lg font-semibold">
              Total: {formatearImporte(totalPrevio)}
            </span>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setAbierto(false)}>Cancelar</Button>
            <Button onClick={facturar} disabled={aFacturar.length === 0 || !borrador.numero}>
              Facturar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={detalle != null} onOpenChange={(v) => { if (!v) setDetalle(null) }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {detalle && `${NOMBRE_DE_TIPO[detalle.comprobante.tipo]} ${numeroDe(detalle.comprobante)}`}
            </DialogTitle>
          </DialogHeader>
          {detalle && (
            <div className="grid gap-3 text-sm">
              <div className="flex flex-wrap gap-6">
                <div>
                  <p className="text-muted-foreground text-xs">Total del comprobante</p>
                  <p className="text-lg font-semibold">
                    {formatearImporte(detalle.comprobante.total)}
                  </p>
                </div>
                {/* Los dos numeros a la vista, igual que en la cuenta
                    corriente: el encabezado y lo que suman sus ordenes. */}
                <div>
                  <p className="text-muted-foreground text-xs">
                    Suma de sus {detalle.suma_de_ordenes.cantidad} orden/es
                  </p>
                  <p className="text-lg font-semibold">
                    {formatearImporte(detalle.suma_de_ordenes.total)}
                  </p>
                </div>
              </div>
              {!detalle.coinciden && (
                <p role="alert" className="text-destructive text-sm font-semibold">
                  🔴 El comprobante no dice lo mismo que sus órdenes. No usarlo
                  hasta saber cuál de los dos importes es el bueno.
                </p>
              )}
              <ul className="divide-y rounded border">
                {detalle.ordenes.map((o) => (
                  <li key={o.id} className="flex items-center gap-3 p-2">
                    <span className="flex-1">#{o.id} · {o.fecha} · remito {o.remito || 's/n'}</span>
                    <span className="tabular-nums">{o.total}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <DialogFooter>
            {detalle && !detalle.comprobante.anulado && (
              confirmando ? (
                <>
                  <span className="mr-auto self-center text-sm">
                    Las órdenes vuelven a pendientes y la cuenta se revierte.
                  </span>
                  <Button variant="ghost" onClick={() => setConfirmando(false)}>No</Button>
                  <Button variant="destructive"
                          onClick={() => anular(detalle.comprobante.id)}>
                    Confirmar anulación
                  </Button>
                </>
              ) : (
                // Dos pasos a proposito: anular mueve la cuenta corriente del
                // cliente, y es la clase de boton que no se aprieta sin querer.
                <Button variant="destructive" onClick={() => setConfirmando(true)}>
                  Anular comprobante
                </Button>
              )
            )}
            <Button variant="ghost" onClick={() => setDetalle(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
