/** El listado de cartas de porte: las CPE que ARCA informa por cada viaje, traídas por su CTG (ADR-036). Es la primera
 *  pestaña de «Cartas de porte» (`CartasDePorte`); el título de la pantalla es de ella, y los botones de acá van en esa línea
 *  (`AccionesDelTitulo`).
 *
 *  El listado muestra lo que importa para liquidar el flete: quién paga, quién maneja, cuántos kilos salieron y cuántos
 *  llegaron. Los de descarga los informa ARCA recién cuando el camión descarga, así que una carta «abierta» —sin
 *  descarga y sin estado final— se vuelve a consultar con «Actualizar» hasta que aparezcan.
 *
 *  🔑 **Traer es una acción de ARCA y no un alta**: no se tipea nada de la carta, se pide por CTG (ver
 *  `TraerCartasDePorte`). Lo único que se carga a mano es el vínculo con la orden de carga.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Download, FileDown, Link2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { MouseEvent } from 'react'
import { Link } from 'react-router-dom'

import type { CartaPorte, ResumenDeActualizar } from '@/api/cartas-porte'
import {
  cartasPorte, esEstadoFinal, formatearCuit, formatearDiaDelInstante, formatearKilos, nombreOCuit, tonoDeEstado,
} from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { AccionesDelTitulo } from '@/components/AccionesDelTitulo'
import { CompartirCartaDePorte } from '@/components/CompartirCartaDePorte'
import { FichaDeCartaDePorte } from '@/components/FichaDeCartaDePorte'
import { TraerCartasDePorte } from '@/components/TraerCartasDePorte'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/context/AuthContext'
import { irA } from '@/navegacion'

type Celda = { row: { original: CartaPorte } }

/** Los kilos de descarga, o por qué no están: una carta abierta los espera; una anulada no los va a tener. */
function kilosDeDescarga(c: CartaPorte): string {
  if (c.peso_neto_descarga != null) return formatearKilos(c.peso_neto_descarga)
  return esEstadoFinal(c.estado) ? '—' : 'pendiente'
}

const sinPropagar = (e: MouseEvent) => e.stopPropagation()

/** El tope de las observaciones de una anulación en ARCA. */
const MAX_OBSERVACIONES = 100

