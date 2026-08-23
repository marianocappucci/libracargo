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
import { FileText, Plus, Receipt } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import type { Comprobante, ComprobanteConOrdenes, TotalDeRazonSocial } from '@/api/comprobantes'
import { NOMBRE_DE_TIPO, comprobantes, numeroDe } from '@/api/comprobantes'
import type { Opcion, Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { formatearImporte } from '@/components/esquema-orden'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { irA } from '@/navegacion'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { formatearFecha } from '@/components/esquema-orden'

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
  const [detalle, setDetalle] = useState<ComprobanteConOrdenes | null>(null)
  const [params, setParams] = useSearchParams()
  const [confirmando, setConfirmando] = useState(false)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // `/comprobantes?ver=123` abre ese comprobante. Es a donde lleva un asiento
  // de cuenta corriente que salio de una factura.
  const idAVer = params.get('ver')
  useEffect(() => {
    if (!idAVer) return
    let vigente = true
    comprobantes.ver(Number(idAVer))
      .then((c) => { if (vigente) setDetalle(c) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [idAVer])

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
        <BadgeEstado tono={row.original.anulado ? 'negativo' : 'ok'}>
          {row.original.anulado ? 'anulado' : 'vigente'}
        </BadgeEstado>
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
        <TituloPantalla icono={Receipt}>Comprobantes</TituloPantalla>
        {/* El listado se imprime desde reportes (`listado-comprobantes`), que
            exige rango. Aca el boton salia sin fechas y mandaba al papel todos
            los comprobantes que hubiera. */}
        <Button asChild>
          <Link to={irA.facturarPendientes()}>
            <Plus className="size-4" /> Facturar pendientes
          </Link>
        </Button>
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
        onRowClick={(c) => ver(c.id)}
        emptyMessage={cargando ? 'Cargando…' : 'No hay comprobantes en ese rango.'}
      />

      <Dialog open={detalle != null}
              onOpenChange={(v) => {
                if (v) return
                setDetalle(null)
                if (params.has('ver')) {
                  const otros = new URLSearchParams(params)
                  otros.delete('ver')
                  setParams(otros, { replace: true })
                }
              }}>
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
                    <span className="flex-1">#{o.id} · {formatearFecha(o.fecha)} · remito {o.remito || 's/n'}</span>
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
