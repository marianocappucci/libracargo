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
import type { DatosOrden, EntradaOrden } from '@/components/esquema-orden'
import { ORDEN_VACIA, esquemaOrden } from '@/components/esquema-orden'
import { FiltrosOrdenes } from '@/components/FiltrosOrdenes'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Form = UseFormReturn<EntradaOrden, unknown, DatosOrden>

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
      <select id={nombre} className="h-9 rounded-md border px-2 text-sm"
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

  const columnas = [
    { accessorKey: 'fecha', header: sortableHeader('Fecha') },
    { id: 'cliente', header: sortableHeader('Cliente'),
      accessorFn: (o: Orden) => nombreDe(opciones?.clientes, o.cliente_id) },
    { id: 'tramo', header: 'Tramo',
      accessorFn: (o: Orden) => `${nombreDe(opciones?.localidades, o.origen_id)} - ${nombreDe(opciones?.localidades, o.destino_id)}` },
    { id: 'fletero', header: sortableHeader('Fletero'),
      accessorFn: (o: Orden) => nombreDe(opciones?.fleteros, o.fletero_id) },
    { accessorKey: 'remito', header: 'Remito' },
    { accessorKey: 'total', header: sortableHeader('Total') },
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
        <Button onClick={() => abrir(null)}><Plus className="size-4" /> Nueva</Button>
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
