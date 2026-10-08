/** El listado de órdenes: una pantalla con filtros, no once pantallas. */
import { zodResolver } from '@hookform/resolvers/zod'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { IconoIndicador } from 'libra-ui/IconoIndicador'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { Ban, ClipboardList, Eye, Pencil, Plus, Printer } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { UseFormReturn } from 'react-hook-form'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router-dom'

import type { Filtros, Opciones, Orden } from '@/api/ordenes'
import { ETAPAS, cargarOpciones, ordenes as api } from '@/api/ordenes'
import { formatearKilos } from '@/api/cartas-porte'
import { useConfiguracion } from '@/api/configuracion'
import type { Localidad } from '@/api/localidades'
import { aOpcionLocalidad } from '@/api/localidades'
import { mensajeDeError } from '@/components/AbmMaestro'
import { AdjuntosDeOrden } from '@/components/AdjuntosDeOrden'
import { CambiarEtapa } from '@/components/CambiarEtapa'
import { EmitirCartaDePorte } from '@/components/EmitirCartaDePorte'
import { ElegirLocalidad } from '@/components/ElegirLocalidad'
import { SeccionFlete } from '@/components/FleteDeOrden'
import { KilosDelDetalle, SeccionKilos } from '@/components/KilosDeOrden'
import { OrdenImpresa } from '@/components/OrdenImpresa'
import type { DatosOrden, EntradaOrden } from '@/components/esquema-orden'
import { ORDEN_VACIA, esquemaOrden, formatearImporte } from '@/components/esquema-orden'
import { FiltrosOrdenes } from '@/components/FiltrosOrdenes'
import { EstadoDeOrden, EtapaDeOrden } from '@/components/EstadoDeOrden'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

type Form = UseFormReturn<EntradaOrden, unknown, DatosOrden>

const COLUMNA_OPCIONAL = {
  className: 'tabular-nums hidden xl:table-cell', colClassName: 'hidden xl:table-column', opcional: true,
}

const nombreDe = (
  lista: { id: number; etiqueta: string }[] | undefined, id: number | null,
) => lista?.find((o) => o.id === id)?.etiqueta ?? ''

function Campo({ form, nombre, etiqueta, tipo = 'text' }: {
  form: Form; nombre: keyof EntradaOrden; etiqueta: string; tipo?: string
}) {
  const error = form.formState.errors[nombre]
  return (
    <div className="grid gap-1">
      <Label htmlFor={nombre}>{etiqueta}</Label>
      <Input id={nombre} type={tipo} {...form.register(nombre)} />
      {error && <p className="text-destructive text-xs">{String(error.message)}</p>}
    </div>
  )
}

function Etapa({ form }: { form: Form }) {
  return (
    <div className="grid gap-1">
      <Label htmlFor="etapa">Etapa</Label>
      {/* select-cerrado: cinco valores fijos (`ETAPAS`), una constante del código: no hay nada que buscar. Es la etapa del viaje;
          el estado de facturación es otro dato y no se elige acá (lo cambia facturar). */}
      <select id="etapa" className="h-9 rounded-md border px-3 text-sm" {...form.register('etapa')}>
        {ETAPAS.map((e) => <option key={e.valor} value={e.valor}>{e.etiqueta}</option>)}
      </select>
    </div>
  )
}

function Elegir({ form, nombre, etiqueta, opciones, opcional }: {
  form: Form
  nombre: keyof EntradaOrden
  etiqueta: string
  opciones: { id: number; etiqueta: string }[]
  opcional?: boolean
}) {
  const error = form.formState.errors[nombre]
  // 🔑 Con buscador: cargar una orden es elegir entre 75 clientes, 186 fleteros
  // y 121 localidades, y el desplegable nativo obliga a encontrarlos a ojo.
  // `watch`/`setValue` en vez de `register` porque el control no es un `<input>`
  // y react-hook-form no puede engancharse solo.
  const valor = form.watch(nombre)
  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={nombre}>{etiqueta}</Label>
      <SelectBuscable
        id={nombre}
        value={valor === undefined || valor === null ? '' : String(valor)}
        onChange={(v) => form.setValue(nombre, v as never, { shouldValidate: true })}
        opciones={[{ value: '', label: opcional ? 'Sin asignar' : 'Elegir…' },
                   ...opciones.map((o) => ({ value: String(o.id), label: o.etiqueta }))]}
        placeholder={opcional ? 'Sin asignar' : 'Elegir…'}
        emptyMessage="No hay ninguno con ese nombre."
        ariaLabel={etiqueta}
        className="w-full min-w-0"
        aria-invalid={error ? true : undefined}
      />
      {error && <p className="text-destructive text-xs">{String(error.message)}</p>}
    </div>
  )
}