export function ListadoDeCartasDePorte() {
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const [filas, setFilas] = useState<CartaPorte[]>([])
  const [soloAbiertas, setSoloAbiertas] = useState(false)
  const [recarga, setRecarga] = useState(0)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [resumen, setResumen] = useState<ResumenDeActualizar | null>(null)
  const [actualizandoTodas, setActualizandoTodas] = useState(false)
  const [ocupada, setOcupada] = useState<number | null>(null)
  const [trayendo, setTrayendo] = useState(false)
  const [detalle, setDetalle] = useState<CartaPorte | null>(null)
  const [vinculando, setVinculando] = useState<CartaPorte | null>(null)
  const [numeroDeOrden, setNumeroDeOrden] = useState('')
  const [errorDeVinculo, setErrorDeVinculo] = useState<string | null>(null)
  // Anular en ARCA una carta emitida desde acá (ADR-043): sólo un administrador, y con un motivo opcional.
  const [anulando, setAnulando] = useState<CartaPorte | null>(null)
  const [observaciones, setObservaciones] = useState('')
  const [errorDeAnulacion, setErrorDeAnulacion] = useState<string | null>(null)
  const [enviandoAnulacion, setEnviandoAnulacion] = useState(false)

  useEffect(() => {
    let vigente = true
    setCargando(true)
    cartasPorte.listar({ abiertas: soloAbiertas })
      .then((r) => { if (vigente) { setFilas(r); setError(null) } })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [soloAbiertas, recarga])

  function reemplazar(carta: CartaPorte) {
    setFilas((actuales) => actuales.map((f) => (f.id === carta.id ? carta : f)))
  }

  async function actualizar(carta: CartaPorte) {
    if (carta.id === null) return
    setError(null); setAviso(null); setResumen(null); setOcupada(carta.id)
    try {
      reemplazar(await cartasPorte.actualizar(carta.id))
      setAviso(`CTG ${carta.nro_ctg} actualizada con lo que informa ARCA.`)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setOcupada(null)
    }
  }

  async function actualizarAbiertas() {
    setError(null); setAviso(null); setResumen(null); setActualizandoTodas(true)
    try {
      setResumen(await cartasPorte.actualizarAbiertas())
      setRecarga((n) => n + 1)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setActualizandoTodas(false)
    }
  }

  function abrirVinculo(carta: CartaPorte) {
    setVinculando(carta)
    setNumeroDeOrden(carta.orden_carga_id != null ? String(carta.orden_carga_id) : '')
    setErrorDeVinculo(null)
  }

  async function vincular(ordenId: number | null) {
    if (!vinculando || vinculando.id === null) return
    setErrorDeVinculo(null)
    try {
      reemplazar(await cartasPorte.vincular(vinculando.id, ordenId))
      setAviso(ordenId === null
        ? `CTG ${vinculando.nro_ctg} desvinculada de la orden.`
        : `CTG ${vinculando.nro_ctg} vinculada a la orden ${ordenId}.`)
      setVinculando(null)
    } catch (e) {
      // El 404 de «no existe la orden» se lee en el diálogo, al lado del número que lo causó.
      setErrorDeVinculo(mensajeDeError(e))
    }
  }

  function abrirAnulacion(carta: CartaPorte) {
    setAnulando(carta); setObservaciones(''); setErrorDeAnulacion(null)
  }

  async function anular() {
    if (!anulando || anulando.id === null || enviandoAnulacion) return
    setErrorDeAnulacion(null); setEnviandoAnulacion(true)
    try {
      const anulada = await cartasPorte.anular(anulando.id, observaciones.trim() || undefined)
      reemplazar(anulada)
      setDetalle((actual) => (actual?.id === anulada.id ? anulada : actual))
      setAviso(`CTG ${anulada.nro_ctg} anulada en ARCA.`)
      setAnulando(null)
    } catch (e) {
      // Se lee en el diálogo, al lado del botón que lo causó: el 409 («sólo se anulan las emitidas desde acá») o el
      // rechazo de ARCA con su código.
      setErrorDeAnulacion(mensajeDeError(e))
    } finally {
      setEnviandoAnulacion(false)
    }
  }

  const ordenValida = /^[1-9]\d*$/.test(numeroDeOrden.trim())

  const columnas = [
    { accessorKey: 'nro_ctg', header: sortableHeader('CTG') },
    { accessorKey: 'numero', header: 'N.º CPE' },
    { id: 'emision', header: sortableHeader('Emisión'),
      accessorFn: (c: CartaPorte) => c.fecha_emision ?? '',
      cell: ({ row }: Celda) => formatearDiaDelInstante(row.original.fecha_emision) },
    { id: 'estado', header: 'Estado',
      accessorFn: (c: CartaPorte) => c.estado_descripcion,
      cell: ({ row }: Celda) => (
        <BadgeEstado tono={tonoDeEstado(row.original.estado)}>{row.original.estado_descripcion}</BadgeEstado>
      ) },
    { id: 'pagador', header: 'Pagador del flete',
      accessorFn: (c: CartaPorte) => nombreOCuit(c.pagador_flete) },
    { id: 'chofer', header: 'Chofer',
      accessorFn: (c: CartaPorte) => `${c.chofer.nombre ?? ''} ${formatearCuit(c.chofer.cuit)}`.trim(),
      cell: ({ row }: Celda) => {
        const { nombre, cuit } = row.original.chofer
        return (
          <div>
            {nombre && <div>{nombre}</div>}
            <div className={nombre ? 'text-muted-foreground text-xs' : undefined}>{formatearCuit(cuit) || '—'}</div>
          </div>
        )
      } },
    { id: 'dominios', header: 'Dominios',
      accessorFn: (c: CartaPorte) => c.dominios.join(', ') || '—' },
    { id: 'kilos', header: 'Kg carga', meta: { className: 'tabular-nums' },
      accessorFn: (c: CartaPorte) => formatearKilos(c.peso_neto) },
    { id: 'kilos-descarga', header: 'Kg descarga', meta: { className: 'tabular-nums' },
      accessorFn: (c: CartaPorte) => kilosDeDescarga(c) },
    { id: 'orden', header: 'Orden',
      accessorFn: (c: CartaPorte) => c.orden_carga_id ?? '',
      cell: ({ row }: Celda) => row.original.orden_carga_id == null ? '—' : (
        <Link to={irA.orden(row.original.orden_carga_id)} className="underline" onClick={sinPropagar}>
          {row.original.orden_carga_id}
        </Link>
      ) },
    { id: 'acciones', header: '', meta: { acciones: true },
      cell: ({ row }: Celda) => {
        const carta = row.original
        return (
          // La fila entera abre el detalle: los botones no tienen que abrirlo también.
          <div className="flex justify-end gap-1" onClick={sinPropagar}>
            <Button variant="ghost" size="icon" aria-label="Actualizar" title="Actualizar desde ARCA"
                    disabled={ocupada === carta.id} onClick={() => actualizar(carta)}>
              <RefreshCw className="size-4" />
            </Button>
            {carta.tiene_pdf && carta.id !== null && (
              <Button variant="ghost" size="icon" asChild>
                <a href={cartasPorte.urlDelPdf(carta.id)} target="_blank" rel="noreferrer"
                   aria-label="PDF" title="Ver el PDF de ARCA">
                  <FileDown className="size-4" />
                </a>
              </Button>
            )}
            <Button variant="ghost" size="icon" aria-label="Vincular orden" title="Vincular con una orden de carga"
                    onClick={() => abrirVinculo(carta)}>
              <Link2 className="size-4" />
            </Button>
          </div>
        )
      } },
  ]

  return (
    <div>
      {/* Los botones de la pestaña van en la línea del título de la pantalla, arriba a la derecha. */}
      <AccionesDelTitulo>
        <Button variant="outline" onClick={actualizarAbiertas} disabled={actualizandoTodas}>
          <RefreshCw className="size-4" /> {actualizandoTodas ? 'Actualizando…' : 'Actualizar abiertas'}
        </Button>
        <Button onClick={() => setTrayendo(true)}>
          <Download className="size-4" /> Traer de ARCA
        </Button>
      </AccionesDelTitulo>

      <p className="text-muted-foreground mb-4 text-sm">
        Las cartas de porte electrónicas que ARCA informa por cada viaje. Los kilos de descarga llegan cuando el
        camión descarga: hasta entonces la carta está abierta y se puede actualizar.
      </p>

      <div className="mb-4 flex items-center gap-2">
        <input id="cpe-abiertas" type="checkbox" checked={soloAbiertas}
               onChange={(e) => setSoloAbiertas(e.target.checked)} />
        <Label htmlFor="cpe-abiertas">Sólo abiertas</Label>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">{error}</p>
      )}
      {aviso && <p role="status" className="mb-4 rounded border p-3 text-sm">{aviso}</p>}
      {resumen && (
        <section role="status" aria-label="Resumen de la actualización" className="mb-4 rounded border p-3 text-sm">
          <p className="font-medium">
            {resumen.actualizadas === 1
              ? 'Se actualizó 1 carta de porte'
              : `Se actualizaron ${resumen.actualizadas} cartas de porte`}
            {resumen.errores.length > 0 && `; ${resumen.errores.length === 1 ? '1 con error' : `${resumen.errores.length} con error`}`}.
          </p>
          {resumen.errores.length > 0 && (
            <ul className="mt-2 grid gap-1">
              {resumen.errores.map((e) => (
                <li key={e.ctg}>
                  <span className="font-mono">{e.ctg}</span>
                  <span className="text-destructive"> — {e.error}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <DataTable
        columns={columnas}
        data={filas}
        onRowClick={setDetalle}
        emptyMessage={cargando ? 'Cargando…'
          : soloAbiertas ? 'No hay cartas de porte abiertas.'
            : 'Todavía no hay cartas de porte. Traelas de ARCA con su CTG.'}
      />

      <TraerCartasDePorte abierto={trayendo} alCambiar={setTrayendo}
                          alGuardar={() => setRecarga((n) => n + 1)} />

      <Dialog open={detalle !== null} onOpenChange={(v) => { if (!v) setDetalle(null) }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{detalle && `Carta de porte ${detalle.numero || detalle.nro_ctg}`}</DialogTitle>
          </DialogHeader>
          {detalle && <FichaDeCartaDePorte carta={detalle} />}
          {detalle && <CompartirCartaDePorte carta={detalle} />}
          <DialogFooter>
            {/* Sólo las que emitió este sistema y que no están en un estado final, y sólo un administrador. */}
            {esAdmin && detalle?.emitida === true && !esEstadoFinal(detalle.estado) && (
              <Button variant="outline" className="text-destructive sm:mr-auto" onClick={() => abrirAnulacion(detalle)}>
                Anular
              </Button>
            )}
            <Button variant="ghost" onClick={() => setDetalle(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={anulando !== null} onOpenChange={(v) => { if (!v && !enviandoAnulacion) setAnulando(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{anulando && `Anular carta de porte ${anulando.numero || anulando.nro_ctg}`}</DialogTitle>
            <DialogDescription>
              Se anula en ARCA, a nombre de {anulando && formatearCuit(anulando.cuit_representada)}. No se puede
              deshacer.
            </DialogDescription>
          </DialogHeader>
          <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); void anular() }}>
            <div className="grid gap-1">
              <Label htmlFor="cpe-anular-obs">Observaciones</Label>
              <Input id="cpe-anular-obs" value={observaciones} maxLength={MAX_OBSERVACIONES}
                     onChange={(e) => setObservaciones(e.target.value)} />
              <p className="text-muted-foreground text-xs">
                Opcional, hasta {MAX_OBSERVACIONES} caracteres ({observaciones.length}/{MAX_OBSERVACIONES}).
              </p>
            </div>
            {errorDeAnulacion && (
              <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeAnulacion}</p>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" disabled={enviandoAnulacion} onClick={() => setAnulando(null)}>
                Cancelar
              </Button>
              <Button type="submit" variant="destructive" disabled={enviandoAnulacion}>
                {enviandoAnulacion ? 'Anulando…' : 'Anular en ARCA'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={vinculando !== null} onOpenChange={(v) => { if (!v) setVinculando(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{vinculando && `Vincular orden · CTG ${vinculando.nro_ctg}`}</DialogTitle>
          </DialogHeader>
          <form className="grid gap-3"
                onSubmit={(e) => { e.preventDefault(); if (ordenValida) vincular(Number(numeroDeOrden)) }}>
            <div className="grid gap-1">
              <Label htmlFor="cpe-orden">N.º de orden</Label>
              <Input id="cpe-orden" type="number" min={1} inputMode="numeric" value={numeroDeOrden}
                     onChange={(e) => setNumeroDeOrden(e.target.value)} />
            </div>
            {errorDeVinculo && (
              <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeVinculo}</p>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setVinculando(null)}>Cancelar</Button>
              {vinculando?.orden_carga_id != null && (
                <Button type="button" variant="outline" onClick={() => vincular(null)}>Desvincular</Button>
              )}
              <Button type="submit" disabled={!ordenValida}>Vincular</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
