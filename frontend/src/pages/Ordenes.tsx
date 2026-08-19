/** El listado de órdenes: una pantalla con filtros, no once pantallas. */
import { zodResolver } from '@hookform/resolvers/zod'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Ban, Pencil, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { UseFormReturn } from 'react-hook-form'
import { useForm } from 'react-hook-form'

import type { Filtros, Opciones, Orden } from '@/api/ordenes'
import { cargarOpciones, ordenes as api } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import type { Columna } from '@/components/impresion'
import { BotonImprimir, traerTodo } from '@/components/impresion'
import { sumarImportes } from '@/api/comprobantes'
import type { DatosOrden, EntradaOrden } from '@/components/esquema-orden'
import { ORDEN_VACIA, esquemaOrden, formatearImporte } from '@/components/esquema-orden'
import { FiltrosOrdenes } from '@/components/FiltrosOrdenes'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Form = UseFormReturn<EntradaOrden, unknown, DatosOrden>

/** Los filtros activos, en texto, para el encabezado de la hoja impresa.
 *  Dos papeles del mismo listado con filtros distintos tienen que poder
 *  distinguirse sin leer las filas. */
function describirFiltros(filtros: Filtros): string {
  const partes = Object.entries(filtros)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k.replace(/_id$/, '')}: ${v}`)
  return partes.length ? partes.join(' · ') : 'sin filtros'
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

function Elegir({ form, nombre, etiqueta, opciones, opcional }: {
  form: Form
  nombre: keyof EntradaOrden
  etiqueta: string
  opciones: { id: number; etiqueta: string }[]
  opcional?: boolean
}) {
  const error = form.formState.errors[nombre]
  return (
    <div className="grid gap-1">
      <Label htmlFor={nombre}>{etiqueta}</Label>
      <select id={nombre} className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
              {...form.register(nombre)}>
        <option value="">{opcional ? 'Sin asignar' : 'Elegir…'}</option>
        {opciones.map((o) => <option key={o.id} value={o.id}>{o.etiqueta}</option>)}
      </select>
      {error && <p className="text-destructive text-xs">{String(error.message)}</p>}
    </div>
  )
}

export default function Ordenes() {
  const [filas, setFilas] = useState<Orden[]>([])
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [filtros, setFiltros] = useState<Filtros>({})
  const [cargando, setCargando] = useState(true)
  const [abierto, setAbierto] = useState(false)
  const [editando, setEditando] = useState<Orden | null>(null)
  const [error, setError] = useState<string | null>(null)

  const form = useForm<EntradaOrden, unknown, DatosOrden>({
    resolver: zodResolver(esquemaOrden),
    defaultValues: ORDEN_VACIA as EntradaOrden,
  })

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

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
    form.reset(orden
      ? ({ ...orden } as unknown as EntradaOrden)
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

  const COLUMNAS_IMPRESAS: Columna<Orden>[] = [
    { encabezado: 'Fecha', valor: (o: Orden) => o.fecha },
    { encabezado: 'Cliente', valor: (o: Orden) => nombreDe(opciones?.clientes, o.cliente_id) },
    { encabezado: 'Origen', valor: (o: Orden) => nombreDe(opciones?.localidades, o.origen_id) },
    { encabezado: 'Destino', valor: (o: Orden) => nombreDe(opciones?.localidades, o.destino_id) },
    { encabezado: 'Fletero', valor: (o: Orden) => nombreDe(opciones?.fleteros, o.fletero_id) },
    { encabezado: 'Remito', valor: (o: Orden) => o.remito },
    { encabezado: 'Estado', valor: (o: Orden) => o.estado },
    { encabezado: 'Tarifa', valor: (o: Orden) => o.tarifa, numerica: true, moneda: true },
    { encabezado: 'Total', valor: (o: Orden) => o.total, numerica: true, moneda: true },
    { encabezado: 'Comisión', valor: (o: Orden) => o.comision, numerica: true, moneda: true },
  ]

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
    { id: 'estado', header: sortableHeader('Estado'),
      accessorFn: (o: Orden) => o.estado,
      cell: ({ row }: { row: { original: Orden } }) => (
        <Badge variant={row.original.estado === 'anulada' ? 'destructive' : 'secondary'}>
          {row.original.estado}
        </Badge>
      ) },
    { id: 'acciones', header: '',
      cell: ({ row }: { row: { original: Orden } }) => (
        <div className="flex justify-end gap-1">
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
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Órdenes de carga</h1>
        <div className="flex gap-2">
          {/* La hoja NO imprime lo que hay en pantalla: vuelve a pedir el
              listado con los mismos filtros. La grilla muestra una pagina y
              quien imprime un listado filtrado espera el listado. */}
          <BotonImprimir
            titulo="Órdenes de carga"
            filtros={describirFiltros(filtros)}
            columnas={COLUMNAS_IMPRESAS}
            traer={() => traerTodo((desplazamiento, limite) =>
              api.listar({ ...filtros, desplazamiento, limite }))}
            totales={(filas) => [
              { etiqueta: 'Órdenes', valor: String(filas.length) },
              { etiqueta: 'Total', valor: sumarImportes(filas.map((o) => o.total)) },
              { etiqueta: 'Comisión', valor: sumarImportes(filas.map((o) => o.comision)) },
            ]}
          />
          <Button onClick={() => abrir(null)}><Plus className="size-4" /> Nueva</Button>
        </div>
      </div>

      <FiltrosOrdenes valor={filtros} opciones={opciones} alCambiar={setFiltros} />

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <DataTable
        columns={columnas}
        data={filas}
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
            <Elegir form={form} nombre="origen_id" etiqueta="Origen"
                    opciones={opciones?.localidades ?? []} />
            <Elegir form={form} nombre="destino_id" etiqueta="Destino"
                    opciones={opciones?.localidades ?? []} />
            <Elegir form={form} nombre="chofer_id" etiqueta="Chofer"
                    opciones={opciones?.choferes ?? []} opcional />
            <Elegir form={form} nombre="vehiculo_id" etiqueta="Vehículo"
                    opciones={opciones?.vehiculos ?? []} opcional />
            <Elegir form={form} nombre="tipo_carga_id" etiqueta="Tipo de carga"
                    opciones={opciones?.tipos ?? []} opcional />
            <Elegir form={form} nombre="razon_social_id" etiqueta="Razón social"
                    opciones={opciones?.razones ?? []} opcional />
            <Campo form={form} nombre="cantidad" etiqueta="Cantidad" />
            <Campo form={form} nombre="unidad" etiqueta="Unidad" />
            <Campo form={form} nombre="tarifa" etiqueta="Tarifa" />
            <Campo form={form} nombre="alicuota_iva" etiqueta="Alícuota de IVA (%)" />
            <Campo form={form} nombre="comision" etiqueta="Comisión" />
            <Campo form={form} nombre="observaciones" etiqueta="Observaciones" />
            {/* El IVA y el total NO se editan: los calcula el servidor desde la
                tarifa y la alícuota. Un campo editable mentiría sobre quién
                decide el importe, que es el defecto que trae el legado. */}
            <p className="text-muted-foreground text-sm md:col-span-2">
              El IVA y el total los calcula el servidor desde la tarifa y la alícuota.
            </p>
            <DialogFooter className="md:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setAbierto(false)}>
                Cancelar
              </Button>
              <Button type="submit">Guardar</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