/** Origen y destino: el selector que busca en el maestro y en el catálogo de Argentina y del Mercosur, y deja cargar un paraje (ADR-041).
 *  La localidad que se trae del catálogo o se carga a mano se suma a la lista del formulario (`alIncorporar`) para que
 *  su nombre se pueda mostrar, y se elige. */
function ElegirLocalidadDeOrden({ form, nombre, etiqueta, opciones, alIncorporar }: {
  form: Form
  nombre: keyof EntradaOrden
  etiqueta: string
  opciones: Opciones['localidades']
  alIncorporar: (l: Localidad) => void
}) {
  const error = form.formState.errors[nombre]
  const valor = form.watch(nombre)
  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={nombre}>{etiqueta}</Label>
      <ElegirLocalidad
        id={nombre} etiqueta={etiqueta}
        valor={valor === undefined || valor === null ? '' : String(valor)}
        localidades={opciones}
        alElegir={(v) => form.setValue(nombre, v as never, { shouldValidate: true })}
        alIncorporar={alIncorporar}
        invalido={error ? true : undefined}
      >
        {error && <p className="text-destructive text-xs">{String(error.message)}</p>}
      </ElegirLocalidad>
    </div>
  )
}

export default function Ordenes() {
  const [filas, setFilas] = useState<Orden[]>([])
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [filtros, setFiltros] = useState<Filtros>({})
  const [detalle, setDetalle] = useState<Orden | null>(null)
  const [params, setParams] = useSearchParams()
  // La orden que se esta por imprimir. Se monta la hoja, se espera un
  // cuadro para que este en el DOM, y recien ahi se abre el dialogo del
  // navegador: `print()` fotografia lo que hay.
  const [aImprimir, setAImprimir] = useState<Orden | null>(null)
  const empresa = useConfiguracion()
  const [cargando, setCargando] = useState(true)
  const [abierto, setAbierto] = useState(false)
  const [editando, setEditando] = useState<Orden | null>(null)
  const [error, setError] = useState<string | null>(null)
  // La orden de la que se está emitiendo la carta de porte (ADR-043). Aparte del detalle: el asistente se abre encima.
  const [emitiendo, setEmitiendo] = useState<Orden | null>(null)

  const form = useForm<EntradaOrden, unknown, DatosOrden>({
    resolver: zodResolver(esquemaOrden),
    defaultValues: ORDEN_VACIA as EntradaOrden,
  })

  // Una localidad traída del catálogo o cargada como paraje desde el selector: entra a la lista del formulario (y al
  // filtro de la grilla) sin volver a pedir todas las opciones. Si ya estaba, se reemplaza: puede haber cambiado.
  const incorporarLocalidad = useCallback((l: Localidad) => {
    setOpciones((o) => {
      if (!o) return o
      const nueva = aOpcionLocalidad(l)
      const hay = o.localidades.some((x) => x.id === l.id)
      return { ...o, localidades: hay ? o.localidades.map((x) => (x.id === l.id ? nueva : x)) : [...o.localidades, nueva] }
    })
  }, [])

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // El enlace profundo: `/ordenes?ver=123` abre el detalle de esa orden.
  // Se pide POR ID y no se busca en la grilla, porque la orden a la que apunta
  // el enlace puede no estar entre las que los filtros de esta pantalla
  // trajeron -- y ahi el click desde la cuenta corriente no haria nada.
  const idAVer = params.get('ver')
  useEffect(() => {
    if (!idAVer) return
    let vigente = true
    api.traer(Number(idAVer))
      .then((o) => { if (vigente) setDetalle(o) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [idAVer])

  const recargar = useCallback(() => {
    setCargando(true)
    api.listar(filtros)
      .then(setFilas)
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [filtros])

  useEffect(recargar, [recargar])

  function abrir(orden: Orden | null) {
    setEditando(orden)
    setError(null)
    // Los kilos, los km y la tarifa por tonelada que no se saben vienen `null`: el campo del formulario es un texto, y
    // vacío es «no se sabe».
    const sinNulos = orden
      ? Object.fromEntries(Object.entries(orden).map(([k, v]) => [
        k, (k.startsWith('kg_') || k === 'km' || k === 'tarifa_tonelada') && v == null ? '' : v]))
      : null
    form.reset(sinNulos
      ? (sinNulos as unknown as EntradaOrden)
      : (ORDEN_VACIA as EntradaOrden))
    setAbierto(true)
  }

  const guardar = form.handleSubmit(async (datos) => {
    setError(null)
    try {
      if (editando) await api.editar(editando.id, datos)
      else await api.crear(datos)
      setAbierto(false)
      recargar()
    } catch (e) {
      // Acá llegan el 409 de "la orden está facturada" y los 422 del servidor.
      // La validación de Zod es para escribir cómodo; **la que manda es la del
      // backend**, que es la única que ve la base.
      setError(mensajeDeError(e))
    }
  })

  async function anular(orden: Orden) {
    setError(null)
    try {
      await api.anular(orden.id)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  function imprimir(orden: Orden) {
    setAImprimir(orden)
    requestAnimationFrame(() => requestAnimationFrame(() => {
      window.print()
      setAImprimir(null)
    }))
  }

  /** Una orden cambió de etapa desde el detalle: se actualiza la ficha y su fila sin volver a pedir el listado. */
  function etapaCambiada(orden: Orden) {
    setDetalle(orden)
    setFilas((actuales) => actuales.map((f) => (f.id === orden.id ? orden : f)))
  }

  const columnas = [
    { accessorKey: 'fecha', header: sortableHeader('Fecha') },
    { id: 'cliente', header: sortableHeader('Cliente'),
      accessorFn: (o: Orden) => nombreDe(opciones?.clientes, o.cliente_id) },
    { id: 'tramo', header: 'Tramo',
      accessorFn: (o: Orden) => `${nombreDe(opciones?.localidades, o.origen_id)} - ${nombreDe(opciones?.localidades, o.destino_id)}` },
    { id: 'fletero', header: sortableHeader('Fletero'),
      accessorFn: (o: Orden) => nombreDe(opciones?.fleteros, o.fletero_id) },
    { accessorKey: 'remito', header: 'Remito' },
    { id: 'total', header: sortableHeader('Total'),
      accessorFn: (o: Orden) => formatearImporte(o.total) },
    { id: 'etapa', header: sortableHeader('Etapa'),
      // Ordena por el avance del viaje, no por el alfabeto; liquidada y anulada van al final, como se leen.
      accessorFn: (o: Orden) => o.estado === 'anulada' ? ETAPAS.length + 1
        : o.estado === 'facturada' ? ETAPAS.length : ETAPAS.findIndex((e) => e.valor === o.etapa),
      cell: ({ row }: { row: { original: Orden } }) => <EtapaDeOrden orden={row.original} /> },
    // Los kilos netos, sólo donde hay ancho: en una pantalla angosta la tabla ya está justa y los kilos completos
    // (bruto, tara, neto) están en el detalle.
    { id: 'kg-carga', header: 'Kg carga', meta: COLUMNA_OPCIONAL,
      accessorFn: (o: Orden) => formatearKilos(o.kg_neto_carga) },
    { id: 'kg-descarga', header: 'Kg descarga', meta: COLUMNA_OPCIONAL,
      accessorFn: (o: Orden) => formatearKilos(o.kg_neto_descarga) },
    // Los km, también sólo donde hay ancho; la tarifa por tonelada está en el detalle.
    { id: 'km', header: 'Km', meta: COLUMNA_OPCIONAL, accessorFn: (o: Orden) => o.km ?? '—' },
    { id: 'estado', header: sortableHeader('Estado'),
      accessorFn: (o: Orden) => o.estado,
      cell: ({ row }: { row: { original: Orden } }) => (
        <EstadoDeOrden estado={row.original.estado} />
      ) },
    { id: 'acciones', header: '',
      cell: ({ row }: { row: { original: Orden } }) => (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="icon" aria-label="Ver detalle"
                  onClick={() => setDetalle(row.original)}>
            <Eye className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Imprimir orden"
                  onClick={() => imprimir(row.original)}>
            <Printer className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Editar"
                  onClick={() => abrir(row.original)}>
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Anular"
                  onClick={() => anular(row.original)}>
            <Ban className="size-4" />
          </Button>
        </div>
      ) },
  ]

  return (
    <div>
      <div className="mb-4">
        {/* El listado se imprime desde reportes (`listado-ordenes`), que exige
            rango: desde aca el boton salia con la pantalla recien abierta y
            mandaba las 4.337 ordenes al papel. El icono de la fila queda: es
            UNA orden, una hoja. */}
        <TituloPantalla
          icono={ClipboardList}
          acciones={<Button onClick={() => abrir(null)}><Plus className="size-4" /> Nueva</Button>}
        >
          Órdenes de carga
        </TituloPantalla>
      </div>

      <FiltrosOrdenes valor={filtros} opciones={opciones} alCambiar={setFiltros} />

      {/* Con el formulario abierto el error se lee ADENTRO, al lado del botón que lo causó: el de la página queda
          detrás del modal y el 422 («el neto no es bruto menos tara») no lo vería nadie. */}
      {error && !abierto && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <DataTable
        columns={columnas}
        data={filas}
        onRowClick={setDetalle}
        emptyMessage={cargando ? 'Cargando…' : 'Ninguna orden coincide con los filtros.'}
      />

      <Dialog open={abierto} onOpenChange={setAbierto}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editando ? 'Editar orden' : 'Nueva orden'}</DialogTitle>
          </DialogHeader>
          <form onSubmit={guardar} className="grid gap-3 md:grid-cols-2">
            <Campo form={form} nombre="fecha" etiqueta="Fecha" tipo="date" />
            <Campo form={form} nombre="remito" etiqueta="Remito" />
            <Elegir form={form} nombre="cliente_id" etiqueta="Cliente"
                    opciones={opciones?.clientes ?? []} />
            <Elegir form={form} nombre="fletero_id" etiqueta="Fletero"
                    opciones={opciones?.fleteros ?? []} opcional />
            <ElegirLocalidadDeOrden form={form} nombre="origen_id" etiqueta="Origen"
                                    opciones={opciones?.localidades ?? []} alIncorporar={incorporarLocalidad} />
            <ElegirLocalidadDeOrden form={form} nombre="destino_id" etiqueta="Destino"
                                    opciones={opciones?.localidades ?? []} alIncorporar={incorporarLocalidad} />
            <Elegir form={form} nombre="chofer_id" etiqueta="Chofer"
                    opciones={opciones?.choferes ?? []} opcional />
            <Elegir form={form} nombre="vehiculo_id" etiqueta="Vehículo"
                    opciones={opciones?.vehiculos ?? []} opcional />
            <Elegir form={form} nombre="tipo_carga_id" etiqueta="Tipo de carga"
                    opciones={opciones?.tipos ?? []} opcional />
            <Campo form={form} nombre="cantidad" etiqueta="Cantidad" />
            <Campo form={form} nombre="unidad" etiqueta="Unidad" />
            <Campo form={form} nombre="tarifa" etiqueta="Tarifa" />
            <Campo form={form} nombre="alicuota_iva" etiqueta="Alícuota de IVA (%)" />
            <Campo form={form} nombre="comision" etiqueta="Comisión" />
            <Campo form={form} nombre="observaciones" etiqueta="Observaciones" />
            <Etapa form={form} />
            <SeccionKilos form={form} />
            <SeccionFlete form={form} />
            {/* El IVA y el total NO se editan: los calcula el servidor desde la
                tarifa y la alícuota. Un campo editable mentiría sobre quién
                decide el importe, que es el defecto que trae el legado. */}
            <p className="text-muted-foreground text-sm md:col-span-2">
              El IVA y el total los calcula el servidor desde la tarifa y la alícuota.
            </p>
            {error && (
              <p role="alert" className="rounded border border-destructive/40 p-3 text-sm md:col-span-2">
                {error}
              </p>
            )}
            <DialogFooter className="md:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setAbierto(false)}>
                Cancelar
              </Button>
              <Button type="submit">Guardar</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* El detalle: click en "ver" y toda la orden en una ficha. Hasta ahora
          la unica forma de ver los campos que no entran en la grilla era abrir
          el formulario de edicion, que es otra cosa: ahi se toca. */}
      {/* Al cerrar se saca el `?ver=` de la URL: si quedara, el efecto de
          arriba lo volveria a abrir en la siguiente vuelta de render, y el
          dialogo no se podria cerrar. `replace` para no llenar el historial. */}
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
              {detalle && `Orden Nº ${String(detalle.id).padStart(8, '0')}`}
            </DialogTitle>
          </DialogHeader>
          {detalle && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              {([
                ['Fecha', detalle.fecha],
                ['Estado', detalle.estado],
                ['Cliente', nombreDe(opciones?.clientes, detalle.cliente_id)],
                ['Remito', detalle.remito ?? '—'],
                ['Origen', nombreDe(opciones?.localidades, detalle.origen_id)],
                ['Destino', nombreDe(opciones?.localidades, detalle.destino_id)],
                ['Fletero', nombreDe(opciones?.fleteros, detalle.fletero_id) || '—'],
                ['Chofer', nombreDe(opciones?.choferes, detalle.chofer_id) || '—'],
                ['Vehículo', nombreDe(opciones?.vehiculos, detalle.vehiculo_id) || '—'],
                ['Tipo de carga', nombreDe(opciones?.tipos, detalle.tipo_carga_id) || '—'],
                ['Cantidad',
                 [detalle.cantidad, detalle.unidad].filter(Boolean).join(' ')
                   || detalle.cantidad_legado || '—'],
                ['Tarifa', formatearImporte(detalle.tarifa)],
                ['Km', detalle.km == null ? '—' : String(detalle.km)],
                ['Tarifa por tonelada', formatearImporte(detalle.tarifa_tonelada) || '—'],
                [`IVA (${detalle.alicuota_iva}%)`, formatearImporte(detalle.iva)],
                ['Total', formatearImporte(detalle.total)],
                ['Comisión', formatearImporte(detalle.comision)],
                ['Comprobante', detalle.comprobante_id ? `#${detalle.comprobante_id}` : '—'],
              ] as [string, string][]).map(([etiqueta, valor]) => (
                <div key={etiqueta}>
                  <p className="text-muted-foreground text-xs">{etiqueta}</p>
                  <p className="font-medium">{valor}</p>
                </div>
              ))}
              <KilosDelDetalle orden={detalle} />
              <CambiarEtapa orden={detalle} alCambiar={etapaCambiada} />
              <AdjuntosDeOrden orden={detalle} />
              {detalle.observaciones && (
                <div className="col-span-2">
                  <p className="text-muted-foreground text-xs">Observaciones</p>
                  <p>{detalle.observaciones}</p>
                </div>
              )}
              {detalle.origen_legado && (
                <div className="col-span-2">
                  <p className="text-muted-foreground text-xs">
                    Viene del sistema anterior: {detalle.origen_legado}
                  </p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            {/* Una orden anulada no viaja: no se le emite carta de porte. */}
            {detalle && detalle.estado !== 'anulada' && (
              <Button variant="outline" onClick={() => setEmitiendo(detalle)}>
                <IconoIndicador concepto="cartasDePorte" /> Emitir carta de porte
              </Button>
            )}
            {detalle && (
              <Button variant="outline" onClick={() => imprimir(detalle)}>
                <Printer className="size-4" /> Imprimir orden
              </Button>
            )}
            <Button variant="ghost" onClick={() => setDetalle(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {emitiendo && (
        <EmitirCartaDePorte orden={emitiendo} abierto alCambiar={(v) => { if (!v) setEmitiendo(null) }} />
      )}

      {aImprimir && (
        <OrdenImpresa orden={aImprimir} opciones={opciones} empresa={empresa} />
      )}
    </div>
  )
}
