/** Comprobantes de proveedores: lo que el proveedor entrega y se le descuenta
 *  al fletero.
 *
 *  🔑 **La etiqueta y el modelo no dicen lo mismo, a propósito.** Adentro
 *  esto es un `GastoDeProveedor` —no es una factura de compra, y el ADR-021
 *  explica por qué con los números del legado—, pero en pantalla se llama
 *  como lo llaman el cliente y el sistema viejo. El modelo no tiene por qué
 *  imponerle su vocabulario a quien lo usa.
 *
 *  🔑 **Un gasto mueve dos cuentas**, y la pantalla lo dice antes de guardar: el
 *  proveedor al debe —lo que se le debe— y el fletero al haber —se le descuenta
 *  de lo que la agencia le debe—. En el sistema viejo eran dos `INSERT` sueltos
 *  y nada en pantalla explicaba que el alta tocaba dos cuentas.
 */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Ban, Pencil, Plus, ReceiptText } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import type { FiltrosDeGasto, Gasto } from '@/api/gastos'
import { gastos as api } from '@/api/gastos'
import type { Opcion, Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { formatearImporte } from '@/components/esquema-orden'
import { irA } from '@/navegacion'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { formatearFecha } from '@/components/esquema-orden'

const VACIO = {
  fecha: new Date().toISOString().slice(0, 10),
  proveedor_id: '' as number | '',
  fletero_id: '' as number | '',
  comprobante: '',
  descripcion: '',
  importe: '',
}

function nombre(lista: Opcion[] | undefined, id: number | null): string {
  return lista?.find((o) => o.id === id)?.etiqueta ?? ''
}

export default function Gastos() {
  const navegar = useNavigate()
  const [params, setParams] = useSearchParams()
  const [filas, setFilas] = useState<Gasto[]>([])
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [filtros, setFiltros] = useState<FiltrosDeGasto>({})
  const [abierto, setAbierto] = useState(false)
  const [editando, setEditando] = useState<Gasto | null>(null)
  const [borrador, setBorrador] = useState({ ...VACIO })
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

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

  // `/gastos?ver=123` abre ese gasto para editar. Es a donde lleva una linea de
  // cuenta corriente que salio de un gasto.
  const idAVer = params.get('ver')
  useEffect(() => {
    if (!idAVer) return
    let vigente = true
    api.traer(Number(idAVer))
      .then((g) => { if (vigente) abrir(g) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idAVer])

  function abrir(gasto: Gasto | null) {
    setEditando(gasto)
    setError(null)
    setBorrador(gasto
      ? {
        fecha: gasto.fecha, proveedor_id: gasto.proveedor_id, fletero_id: gasto.fletero_id,
        comprobante: gasto.comprobante ?? '', descripcion: gasto.descripcion,
        importe: gasto.importe,
      }
      : { ...VACIO })
    setAbierto(true)
  }

  function cerrar() {
    setAbierto(false)
    if (params.has('ver')) {
      const otros = new URLSearchParams(params)
      otros.delete('ver')
      setParams(otros, { replace: true })
    }
  }

  async function guardar() {
    setError(null)
    const cuerpo = {
      fecha: borrador.fecha,
      proveedor_id: Number(borrador.proveedor_id),
      fletero_id: Number(borrador.fletero_id),
      comprobante: borrador.comprobante.trim() || null,
      descripcion: borrador.descripcion.trim(),
      importe: borrador.importe,
    }
    try {
      if (editando) await api.editar(editando.id, cuerpo)
      else await api.crear(cuerpo)
      cerrar()
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function anular(gasto: Gasto) {
    setError(null)
    try {
      await api.anular(gasto.id)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  const columnas = [
    { id: 'fecha', header: sortableHeader('Fecha'), size: 110,
      accessorFn: (g: Gasto) => g.fecha,
      cell: ({ row }: { row: { original: Gasto } }) => formatearFecha(row.original.fecha) },
    { id: 'proveedor', header: 'Proveedor', size: 175,
      accessorFn: (g: Gasto) => nombre(opciones?.proveedores, g.proveedor_id) },
    { id: 'fletero', header: 'Se le descuenta a', size: 175,
      accessorFn: (g: Gasto) => nombre(opciones?.fleteros, g.fletero_id) },
    // La elastica, y la unica de texto libre. `whitespace-normal break-words`
    // porque el default de `TableCell` es `nowrap` y un detalle largo empujaria.
    { id: 'descripcion', header: 'Detalle', size: 190,
      meta: { stretch: true, className: 'whitespace-normal break-words' },
      accessorFn: (g: Gasto) => g.descripcion },
    { id: 'importe', header: 'Importe', size: 130,
      accessorFn: (g: Gasto) => formatearImporte(g.importe) },
    { id: 'estado', header: 'Estado', size: 100,
      cell: ({ row }: { row: { original: Gasto } }) => (
        <BadgeEstado tono={row.original.anulado ? 'negativo' : 'ok'}>
          {row.original.anulado ? 'anulado' : 'vigente'}
        </BadgeEstado>
      ) },
    { id: 'acciones', header: '', size: 90,
      cell: ({ row }: { row: { original: Gasto } }) => (
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" aria-label="Editar"
                  disabled={row.original.anulado}
                  onClick={(e: React.MouseEvent) => { e.stopPropagation(); abrir(row.original) }}>
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Anular"
                  disabled={row.original.anulado}
                  onClick={(e: React.MouseEvent) => { e.stopPropagation(); anular(row.original) }}>
            <Ban className="size-4" />
          </Button>
        </div>
      ) },
  ]

  const proveedores = opciones?.proveedores ?? []
  const fleteros = opciones?.fleteros ?? []

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <TituloPantalla icono={ReceiptText}>Comprobantes de proveedores</TituloPantalla>
          <p className="text-muted-foreground text-sm">
            Lo que el proveedor entrega y se le descuenta al fletero.
          </p>
        </div>
        {/* El listado se imprime desde reportes (`listado-gastos`), que exige
            rango. Este boton ni siquiera escribia los filtros en el encabezado
            de la hoja: dos papeles distintos salian identicos. */}
        <div className="no-imprimir flex gap-2">
          <Button onClick={() => abrir(null)}>
            <Plus className="size-4" /> Nuevo comprobante
          </Button>
        </div>
      </div>

      <div className="no-imprimir mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="grid gap-1">
          <Label htmlFor="g-desde">Desde</Label>
          <Input id="g-desde" type="date" value={filtros.desde ?? ''}
                 onChange={(e) => setFiltros({ ...filtros, desde: e.target.value || undefined })} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="g-hasta">Hasta</Label>
          <Input id="g-hasta" type="date" value={filtros.hasta ?? ''}
                 onChange={(e) => setFiltros({ ...filtros, hasta: e.target.value || undefined })} />
        </div>
        <Elegir id="g-proveedor" etiqueta="Proveedor" vacio="Todos"
                valor={filtros.proveedor_id === undefined ? '' : String(filtros.proveedor_id)}
                opciones={proveedores}
                alCambiar={(v) => setFiltros({ ...filtros, proveedor_id: v ? Number(v) : undefined })} />
        <Elegir id="g-fletero" etiqueta="Fletero" vacio="Todos"
                valor={filtros.fletero_id === undefined ? '' : String(filtros.fletero_id)}
                opciones={fleteros}
                alCambiar={(v) => setFiltros({ ...filtros, fletero_id: v ? Number(v) : undefined })} />
      </div>

      {error && (
        <p role="alert" className="border-destructive/40 mb-4 rounded border p-3 text-sm">
          {error}
        </p>
      )}

      <DataTable
        columns={columnas}
        data={filas}
        onRowClick={(g: Gasto) => navegar(irA.cuenta('proveedor', g.proveedor_id))}
        emptyMessage={cargando ? 'Cargando…' : 'No hay gastos en ese rango.'}
      />

      <Dialog open={abierto} onOpenChange={(v) => { if (!v) cerrar() }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editando ? `Editar comprobante ${editando.id}` : 'Nuevo comprobante'}
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-3">
            <div className="grid gap-1">
              <Label htmlFor="n-fecha">Fecha</Label>
              <Input id="n-fecha" type="date" value={borrador.fecha}
                     onChange={(e) => setBorrador({ ...borrador, fecha: e.target.value })} />
            </div>
            <Elegir id="n-proveedor" etiqueta="Proveedor" vacio="Elegir…"
                    valor={borrador.proveedor_id === '' ? '' : String(borrador.proveedor_id)}
                    opciones={proveedores}
                    alCambiar={(v) => setBorrador({ ...borrador, proveedor_id: v ? Number(v) : '' })} />
            <Elegir id="n-fletero" etiqueta="Se le descuenta a" vacio="Elegir…"
                    valor={borrador.fletero_id === '' ? '' : String(borrador.fletero_id)}
                    opciones={fleteros}
                    alCambiar={(v) => setBorrador({ ...borrador, fletero_id: v ? Number(v) : '' })} />
            <div className="grid gap-1">
              <Label htmlFor="n-comprobante">Remito o comprobante (opcional)</Label>
              <Input id="n-comprobante" value={borrador.comprobante}
                     onChange={(e) => setBorrador({ ...borrador, comprobante: e.target.value })} />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="n-descripcion">Detalle</Label>
              <Input id="n-descripcion" value={borrador.descripcion}
                     onChange={(e) => setBorrador({ ...borrador, descripcion: e.target.value })} />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="n-importe">Importe</Label>
              <Input id="n-importe" value={borrador.importe}
                     onChange={(e) => setBorrador({ ...borrador, importe: e.target.value })} />
            </div>

            {/* Lo que el alta hace, antes de que la persona apriete guardar. En
                el sistema viejo esto pasaba y nada lo decia. */}
            <p className="text-muted-foreground text-sm">
              Al guardar, este gasto <strong>suma</strong> al saldo del proveedor y{' '}
              <strong>descuenta</strong> del saldo del fletero.
            </p>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={cerrar}>Cancelar</Button>
            <Button onClick={guardar}
                    disabled={!borrador.proveedor_id || !borrador.fletero_id
                              || !borrador.descripcion.trim() || !borrador.importe}>
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
