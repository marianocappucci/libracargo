/** La barra de filtros. Es la razon de ser de F3: en el legado cada
 *  combinacion era una pantalla distinta, copiada de la anterior. */
import type { Filtros, Opciones } from '@/api/ordenes'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Props = {
  valor: Filtros
  opciones: Opciones | null
  alCambiar: (f: Filtros) => void
}

function Select({ id, etiqueta, valor, opciones, alCambiar }: {
  id: string
  etiqueta: string
  valor: number | undefined
  opciones: { id: number; etiqueta: string }[]
  alCambiar: (v: number | undefined) => void
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <select
        id={id} className="h-9 rounded-md border px-2 text-sm"
        value={valor ?? ''}
        onChange={(e) => alCambiar(e.target.value === '' ? undefined : Number(e.target.value))}
      >
        <option value="">Todos</option>
        {opciones.map((o) => <option key={o.id} value={o.id}>{o.etiqueta}</option>)}
      </select>
    </div>
  )
}

export function FiltrosOrdenes({ valor, opciones, alCambiar }: Props) {
  const set = (cambio: Partial<Filtros>) => alCambiar({ ...valor, ...cambio })
  const o = opciones

  return (
    <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
      <div className="grid gap-1">
        <Label htmlFor="f-desde">Desde</Label>
        <Input id="f-desde" type="date" value={valor.desde ?? ''}
               onChange={(e) => set({ desde: e.target.value || undefined })} />
      </div>
      <div className="grid gap-1">
        <Label htmlFor="f-hasta">Hasta</Label>
        <Input id="f-hasta" type="date" value={valor.hasta ?? ''}
               onChange={(e) => set({ hasta: e.target.value || undefined })} />
      </div>
      <Select id="f-cliente" etiqueta="Cliente" valor={valor.cliente_id}
              opciones={o?.clientes ?? []} alCambiar={(v) => set({ cliente_id: v })} />
      <Select id="f-fletero" etiqueta="Fletero" valor={valor.fletero_id}
              opciones={o?.fleteros ?? []} alCambiar={(v) => set({ fletero_id: v })} />
      <Select id="f-origen" etiqueta="Origen" valor={valor.origen_id}
              opciones={o?.localidades ?? []} alCambiar={(v) => set({ origen_id: v })} />
      <Select id="f-destino" etiqueta="Destino" valor={valor.destino_id}
              opciones={o?.localidades ?? []} alCambiar={(v) => set({ destino_id: v })} />
      <Select id="f-chofer" etiqueta="Chofer" valor={valor.chofer_id}
              opciones={o?.choferes ?? []} alCambiar={(v) => set({ chofer_id: v })} />
      <Select id="f-vehiculo" etiqueta="Vehículo" valor={valor.vehiculo_id}
              opciones={o?.vehiculos ?? []} alCambiar={(v) => set({ vehiculo_id: v })} />
      <Select id="f-tipo" etiqueta="Tipo de carga" valor={valor.tipo_carga_id}
              opciones={o?.tipos ?? []} alCambiar={(v) => set({ tipo_carga_id: v })} />

      <div className="grid gap-1">
        <Label htmlFor="f-estado">Estado</Label>
        <select id="f-estado" className="h-9 rounded-md border px-2 text-sm"
                value={valor.estado ?? ''}
                onChange={(e) => set({ estado: e.target.value || undefined })}>
          <option value="">Todos</option>
          <option value="pendiente">Pendiente</option>
          <option value="facturada">Facturada</option>
          <option value="anulada">Anulada</option>
        </select>
      </div>

      <div className="grid gap-1">
        <Label htmlFor="f-facturada">Facturación</Label>
        {/* Tres respuestas y no dos: "todas" no es lo mismo que "sin facturar".
            La segunda es la que en el legado era la pantalla de facturar
            pendientes. */}
        <select
          id="f-facturada" className="h-9 rounded-md border px-2 text-sm"
          value={valor.facturada === undefined ? '' : String(valor.facturada)}
          onChange={(e) => set({
            facturada: e.target.value === '' ? undefined : e.target.value === 'true',
          })}
        >
          <option value="">Todas</option>
          <option value="false">Sin facturar</option>
          <option value="true">Facturadas</option>
        </select>
      </div>

      <div className="grid gap-1">
        <Label htmlFor="f-q">Remito u observaciones</Label>
        <Input id="f-q" value={valor.q ?? ''}
               onChange={(e) => set({ q: e.target.value || undefined })} />
      </div>

      <div className="flex items-end">
        <Button variant="ghost" onClick={() => alCambiar({})}>Limpiar</Button>
      </div>
    </div>
  )
}
